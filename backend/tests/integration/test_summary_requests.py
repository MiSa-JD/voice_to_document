from __future__ import annotations

import io
import json
import logging
import shutil
import urllib.request
from pathlib import Path
from typing import Any

import pytest
from app.api import create_app
from app.config import Settings
from app.db import connect
from app.ingest import ingest_file
from app.pipeline import FakePipelineHandler
from app.runtime import process_one_job
from app.summary import RetryableSummaryError, SummaryProviderError, SummaryTimeoutError
from fastapi.testclient import TestClient


def _manual_summary_recording(
    settings_values: dict[str, Any],
) -> tuple[Settings, TestClient, str]:
    values = {**settings_values, "AUTO_SUMMARY_CATEGORIES": "강의"}
    settings = Settings(**values)
    source = settings.recording_input_dir / "complete.m4a"
    shutil.copyfile(Path(__file__).parents[1] / "fixtures" / "complete.m4a", source)
    recording_id = ingest_file(settings.database_path, source).recording_id
    handler = FakePipelineHandler(settings, logging.getLogger("test"))
    while process_one_job(settings.database_path, handler, logging.getLogger("test")):
        pass
    return settings, TestClient(create_app(settings)), recording_id


def test_manual_summary_request_is_idempotent_and_audited_once(
    settings_values: dict[str, Any],
) -> None:
    settings, client, recording_id = _manual_summary_recording(settings_values)

    created = client.post(f"/api/recordings/{recording_id}/summary", json={"expected_revision": 1})
    duplicate = client.post(
        f"/api/recordings/{recording_id}/summary", json={"expected_revision": 1}
    )

    assert created.status_code == 202
    assert created.json()["created"] is True
    assert created.json()["job_status"] == "queued"
    assert duplicate.status_code == 200
    assert duplicate.json() == {**created.json(), "created": False}
    with connect(settings.database_path) as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM jobs WHERE recording_id = ? AND kind = 'summarize'",
                (recording_id,),
            ).fetchone()[0]
            == 1
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM audit_events WHERE event_type = 'summary_requested'"
            ).fetchone()[0]
            == 1
        )

    handler = FakePipelineHandler(settings, logging.getLogger("test"))
    assert process_one_job(settings.database_path, handler, logging.getLogger("test"))
    succeeded = client.post(
        f"/api/recordings/{recording_id}/summary", json={"expected_revision": 1}
    )
    assert succeeded.status_code == 200
    assert succeeded.json()["job_status"] == "succeeded"
    assert succeeded.json()["created"] is False


def test_failed_summary_can_create_a_new_job(settings_values: dict[str, Any]) -> None:
    settings, client, recording_id = _manual_summary_recording(settings_values)
    first = client.post(f"/api/recordings/{recording_id}/summary", json={"expected_revision": 1})
    with connect(settings.database_path) as connection:
        connection.execute(
            "UPDATE jobs SET status = 'failed' WHERE id = ?", (first.json()["job_id"],)
        )
        connection.execute("UPDATE recordings SET status = 'FAILED' WHERE id = ?", (recording_id,))

    retried = client.post(f"/api/recordings/{recording_id}/summary", json={"expected_revision": 1})

    assert retried.status_code == 202
    assert retried.json()["created"] is True
    assert retried.json()["job_id"] != first.json()["job_id"]
    with connect(settings.database_path) as connection:
        assert (
            connection.execute(
                "SELECT status FROM recordings WHERE id = ?", (recording_id,)
            ).fetchone()[0]
            == "SUMMARIZING"
        )


def test_summary_request_reports_stable_precondition_errors(
    settings_values: dict[str, Any],
) -> None:
    settings, client, recording_id = _manual_summary_recording(settings_values)

    missing = client.post("/api/recordings/missing/summary", json={"expected_revision": 1})
    conflict = client.post(
        f"/api/recordings/{recording_id}/summary", json={"expected_revision": 99}
    )
    with connect(settings.database_path) as connection:
        connection.execute("UPDATE recordings SET category = NULL WHERE id = ?", (recording_id,))
    not_ready = client.post(
        f"/api/recordings/{recording_id}/summary", json={"expected_revision": 1}
    )

    assert (missing.status_code, missing.json()["error"]["code"]) == (
        404,
        "RECORDING_NOT_FOUND",
    )
    assert (conflict.status_code, conflict.json()["error"]["code"]) == (
        409,
        "REVISION_CONFLICT",
    )
    assert (not_ready.status_code, not_ready.json()["error"]["code"]) == (
        422,
        "SUMMARY_NOT_READY",
    )


def test_stale_summary_job_finishes_without_overwriting_artifacts(
    settings_values: dict[str, Any],
) -> None:
    settings, client, recording_id = _manual_summary_recording(settings_values)
    response = client.post(f"/api/recordings/{recording_id}/summary", json={"expected_revision": 1})
    with connect(settings.database_path) as connection:
        connection.execute("UPDATE recordings SET revision = 2 WHERE id = ?", (recording_id,))

    handler = FakePipelineHandler(settings, logging.getLogger("test"))
    assert process_one_job(settings.database_path, handler, logging.getLogger("test"))

    with connect(settings.database_path) as connection:
        assert (
            connection.execute(
                "SELECT status FROM jobs WHERE id = ?", (response.json()["job_id"],)
            ).fetchone()[0]
            == "succeeded"
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM artifacts WHERE recording_id = ? AND kind = 'summary_json'",
                (recording_id,),
            ).fetchone()[0]
            == 0
        )


def test_detail_derives_summary_policy_status_job_and_requestability(
    settings_values: dict[str, Any],
) -> None:
    settings, client, recording_id = _manual_summary_recording(settings_values)

    initial = client.get(f"/api/recordings/{recording_id}").json()
    assert (
        initial["summary_status"],
        initial["summary_policy"],
        initial["summary_job"],
        initial["summary_can_request"],
    ) == ("not_requested", "manual", None, True)

    client.post(f"/api/recordings/{recording_id}/summary", json={"expected_revision": 1})
    queued = client.get(f"/api/recordings/{recording_id}").json()
    assert queued["summary_status"] == "queued"
    assert queued["summary_job"]["kind"] == "summarize"
    assert queued["summary_can_request"] is False

    handler = FakePipelineHandler(settings, logging.getLogger("test"))
    assert process_one_job(settings.database_path, handler, logging.getLogger("test"))
    succeeded = client.get(f"/api/recordings/{recording_id}").json()
    assert succeeded["summary_status"] == "succeeded"
    assert succeeded["summary"]["template"] == "meeting"

    with connect(settings.database_path) as connection:
        connection.execute(
            "UPDATE recordings SET revision = 2, status = 'COMPLETED' WHERE id = ?",
            (recording_id,),
        )
    stale = client.get(f"/api/recordings/{recording_id}").json()
    assert stale["summary_status"] == "stale"
    assert stale["summary"] is None
    assert stale["summary_can_request"] is True


@pytest.mark.parametrize("failure", [SummaryTimeoutError, RetryableSummaryError, OSError])
@pytest.mark.parametrize("succeed", [True, False])
def test_summary_worker_retries_until_success_or_final_failure(
    settings_values: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    failure: type[Exception],
    succeed: bool,
) -> None:
    settings, client, recording_id = _manual_summary_recording(settings_values)
    response = client.post(f"/api/recordings/{recording_id}/summary", json={"expected_revision": 1})
    job_id = response.json()["job_id"]
    handler = FakePipelineHandler(settings, logging.getLogger("test"))
    target: Any
    if failure is OSError:
        import app.pipeline as pipeline

        target, name = pipeline, "write_summary_artifacts"
    else:
        target, name = handler.summary_adapter, "summarize"
    original = getattr(target, name)

    def fail(*args: Any, **kwargs: Any) -> None:
        raise failure("private-test-secret")

    monkeypatch.setattr(target, name, fail)
    for attempt in range(1, 4):
        if attempt == 3 and succeed:
            monkeypatch.setattr(target, name, original)
        assert process_one_job(settings.database_path, handler, logging.getLogger("test"))
        with connect(settings.database_path) as connection:
            job = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            recording = connection.execute(
                "SELECT * FROM recordings WHERE id = ?", (recording_id,)
            ).fetchone()
            assert job["attempts"] == attempt
            assert job["status"] == (
                "queued" if attempt < 3 else "succeeded" if succeed else "failed"
            )
            assert recording["status"] == (
                "SUMMARIZING" if attempt < 3 else "COMPLETED" if succeed else "FAILED"
            )
            assert "private-test-secret" not in str(job["error_message"])
            assert "private-test-secret" not in str(recording["last_error_message"])
            connection.execute(
                "UPDATE jobs SET available_at = '2000-01-01' WHERE id = ?", (job_id,)
            )
    if succeed:
        with connect(settings.database_path) as connection:
            rows = connection.execute(
                "SELECT kind, COUNT(*) FROM artifacts WHERE recording_id = ? "
                "AND kind LIKE 'summary_%' AND revision = 1 GROUP BY kind",
                (recording_id,),
            ).fetchall()
            assert {row[0]: row[1] for row in rows} == {"summary_json": 1, "summary_markdown": 1}
    else:
        retried = client.post(
            f"/api/recordings/{recording_id}/summary", json={"expected_revision": 1}
        )
        assert retried.status_code == 202
        monkeypatch.setattr(target, name, original)
        assert process_one_job(settings.database_path, handler, logging.getLogger("test"))
        assert (
            client.get(f"/api/recordings/{recording_id}").json()["recording"]["status"]
            == "COMPLETED"
        )


@pytest.mark.parametrize("stale", [True, False])
def test_summary_permanent_failure_protects_new_revision(
    settings_values: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    stale: bool,
) -> None:
    settings, client, recording_id = _manual_summary_recording(settings_values)
    client.post(f"/api/recordings/{recording_id}/summary", json={"expected_revision": 1})
    handler = FakePipelineHandler(settings, logging.getLogger("test"))

    def fail(*args: Any, **kwargs: Any) -> None:
        if stale:
            with connect(settings.database_path) as connection:
                connection.execute(
                    "UPDATE recordings SET revision = 2 WHERE id = ?", (recording_id,)
                )
        raise SummaryProviderError("private-test-secret")

    monkeypatch.setattr(handler.summary_adapter, "summarize", fail)
    assert process_one_job(settings.database_path, handler, logging.getLogger("test"))
    with connect(settings.database_path) as connection:
        row = connection.execute(
            "SELECT status FROM recordings WHERE id = ?", (recording_id,)
        ).fetchone()
        assert row[0] == ("SUMMARIZING" if stale else "FAILED")


@pytest.mark.parametrize(
    ("failure", "code", "reason"),
    [
        (
            SummaryProviderError("private-test-secret", reason="evidence"),
            "SUMMARY_INVALID_OUTPUT",
            "evidence",
        ),
        (ValueError("private-test-secret"), "SUMMARY_INVALID_INPUT", "input_validation"),
        (RuntimeError("private-test-secret"), "SUMMARY_PIPELINE_ERROR", "unexpected"),
    ],
)
def test_summary_boundary_logs_only_safe_reason(
    settings_values: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
    code: str,
    reason: str,
) -> None:
    from app.log import JsonFormatter

    settings, client, recording_id = _manual_summary_recording(settings_values)
    client.post(f"/api/recordings/{recording_id}/summary", json={"expected_revision": 1})
    output = io.StringIO()
    log_handler = logging.StreamHandler(output)
    log_handler.setFormatter(JsonFormatter("test"))
    logger = logging.getLogger("safe-summary-test")
    logger.addHandler(log_handler)
    handler = FakePipelineHandler(settings, logger)

    def fail(*args: Any, **kwargs: Any) -> None:
        raise failure

    monkeypatch.setattr(handler.summary_adapter, "summarize", fail)
    try:
        assert process_one_job(settings.database_path, handler, logger)
    finally:
        logger.removeHandler(log_handler)
    assert reason in output.getvalue()
    assert "private-test-secret" not in output.getvalue()
    assert "INVALID_FAKE_RESULT" not in output.getvalue()
    with connect(settings.database_path) as connection:
        row = connection.execute(
            "SELECT last_error_code, last_error_message FROM recordings WHERE id = ?",
            (recording_id,),
        ).fetchone()
        assert row[0] == code
        assert "private-test-secret" not in row[1]


@pytest.mark.parametrize("succeeds", [True, False])
def test_worker_diagnostics_link_actual_job_revision_and_result(
    settings_values: dict[str, Any],
    succeeds: bool,
) -> None:
    from app.log import JsonFormatter
    from app.openai_summary import OpenAISummaryAdapter
    from app.summary import summary_settings_fingerprint

    settings, client, recording_id = _manual_summary_recording(settings_values)
    output = io.StringIO()
    sink = logging.StreamHandler(output)
    sink.setFormatter(JsonFormatter("worker-test"))
    logger = logging.Logger("worker-test", logging.INFO)
    logger.addHandler(sink)
    calls = 0

    def transport(request: urllib.request.Request, timeout: float) -> bytes:
        nonlocal calls
        calls += 1
        assert isinstance(request.data, bytes)
        body = json.loads(request.data)
        material = json.loads(body["input"].split("\n")[-1])
        segment = material["segments"][0]
        fact = {
            "text": "공개 테스트 사실",
            "evidence": [
                {
                    "segment_id": segment["segment_id"],
                    "quote": None,
                }
            ],
        }
        value = (
            {
                "template": "meeting",
                "purpose": fact,
                "discussion": [],
                "decisions": [],
                "action_items": [],
                "open_questions": [],
            }
            if succeeds and calls == 2
            else {"PRIVATE_KEY": "PRIVATE_VALUE"}
        )
        return json.dumps(
            {
                "output": [
                    {
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(value),
                            }
                        ]
                    }
                ]
            }
        ).encode()

    adapter = OpenAISummaryAdapter(
        base_url="https://example.invalid",
        api_key="PRIVATE_KEY",
        model="test",
        transport=transport,
    )
    # Queue with the adapter fingerprint used by the worker in this test.
    response = client.post(f"/api/recordings/{recording_id}/summary", json={"expected_revision": 1})
    assert response.status_code == 202
    with connect(settings.database_path) as connection:
        connection.execute(
            "UPDATE jobs SET settings_fingerprint = ?, attempts = 1 "
            "WHERE recording_id = ? AND kind = 'summarize'",
            (summary_settings_fingerprint(adapter, "회의"), recording_id),
        )
    handler = FakePipelineHandler(settings, logger)
    handler.summary_adapter = adapter
    assert process_one_job(settings.database_path, handler, logger)
    events = [json.loads(line) for line in output.getvalue().splitlines()]
    diagnostics = [
        e
        for e in events
        if e["event"].startswith("summary_validation") or e["event"] == "summary_request_started"
    ]
    assert len(diagnostics) == 4
    outcome = next(
        e for e in events if e["event"] == ("job_succeeded" if succeeds else "job_failed")
    )
    assert all(e["job_id"] == outcome["job_id"] for e in diagnostics)
    assert all(e["job_attempt"] == outcome["attempt"] == 2 for e in diagnostics)
    assert all(e["input_revision"] == 1 for e in diagnostics)
    assert [e["provider_attempt"] for e in diagnostics] == [1, 1, 2, 2]
    assert diagnostics[-1]["event"] == (
        "summary_validation_succeeded" if succeeds else "summary_validation_failed"
    )
    assert "PRIVATE" not in output.getvalue()
    assert "exception" not in output.getvalue()
    with connect(settings.database_path) as connection:
        row = connection.execute(
            "SELECT status, error_code, error_message FROM jobs WHERE id = ?",
            (outcome["job_id"],),
        ).fetchone()
    assert row["status"] == ("succeeded" if succeeds else "failed")
    if not succeeds:
        assert row["error_code"] == "SUMMARY_INVALID_OUTPUT"
        assert "PRIVATE" not in row["error_message"]


def test_real_api_worker_fingerprint_and_timestamp_artifacts(
    settings_values: dict[str, Any],
) -> None:
    from app.openai_summary import OpenAISummaryAdapter
    from app.summary import configured_summary_settings_fingerprint, summary_settings_fingerprint

    settings, _, recording_id = _manual_summary_recording(settings_values)
    settings = settings.model_copy(update={"document_mode": "real", "llm_model": "test"})
    client = TestClient(create_app(settings))

    def transport(request: urllib.request.Request, timeout: float) -> bytes:
        assert isinstance(request.data, bytes)
        material = json.loads(json.loads(request.data)["input"].split("\n")[-1])
        fact = {
            "text": "공개 사실",
            "evidence": [{"segment_id": material["segments"][0]["segment_id"], "quote": None}],
        }
        value = {
            "template": "meeting",
            "purpose": fact,
            "discussion": [],
            "decisions": [],
            "action_items": [],
            "open_questions": [],
        }
        return json.dumps(
            {"output": [{"content": [{"type": "output_text", "text": json.dumps(value)}]}]}
        ).encode()

    adapter = OpenAISummaryAdapter(
        base_url="https://example.invalid",
        api_key="",
        model="test",
        transport=transport,
        max_context_chars=settings.summary_context_max_chars,
    )
    expected = summary_settings_fingerprint(adapter, "회의")
    # main c346b02, model=test, default context: provider v2 contract.
    assert expected != "27d7111a75cb7c456c4257db1ea32633035a2d0aca21aa52fafc5a6d54346b15"
    assert configured_summary_settings_fingerprint(settings, "회의") == expected
    created = client.post(f"/api/recordings/{recording_id}/summary", json={"expected_revision": 1})
    assert created.status_code == 202
    with connect(settings.database_path) as connection:
        row = connection.execute(
            "SELECT settings_fingerprint FROM jobs WHERE id = ?", (created.json()["job_id"],)
        ).fetchone()
        assert row[0] == expected
    handler = FakePipelineHandler(settings, logging.getLogger("test"), summary_adapter=adapter)
    assert process_one_job(settings.database_path, handler, logging.getLogger("test"))
    detail = client.get(f"/api/recordings/{recording_id}").json()
    assert detail["summary_status"] == "succeeded"
    evidence = detail["summary"]["purpose"]["evidence"][0]
    segment = next(s for s in detail["segments"] if s["id"] == evidence["segment_id"])
    assert (evidence["start_ms"], evidence["end_ms"]) == (segment["start_ms"], segment["end_ms"])
    with connect(settings.database_path) as connection:
        rows = connection.execute(
            "SELECT kind, relative_path FROM artifacts "
            "WHERE recording_id = ? AND kind LIKE 'summary_%'",
            (recording_id,),
        ).fetchall()
    assert {row["kind"] for row in rows} == {"summary_json", "summary_markdown"}
    for row in rows:
        text = (settings.summary_root / row["relative_path"]).read_text()
        if row["kind"] == "summary_json":
            payload = json.loads(text)
            assert payload["schema_version"] == 1
            assert payload["summary"]["purpose"]["evidence"][0] == evidence
            assert payload["summary_fingerprint"] == adapter.fingerprint
        else:
            assert "공개 사실" in text
            from app.renderer import format_timestamp

            assert (
                f"{format_timestamp(evidence['start_ms'])}–{format_timestamp(evidence['end_ms'])}"
                in text
            )


@pytest.mark.parametrize("completed", [False, True])
def test_fingerprint_upgrade_preserves_existing_job_and_artifact_behavior(
    settings_values: dict[str, Any],
    completed: bool,
) -> None:
    from app.openai_summary import OpenAISummaryAdapter

    settings, old_client, recording_id = _manual_summary_recording(settings_values)
    first = old_client.post(
        f"/api/recordings/{recording_id}/summary", json={"expected_revision": 1}
    )
    logger = logging.getLogger("test")
    if completed:
        assert process_one_job(
            settings.database_path, FakePipelineHandler(settings, logger), logger
        )
    with connect(settings.database_path) as connection:
        before = [
            dict(row)
            for row in connection.execute(
                "SELECT * FROM artifacts WHERE recording_id = ?", (recording_id,)
            )
        ]
    with connect(settings.database_path) as connection:
        # Public baseline fingerprint from main c346b02, model=test.
        connection.execute(
            "UPDATE jobs SET settings_fingerprint = ? WHERE id = ?",
            (
                "27d7111a75cb7c456c4257db1ea32633035a2d0aca21aa52fafc5a6d54346b15",
                first.json()["job_id"],
            ),
        )
    settings = settings.model_copy(update={"document_mode": "real", "llm_model": "test"})
    client = TestClient(create_app(settings))
    adapter = OpenAISummaryAdapter(base_url="https://example.invalid", api_key="", model="test")
    if not completed:
        blocked = client.post(
            f"/api/recordings/{recording_id}/summary", json={"expected_revision": 1}
        )
        assert blocked.status_code == 422
        assert blocked.json()["error"]["code"] == "SUMMARY_IN_PROGRESS"
        # Existing behavior: obsolete fingerprints return without calling the provider.
        assert process_one_job(
            settings.database_path,
            FakePipelineHandler(settings, logger, summary_adapter=adapter),
            logger,
        )
    detail = client.get(f"/api/recordings/{recording_id}").json()
    assert detail["summary_status"] == ("succeeded" if completed else "failed")
    assert (detail["summary"] is not None) is completed
    with connect(settings.database_path) as connection:
        assert (
            connection.execute(
                "SELECT status FROM jobs WHERE id = ?", (first.json()["job_id"],)
            ).fetchone()[0]
            == "succeeded"
        )
        assert [
            dict(row)
            for row in connection.execute(
                "SELECT * FROM artifacts WHERE recording_id = ?", (recording_id,)
            )
        ] == before
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM jobs WHERE recording_id = ? AND kind = 'summarize'",
                (recording_id,),
            ).fetchone()[0]
            == 1
        )
    if completed:
        # A changed fingerprint alone neither marks an existing artifact stale nor queues a job.
        new = client.post(f"/api/recordings/{recording_id}/summary", json={"expected_revision": 1})
        assert new.status_code == 202
        assert new.json()["job_id"] != first.json()["job_id"]
        duplicate = client.post(
            f"/api/recordings/{recording_id}/summary", json={"expected_revision": 1}
        )
        assert duplicate.status_code == 200
        assert duplicate.json()["job_id"] == new.json()["job_id"]
    else:
        # The old skipped job leaves the recording SUMMARIZING: drain before upgrading.
        retry = client.post(
            f"/api/recordings/{recording_id}/summary", json={"expected_revision": 1}
        )
        assert retry.status_code == 422
        assert retry.json()["error"]["code"] == "SUMMARY_NOT_READY"
