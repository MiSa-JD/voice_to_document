from __future__ import annotations

from pathlib import Path

import pytest
from app.db import connect
from app.repository import register_recording
from app.schema import RecordingStatus
from app.state import (
    ALLOWED_TRANSITIONS,
    InvalidTransitionError,
    enqueue_job,
    transition_recording,
)


def _recording(tmp_path: Path) -> tuple[Path, str]:
    source = tmp_path / "source.m4a"
    source.write_bytes(b"audio")
    database_path = tmp_path / "app.db"
    result = register_recording(database_path, source, "d" * 64, 5, 1000)
    return database_path, result.recording_id


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (current, target)
        for current, targets in ALLOWED_TRANSITIONS.items()
        for target in targets
        if current is not RecordingStatus.FAILED
    ],
)
def test_allowed_transitions_are_persisted(
    tmp_path: Path,
    current: RecordingStatus,
    target: RecordingStatus,
) -> None:
    database_path, recording_id = _recording(tmp_path)
    with connect(database_path) as connection:
        connection.execute(
            "UPDATE recordings SET status = ? WHERE id = ?", (current.value, recording_id)
        )

    transition_recording(database_path, recording_id, target, "TEST", "failure")

    with connect(database_path) as connection:
        row = connection.execute(
            "SELECT status, last_error_code FROM recordings WHERE id = ?", (recording_id,)
        ).fetchone()
    assert row["status"] == target.value
    assert row["last_error_code"] == ("TEST" if target is RecordingStatus.FAILED else None)


def test_impossible_transition_is_rejected(tmp_path: Path) -> None:
    database_path, recording_id = _recording(tmp_path)

    with pytest.raises(InvalidTransitionError, match="cannot transition"):
        transition_recording(database_path, recording_id, RecordingStatus.COMPLETED)


def test_same_effective_job_is_enqueued_once(tmp_path: Path) -> None:
    database_path, recording_id = _recording(tmp_path)

    first = enqueue_job(database_path, recording_id, "classify", 1, "fake-document-v1")
    second = enqueue_job(database_path, recording_id, "classify", 1, "fake-document-v1")

    assert first.created is True
    assert second.created is False
    assert first.job_id == second.job_id
