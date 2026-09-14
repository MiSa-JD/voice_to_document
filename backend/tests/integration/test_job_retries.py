from __future__ import annotations

import logging
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
from app.api import create_app
from app.config import Settings
from app.db import connect
from app.ingest import ingest_file
from app.job_failures import job_failure_policy
from app.job_retries import enqueue_retry
from app.jobs import Job, claim_next_job, complete_job, fail_job
from app.pipeline import FakePipelineHandler
from app.runtime import process_one_job
from fastapi.testclient import TestClient

LOGGER = logging.getLogger("test")


def failed_job(
    values: dict[str, Any], kind: str = "transcribe"
) -> tuple[Settings, TestClient, Job]:
    settings = Settings(**values)
    source = settings.recording_input_dir / "complete.m4a"
    shutil.copyfile(Path(__file__).parents[1] / "fixtures/complete.m4a", source)
    ingest_file(settings.database_path, source)
    handler = FakePipelineHandler(settings, LOGGER)
    while True:
        job = claim_next_job(settings.database_path)
        assert job is not None
        if job.kind == kind:
            fail_job(settings.database_path, job.id, "ARTIFACT_IO_ERROR", "private exception path")
            return settings, TestClient(create_app(settings)), job
        handler(job)
        complete_job(settings.database_path, job.id)


@pytest.mark.parametrize("kind", ["transcribe", "finalize_speakers", "classify"])
def test_retry_keeps_failure_history_and_gets_new_budget(values: dict[str, Any], kind: str) -> None:
    settings, client, job = failed_job(values, kind)
    detail = client.get(f"/api/recordings/{job.recording_id}")
    assert detail.status_code == 200
    assert "private exception path" not in detail.text
    item = next(item for item in detail.json()["jobs"] if item["id"] == job.id)
    assert item["failure_category"] == "transient" and item["recovery_action"] == "retry"
    request = {"job_id": job.id, "expected_revision": 1}
    accepted = client.post(f"/api/recordings/{job.recording_id}/retry", json=request)
    assert accepted.status_code == 202 and accepted.json()["created"]
    handler = FakePipelineHandler(settings, LOGGER)
    while process_one_job(settings.database_path, handler, LOGGER):
        pass
    with connect(settings.database_path) as connection:
        assert (
            connection.execute("SELECT status FROM jobs WHERE id = ?", (job.id,)).fetchone()[0]
            == "failed"
        )
        row = connection.execute(
            "SELECT status, attempts FROM jobs WHERE id = ?", (accepted.json()["job_id"],)
        ).fetchone()
        assert tuple(row) == ("succeeded", 1)


@pytest.fixture
def values(settings_values: dict[str, Any]) -> dict[str, Any]:
    return settings_values


@pytest.fixture(params=["missing", "file", "inaccessible"])
def real_api_values(
    settings_values: dict[str, Any], request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> dict[str, Any]:
    cache = settings_values["MODEL_CACHE_ROOT"] / "unusable"
    if request.param == "file":
        cache.touch()
    elif request.param == "inaccessible":
        cache.mkdir(mode=0)
        request.addfinalizer(lambda: cache.chmod(0o700))

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("API inspection must not initialize speech or call a provider")

    for target in (
        "app.worker.build_handler",
        "app.real_pipeline.RealSpeechPipelineHandler.__init__",
        "app.transcription._load_whisperx_runtime",
        "app.alignment._load_whisperx_alignment_runtime",
        "app.diarization._load_whisperx_diarization_runtime",
        "urllib.request.urlopen",
    ):
        monkeypatch.setattr(target, forbidden)
    return {
        **settings_values,
        "SERVICE_NAME": "api",
        "SPEECH_MODE": "real",
        "DOCUMENT_MODE": "real",
        "MODEL_CACHE_ROOT": cache,
        "LLM_PROVIDER": "openai_compatible",
        "LLM_BASE_URL": "http://127.0.0.1:1/v1",
        "LLM_MODEL": "test-snapshot",
        "LLM_API_KEY": "",
        "HF_TOKEN": "",
    }


@pytest.mark.parametrize("completed", [False, True])
def test_real_api_detail_preserves_failed_history_without_model_cache(
    real_api_values: dict[str, Any], completed: bool
) -> None:
    settings, client, job = failed_job(real_api_values)
    with connect(settings.database_path) as connection:
        connection.execute("UPDATE recordings SET status = 'FAILED'")
    if completed:
        with connect(settings.database_path) as connection:
            row = connection.execute("SELECT * FROM jobs WHERE id = ?", (job.id,)).fetchone()
            enqueue_retry(connection, row)
        handler = FakePipelineHandler(settings, LOGGER)
        while process_one_job(settings.database_path, handler, LOGGER):
            pass
    response = client.get(f"/api/recordings/{job.recording_id}")
    assert response.status_code == 200
    payload = response.json()
    assert payload["recording"]["status"] == ("COMPLETED" if completed else "FAILED")
    if completed:
        assert payload["segments"] and payload["artifacts"]
    item = next(row for row in payload["jobs"] if row["id"] == job.id)
    assert item["status"] == "failed"
    assert item["recovery_action"] == ("none" if completed else "retry")


def test_real_api_concurrent_retry_preserves_history(real_api_values: dict[str, Any]) -> None:
    settings, client, job = failed_job(real_api_values)

    def submit(_: int) -> dict[str, Any]:
        response = client.post(
            f"/api/recordings/{job.recording_id}/retry",
            json={"job_id": job.id, "expected_revision": 1},
        )
        assert response.status_code == 202
        return dict(response.json())

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(submit, range(2)))
    assert len({row["job_id"] for row in responses}) == 1
    assert sum(row["created"] for row in responses) == 1
    assert submit(0) == {**responses[0], "created": False}
    with connect(settings.database_path) as connection:
        rows = connection.execute("SELECT id, status FROM jobs").fetchall()
        assert {(row["id"], row["status"]) for row in rows} == {
            (job.id, "failed"),
            (responses[0]["job_id"], "queued"),
        }


@pytest.mark.parametrize("change", ["revision", "active", "missing_source", "fingerprint"])
def test_real_api_recovery_conflicts_remain_409(
    real_api_values: dict[str, Any], change: str
) -> None:
    settings, client, job = failed_job(real_api_values)
    with connect(settings.database_path) as connection:
        if change == "revision":
            connection.execute("UPDATE recordings SET revision = 2")
        elif change == "fingerprint":
            connection.execute("UPDATE jobs SET settings_fingerprint = 'changed'")
        elif change == "active":
            from app.state import _enqueue

            _enqueue(connection, job.recording_id, "render", 1, "render-v1")
        else:
            (settings.recording_input_dir / "complete.m4a").unlink()
    detail = client.get(f"/api/recordings/{job.recording_id}")
    assert detail.status_code == 200
    item = next(row for row in detail.json()["jobs"] if row["id"] == job.id)
    assert item["recovery_action"] == "none"
    assert (
        client.post(
            f"/api/recordings/{job.recording_id}/retry",
            json={"job_id": job.id, "expected_revision": 1},
        ).status_code
        == 409
    )


def test_concurrent_retry_creates_only_one_child(settings_values: dict[str, Any]) -> None:
    settings, client, job = failed_job(settings_values)

    def submit(_: int) -> dict[str, Any]:
        response = client.post(
            f"/api/recordings/{job.recording_id}/retry",
            json={"job_id": job.id, "expected_revision": 1},
        )
        assert response.status_code == 202
        return dict(response.json())

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(submit, range(2)))
    assert len({row["job_id"] for row in responses}) == 1
    assert sum(row["created"] for row in responses) == 1
    with connect(settings.database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 2


@pytest.mark.parametrize(
    "change",
    [
        "UPDATE recordings SET revision = 2",
        "UPDATE jobs SET status = 'succeeded'",
        "UPDATE jobs SET settings_fingerprint = 'changed'",
    ],
)
def test_retry_rejects_changed_state(settings_values: dict[str, Any], change: str) -> None:
    settings, client, job = failed_job(settings_values)
    with connect(settings.database_path) as connection:
        connection.execute(change)
    assert (
        client.post(
            f"/api/recordings/{job.recording_id}/retry",
            json={"job_id": job.id, "expected_revision": 1},
        ).status_code
        == 409
    )
    assert (
        client.post(
            "/api/recordings/not-owner/retry", json={"job_id": job.id, "expected_revision": 1}
        ).status_code
        == 404
    )


def test_missing_source_disables_retry(settings_values: dict[str, Any]) -> None:
    settings, client, job = failed_job(settings_values)
    (settings.recording_input_dir / "complete.m4a").unlink()
    payload = client.get(f"/api/recordings/{job.recording_id}").json()
    assert payload["jobs"][0]["recovery_action"] == "none"
    assert (
        client.post(
            f"/api/recordings/{job.recording_id}/retry",
            json={"job_id": job.id, "expected_revision": 1},
        ).status_code
        == 409
    )


def test_summary_failure_routes_to_dedicated_request(settings_values: dict[str, Any]) -> None:
    _, client, job = failed_job(settings_values, "summarize")
    item = next(
        row
        for row in client.get(f"/api/recordings/{job.recording_id}").json()["jobs"]
        if row["id"] == job.id
    )
    assert item["recovery_action"] == "request_summary"
    assert (
        client.post(
            f"/api/recordings/{job.recording_id}/retry",
            json={"job_id": job.id, "expected_revision": 1},
        ).status_code
        == 409
    )


@pytest.mark.parametrize(
    ("code", "category", "retryable"),
    [
        ("MODEL_OOM", "action_required", False),
        ("MODEL_DOWNLOAD_FAILED", "transient", True),
        ("SUMMARY_TIMEOUT", "transient", True),
        ("SUMMARY_INVALID_OUTPUT", "invalid_output", False),
        ("MALFORMED_CLASSIFICATION", "invalid_output", False),
        ("UNEXPECTED_JOB_ERROR", "internal", False),
    ],
)
def test_shared_failure_policy(code: str, category: str, retryable: bool) -> None:
    policy = job_failure_policy(code)
    assert policy is not None
    assert policy.category == category and policy.retryable == retryable


def test_retranscription_failure_requires_new_hints(settings_values: dict[str, Any]) -> None:
    settings, client, first = failed_job(settings_values)
    accepted = client.post(
        f"/api/recordings/{first.recording_id}/retry",
        json={"job_id": first.id, "expected_revision": 1},
    )
    assert accepted.status_code == 202
    handler = FakePipelineHandler(settings, LOGGER)
    while process_one_job(settings.database_path, handler, LOGGER):
        pass
    requested = client.post(
        f"/api/recordings/{first.recording_id}/retranscriptions",
        json={
            "expected_revision": 1,
            "language": "en",
            "content_description": "test hint",
            "terms": ["test"],
            "confirm_impact": True,
        },
    )
    assert requested.status_code == 202
    rerun = claim_next_job(settings.database_path)
    assert rerun is not None
    fail_job(settings.database_path, rerun.id, "MODEL_OOM", "safe")
    detail = client.get(f"/api/recordings/{first.recording_id}").json()
    item = next(item for item in detail["jobs"] if item["id"] == rerun.id)
    assert item["recovery_action"] == "retranscribe"
    assert (
        client.post(
            f"/api/recordings/{first.recording_id}/retry",
            json={"job_id": rerun.id, "expected_revision": 1},
        ).status_code
        == 409
    )
    with connect(settings.database_path) as connection:
        assert tuple(
            connection.execute(
                "SELECT content_hint, terms_json FROM retranscription_requests"
            ).fetchone()
        ) == (None, None)

    # Re-entering the same options explicitly is a new request, not restored private hints.
    replacement = client.post(
        f"/api/recordings/{first.recording_id}/retranscriptions",
        json={
            "expected_revision": 1,
            "language": "en",
            "content_description": "test hint",
            "terms": ["test"],
            "confirm_impact": True,
        },
    )
    assert replacement.status_code == 202
    assert replacement.json()["request_id"] != requested.json()["request_id"]
    while process_one_job(settings.database_path, handler, LOGGER):
        pass
    with connect(settings.database_path) as connection:
        assert (
            connection.execute("SELECT status FROM jobs WHERE id = ?", (rerun.id,)).fetchone()[0]
            == "failed"
        )
        assert connection.execute("SELECT revision FROM recordings").fetchone()[0] == 2


def test_automatic_retry_timing_and_exhaustion_are_server_decisions(
    settings_values: dict[str, Any],
) -> None:
    settings, client, job = failed_job(settings_values)
    with connect(settings.database_path) as connection:
        connection.execute(
            "UPDATE jobs SET status = 'queued', attempts = 2, "
            "available_at = '2099-01-01T00:00:00+00:00'"
        )
    item = client.get(f"/api/recordings/{job.recording_id}").json()["jobs"][0]
    assert item["automatic_retry"] == "scheduled"
    assert item["next_run_at"].startswith("2099-01-01")
    with connect(settings.database_path) as connection:
        connection.execute("UPDATE jobs SET status = 'failed', attempts = 3")
    item = client.get(f"/api/recordings/{job.recording_id}").json()["jobs"][0]
    assert item["automatic_retry"] == "exhausted" and item["next_run_at"] is None
    with connect(settings.database_path) as connection:
        connection.execute("UPDATE jobs SET error_code = 'SUMMARY_INVALID_OUTPUT'")
    item = client.get(f"/api/recordings/{job.recording_id}").json()["jobs"][0]
    assert item["automatic_retry"] == "stopped" and item["failure_category"] == "invalid_output"
