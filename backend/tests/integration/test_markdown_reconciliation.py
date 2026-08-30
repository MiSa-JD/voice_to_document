from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any

from app.api import create_app
from app.config import Settings
from app.db import connect
from app.ingest import ingest_file
from app.pipeline import FakePipelineHandler
from app.reconciliation import reconcile_markdown_artifacts
from app.runtime import process_one_job
from fastapi.testclient import TestClient


def _completed_recording(settings: Settings) -> tuple[str, Path]:
    source = settings.recording_input_dir / "complete.m4a"
    shutil.copyfile(Path(__file__).parents[1] / "fixtures" / "complete.m4a", source)
    recording_id = ingest_file(settings.database_path, source).recording_id
    handler = FakePipelineHandler(settings, logging.getLogger("test"))
    while process_one_job(settings.database_path, handler, logging.getLogger("test")):
        pass
    with connect(settings.database_path) as connection:
        relative_path = connection.execute(
            "SELECT relative_path FROM artifacts WHERE kind = 'transcript_markdown'"
        ).fetchone()["relative_path"]
    return recording_id, settings.document_root / relative_path


def test_legacy_uuid_markdown_is_migrated_without_stt(
    settings_values: dict[str, Any],
) -> None:
    settings = Settings(**settings_values)
    recording_id, flat_path = _completed_recording(settings)
    legacy_path = settings.document_root / recording_id / "transcript.md"
    legacy_path.parent.mkdir()
    flat_path.replace(legacy_path)
    with connect(settings.database_path) as connection:
        connection.execute(
            """
            UPDATE artifacts SET relative_path = ?
            WHERE recording_id = ? AND kind = 'transcript_markdown'
            """,
            (f"{recording_id}/transcript.md", recording_id),
        )

    result = reconcile_markdown_artifacts(
        settings.database_path,
        settings.transcript_root,
        settings.document_root,
        logging.getLogger("test"),
    )

    assert result == (type(result))(inspected=1, repaired=1, failed=0)
    with connect(settings.database_path) as connection:
        artifact = connection.execute(
            "SELECT relative_path FROM artifacts WHERE kind = 'transcript_markdown'"
        ).fetchone()
        jobs = connection.execute(
            "SELECT kind, COUNT(*) AS count FROM jobs GROUP BY kind"
        ).fetchall()
    migrated = settings.document_root / artifact["relative_path"]
    assert migrated.is_file()
    assert migrated.parent == settings.document_root
    assert not legacy_path.exists()
    assert not legacy_path.parent.exists()
    assert [dict(row) for row in jobs] == [
        {"kind": "classify", "count": 1},
        {"kind": "finalize_speakers", "count": 1},
        {"kind": "transcribe", "count": 1},
    ]


def test_missing_flat_markdown_is_recreated_idempotently(settings_values: dict[str, Any]) -> None:
    settings = Settings(**settings_values)
    _recording_id, flat_path = _completed_recording(settings)
    expected = flat_path.read_bytes()
    flat_path.unlink()

    first = reconcile_markdown_artifacts(
        settings.database_path,
        settings.transcript_root,
        settings.document_root,
        logging.getLogger("test"),
    )
    second = reconcile_markdown_artifacts(
        settings.database_path,
        settings.transcript_root,
        settings.document_root,
        logging.getLogger("test"),
    )

    assert (first.repaired, second.inspected) == (1, 0)
    assert flat_path.read_bytes() == expected


def test_manual_category_markdown_is_recreated_with_manual_source(
    settings_values: dict[str, Any],
) -> None:
    settings = Settings(**settings_values)
    recording_id, flat_path = _completed_recording(settings)
    client = TestClient(create_app(settings))
    response = client.patch(
        f"/api/recordings/{recording_id}/category",
        json={"category": "강의", "expected_revision": 1},
    )
    assert response.status_code == 200
    handler = FakePipelineHandler(settings, logging.getLogger("test"))
    assert process_one_job(settings.database_path, handler, logging.getLogger("test"))
    expected = flat_path.read_bytes()
    flat_path.unlink()

    result = reconcile_markdown_artifacts(
        settings.database_path,
        settings.transcript_root,
        settings.document_root,
        logging.getLogger("test"),
    )

    assert result.repaired == 1
    assert flat_path.read_bytes() == expected
    assert b"Category Source: manual" in expected


def test_revision_mismatch_keeps_legacy_artifact_and_records_safe_audit(
    settings_values: dict[str, Any], caplog: Any
) -> None:
    settings = Settings(**settings_values)
    recording_id, flat_path = _completed_recording(settings)
    legacy_path = settings.document_root / recording_id / "transcript.md"
    legacy_path.parent.mkdir()
    flat_path.replace(legacy_path)
    with connect(settings.database_path) as connection:
        connection.execute(
            "UPDATE artifacts SET relative_path = ? WHERE kind = 'transcript_markdown'",
            (f"{recording_id}/transcript.md",),
        )
        json_relative = connection.execute(
            "SELECT relative_path FROM artifacts WHERE kind = 'transcript_json'"
        ).fetchone()["relative_path"]
    json_path = settings.transcript_root / json_relative
    payload = json.loads(json_path.read_text())
    payload["revision"] = 2
    json_path.write_text(json.dumps(payload), encoding="utf-8")

    result = reconcile_markdown_artifacts(
        settings.database_path,
        settings.transcript_root,
        settings.document_root,
        logging.getLogger("test"),
    )

    assert result.failed == 1
    assert legacy_path.is_file()
    with connect(settings.database_path) as connection:
        artifact = connection.execute(
            "SELECT relative_path FROM artifacts WHERE kind = 'transcript_markdown'"
        ).fetchone()["relative_path"]
        audit = connection.execute(
            """
            SELECT details_json FROM audit_events
            WHERE event_type = 'markdown_reconciliation_failed'
            """
        ).fetchone()["details_json"]
        status = connection.execute(
            "SELECT status FROM recordings WHERE id = ?", (recording_id,)
        ).fetchone()["status"]
    assert artifact == f"{recording_id}/transcript.md"
    assert json.loads(audit) == {"error_code": "TRANSCRIPT_IDENTITY_MISMATCH"}
    assert status == "COMPLETED"
    failure = next(
        record for record in caplog.records if record.msg == "markdown_reconciliation_failed"
    )
    assert failure.recording_id == recording_id
    assert failure.error_code == "TRANSCRIPT_IDENTITY_MISMATCH"


def test_render_failure_preserves_legacy_file_and_artifact(settings_values: dict[str, Any]) -> None:
    settings = Settings(**settings_values)
    recording_id, flat_path = _completed_recording(settings)
    legacy_path = settings.document_root / recording_id / "transcript.md"
    legacy_path.parent.mkdir()
    flat_path.replace(legacy_path)
    with connect(settings.database_path) as connection:
        connection.execute(
            "UPDATE artifacts SET relative_path = ? WHERE kind = 'transcript_markdown'",
            (f"{recording_id}/transcript.md",),
        )

    result = reconcile_markdown_artifacts(
        settings.database_path,
        settings.transcript_root,
        settings.document_root,
        logging.getLogger("test"),
        markdown_renderer=lambda _transcript: (_ for _ in ()).throw(RuntimeError("injected")),
    )

    assert result.failed == 1
    assert legacy_path.is_file()
    with connect(settings.database_path) as connection:
        relative_path = connection.execute(
            "SELECT relative_path FROM artifacts WHERE kind = 'transcript_markdown'"
        ).fetchone()["relative_path"]
    assert relative_path == f"{recording_id}/transcript.md"
