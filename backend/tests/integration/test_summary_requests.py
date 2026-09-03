from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

from app.api import create_app
from app.config import Settings
from app.db import connect
from app.ingest import ingest_file
from app.pipeline import FakePipelineHandler
from app.runtime import process_one_job
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
