from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path

from app.db import connect, migrate_database, utc_now
from app.schema import RecordingStatus

ALLOWED_TRANSITIONS: dict[RecordingStatus, frozenset[RecordingStatus]] = {
    RecordingStatus.DISCOVERED: frozenset({RecordingStatus.TRANSCRIBING, RecordingStatus.FAILED}),
    RecordingStatus.TRANSCRIBING: frozenset(
        {
            RecordingStatus.SPEAKER_REVIEW,
            RecordingStatus.CLASSIFYING,
            RecordingStatus.FAILED,
        }
    ),
    RecordingStatus.SPEAKER_REVIEW: frozenset(
        {RecordingStatus.CLASSIFYING, RecordingStatus.FAILED}
    ),
    RecordingStatus.CLASSIFYING: frozenset(
        {
            RecordingStatus.READY_FOR_SUMMARY,
            RecordingStatus.SUMMARIZING,
            RecordingStatus.FAILED,
        }
    ),
    RecordingStatus.READY_FOR_SUMMARY: frozenset(
        {RecordingStatus.SUMMARIZING, RecordingStatus.COMPLETED, RecordingStatus.FAILED}
    ),
    RecordingStatus.SUMMARIZING: frozenset({RecordingStatus.COMPLETED, RecordingStatus.FAILED}),
    RecordingStatus.COMPLETED: frozenset({RecordingStatus.SUMMARIZING}),
    RecordingStatus.FAILED: frozenset(
        {
            RecordingStatus.DISCOVERED,
            RecordingStatus.TRANSCRIBING,
            RecordingStatus.CLASSIFYING,
            RecordingStatus.READY_FOR_SUMMARY,
            RecordingStatus.SUMMARIZING,
        }
    ),
}


class InvalidTransitionError(ValueError):
    pass


@dataclass(frozen=True)
class EnqueueResult:
    job_id: str
    created: bool


def transition_recording(
    database_path: Path,
    recording_id: str,
    target: RecordingStatus,
    error_code: str | None = None,
    error_message: str | None = None,
) -> None:
    migrate_database(database_path)
    with connect(database_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        _transition(connection, recording_id, target, error_code, error_message)
        connection.commit()


def transition_and_enqueue(
    database_path: Path,
    recording_id: str,
    target: RecordingStatus,
    kind: str,
    input_revision: int,
    settings_fingerprint: str,
) -> EnqueueResult:
    migrate_database(database_path)
    with connect(database_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        _transition(connection, recording_id, target)
        result = _enqueue(
            connection,
            recording_id,
            kind,
            input_revision,
            settings_fingerprint,
        )
        connection.commit()
        return result


def enqueue_job(
    database_path: Path,
    recording_id: str,
    kind: str,
    input_revision: int,
    settings_fingerprint: str,
) -> EnqueueResult:
    migrate_database(database_path)
    with connect(database_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        result = _enqueue(
            connection,
            recording_id,
            kind,
            input_revision,
            settings_fingerprint,
        )
        connection.commit()
        return result


def _transition(
    connection: sqlite3.Connection,
    recording_id: str,
    target: RecordingStatus,
    error_code: str | None = None,
    error_message: str | None = None,
) -> None:
    row = connection.execute(
        "SELECT status FROM recordings WHERE id = ?", (recording_id,)
    ).fetchone()
    if row is None:
        raise KeyError(recording_id)
    current = RecordingStatus(str(row["status"]))
    if target not in ALLOWED_TRANSITIONS[current]:
        raise InvalidTransitionError(f"cannot transition {current} to {target}")
    timestamp = utc_now()
    connection.execute(
        """
        UPDATE recordings
        SET status = ?, last_error_code = ?, last_error_message = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            target.value,
            error_code if target is RecordingStatus.FAILED else None,
            error_message if target is RecordingStatus.FAILED else None,
            timestamp,
            recording_id,
        ),
    )


def _enqueue(
    connection: sqlite3.Connection,
    recording_id: str,
    kind: str,
    input_revision: int,
    settings_fingerprint: str,
) -> EnqueueResult:
    existing = connection.execute(
        """
        SELECT id FROM jobs
        WHERE recording_id = ? AND kind = ? AND input_revision = ?
          AND settings_fingerprint = ? AND status IN ('queued', 'running', 'succeeded')
        ORDER BY created_at LIMIT 1
        """,
        (recording_id, kind, input_revision, settings_fingerprint),
    ).fetchone()
    if existing is not None:
        return EnqueueResult(str(existing["id"]), False)
    job_id = str(uuid.uuid4())
    timestamp = utc_now()
    connection.execute(
        """
        INSERT INTO jobs(
            id, recording_id, kind, status, attempts, available_at, created_at, updated_at,
            input_revision, settings_fingerprint
        ) VALUES (?, ?, ?, 'queued', 0, ?, ?, ?, ?, ?)
        """,
        (
            job_id,
            recording_id,
            kind,
            timestamp,
            timestamp,
            timestamp,
            input_revision,
            settings_fingerprint,
        ),
    )
    return EnqueueResult(job_id, True)
