from __future__ import annotations

import io
import logging
import shutil
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

    def fail(*args: Any) -> None:
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

    def fail(*args: Any) -> None:
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
