from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any

from app.config import Settings
from app.db import connect
from app.discovery import StabilityTracker
from app.pipeline import FakePipelineHandler
from app.runtime import discover_once, process_one_job


class FakeClock:
    def __init__(self) -> None:
        self.value = 100.0

    def __call__(self) -> float:
        return self.value


def test_file_detection_to_revision_matched_markdown_survives_restart(
    settings_values: dict[str, Any],
) -> None:
    settings_values.update({"FILE_STABLE_SECONDS": 1, "SERVICE_NAME": "worker"})
    settings = Settings(**settings_values)
    source = settings.recording_input_dir / "detected.m4a"
    shutil.copyfile(Path(__file__).parents[1] / "fixtures" / "complete.m4a", source)
    clock = FakeClock()
    tracker = StabilityTracker(1, clock)
    logger = logging.getLogger("stt-markdown-e2e")

    assert discover_once(settings, tracker, logger) == []
    clock.value += 1
    registrations = discover_once(settings, tracker, logger)
    assert len(registrations) == 1
    recording_id = registrations[0].recording_id

    handler = FakePipelineHandler(settings, logger)
    while process_one_job(settings.database_path, handler, logger):
        pass

    with connect(settings.database_path) as connection:
        recording = connection.execute(
            "SELECT status, revision FROM recordings WHERE id = ?", (recording_id,)
        ).fetchone()
        artifacts = connection.execute(
            """
            SELECT kind, relative_path, schema_version, revision FROM artifacts
            WHERE recording_id = ? ORDER BY kind
            """,
            (recording_id,),
        ).fetchall()
    assert dict(recording) == {"status": "COMPLETED", "revision": 1}
    assert [row["kind"] for row in artifacts] == [
        "transcript_json",
        "transcript_markdown",
    ]
    assert {row["revision"] for row in artifacts} == {1}

    json_row = artifacts[0]
    markdown_row = artifacts[1]
    json_path = settings.transcript_root / json_row["relative_path"]
    markdown_path = settings.document_root / markdown_row["relative_path"]
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    markdown_before_restart = markdown_path.read_bytes()
    assert payload["recording_id"] == recording_id
    assert payload["revision"] == 1
    assert payload["classification"]["schema_version"] == 1
    assert f"Recording ID: `{recording_id}`" in markdown_before_restart.decode()
    assert "Revision: 1" in markdown_before_restart.decode()
    assert "SPEAKER_00" in markdown_before_restart.decode()

    restarted_handler = FakePipelineHandler(settings, logger)
    assert not process_one_job(settings.database_path, restarted_handler, logger)
    assert markdown_path.read_bytes() == markdown_before_restart
    assert not list(settings.document_root.rglob("*.tmp"))
