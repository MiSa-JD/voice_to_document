from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

from app.config import Settings
from app.db import connect
from app.discovery import StabilityTracker
from app.jobs import Job
from app.runtime import discover_once, process_one_job

FIXTURES = Path(__file__).parents[1] / "fixtures"


class FakeClock:
    def __init__(self) -> None:
        self.value = 100.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def test_scanner_worker_restart_and_duplicate_flow(
    settings_values: dict[str, Any],
) -> None:
    settings_values["FILE_STABLE_SECONDS"] = 1
    settings = Settings(**settings_values)
    complete = settings.recording_input_dir / "first.m4a"
    duplicate = settings.recording_input_dir / "같은 내용.m4a"
    corrupt = settings.recording_input_dir / "손상.m4a"
    shutil.copyfile(FIXTURES / "complete.m4a", complete)
    shutil.copyfile(FIXTURES / "complete.m4a", duplicate)
    shutil.copyfile(FIXTURES / "corrupt.m4a", corrupt)
    clock = FakeClock()
    tracker = StabilityTracker(1, clock)
    logger = logging.getLogger("integration")

    assert discover_once(settings, tracker, logger) == []
    clock.advance(1)
    discovered = discover_once(settings, tracker, logger)
    assert len(discovered) == 2
    handled: list[Job] = []
    assert process_one_job(settings.database_path, handled.append, logger) is True
    assert process_one_job(settings.database_path, handled.append, logger) is False

    restarted_clock = FakeClock()
    restarted_tracker = StabilityTracker(1, restarted_clock)
    assert discover_once(settings, restarted_tracker, logger) == []
    restarted_clock.advance(1)
    rediscovered = discover_once(settings, restarted_tracker, logger)

    assert len(rediscovered) == 2
    assert all(result.created is False for result in rediscovered)
    assert process_one_job(settings.database_path, handled.append, logger) is False
    with connect(settings.database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM recordings").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1
        assert connection.execute("SELECT status FROM jobs").fetchone()[0] == "succeeded"
        audit = connection.execute(
            "SELECT event_type, details_json FROM audit_events ORDER BY created_at LIMIT 1"
        ).fetchone()
    assert audit["event_type"] == "input_rejected"
    assert "손상.m4a" in audit["details_json"]
    assert str(settings.recording_input_dir) not in audit["details_json"]
