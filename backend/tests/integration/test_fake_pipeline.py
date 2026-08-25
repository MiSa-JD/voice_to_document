from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

from app.config import Settings
from app.db import connect
from app.ingest import ingest_file
from app.pipeline import FakePipelineHandler
from app.runtime import process_one_job


def test_complete_fixture_reaches_completed_with_single_artifacts(
    tmp_path: Path,
    settings_values: dict[str, Any],
) -> None:
    settings = Settings(**settings_values)
    source = Path(settings.recording_input_dir) / "complete.m4a"
    shutil.copyfile(Path(__file__).parents[1] / "fixtures" / "complete.m4a", source)
    result = ingest_file(settings.database_path, source)
    handler = FakePipelineHandler(settings, logging.getLogger("test"))

    while process_one_job(settings.database_path, handler, logging.getLogger("test")):
        pass

    with connect(settings.database_path) as connection:
        recording = connection.execute(
            "SELECT status, category FROM recordings WHERE id = ?", (result.recording_id,)
        ).fetchone()
        jobs = connection.execute("SELECT kind, status FROM jobs ORDER BY created_at").fetchall()
        artifacts = connection.execute("SELECT kind FROM artifacts ORDER BY kind").fetchall()
    assert dict(recording) == {"status": "COMPLETED", "category": "회의"}
    assert [dict(job) for job in jobs] == [
        {"kind": "transcribe", "status": "succeeded"},
        {"kind": "classify", "status": "succeeded"},
        {"kind": "summarize", "status": "succeeded"},
    ]
    assert [row["kind"] for row in artifacts] == [
        "summary_json",
        "summary_markdown",
        "transcript_json",
        "transcript_markdown",
    ]

    assert not process_one_job(settings.database_path, handler, logging.getLogger("test"))
    with connect(settings.database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0] == 4


def test_review_fixture_stops_before_classification(
    tmp_path: Path,
    settings_values: dict[str, Any],
) -> None:
    settings = Settings(**settings_values)
    source = Path(settings.recording_input_dir) / "speaker-review.m4a"
    shutil.copyfile(Path(__file__).parents[1] / "fixtures" / "speaker-review.m4a", source)
    result = ingest_file(settings.database_path, source)
    handler = FakePipelineHandler(settings, logging.getLogger("test"))

    assert process_one_job(settings.database_path, handler, logging.getLogger("test"))

    with connect(settings.database_path) as connection:
        recording = connection.execute(
            "SELECT status, needs_speaker_review FROM recordings WHERE id = ?",
            (result.recording_id,),
        ).fetchone()
        jobs = connection.execute("SELECT kind FROM jobs").fetchall()
    assert dict(recording) == {"status": "SPEAKER_REVIEW", "needs_speaker_review": 1}
    assert [row["kind"] for row in jobs] == ["transcribe"]
