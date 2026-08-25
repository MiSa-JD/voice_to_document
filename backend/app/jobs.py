from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.db import connect, migrate_database, utc_now


@dataclass(frozen=True)
class Job:
    id: str
    recording_id: str
    kind: str
    attempts: int
    input_revision: int
    settings_fingerprint: str


def claim_next_job(database_path: Path, now: str | None = None) -> Job | None:
    migrate_database(database_path)
    timestamp = now or utc_now()
    with connect(database_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            """
            SELECT id, recording_id, kind, attempts, input_revision, settings_fingerprint
            FROM jobs
            WHERE status = 'queued' AND available_at <= ?
            ORDER BY available_at, created_at, id
            LIMIT 1
            """,
            (timestamp,),
        ).fetchone()
        if row is None:
            connection.commit()
            return None
        attempts = int(row["attempts"]) + 1
        connection.execute(
            """
            UPDATE jobs
            SET status = 'running', attempts = ?, locked_at = ?, updated_at = ?,
                error_code = NULL, error_message = NULL
            WHERE id = ? AND status = 'queued'
            """,
            (attempts, timestamp, timestamp, row["id"]),
        )
        connection.commit()
        return Job(
            id=str(row["id"]),
            recording_id=str(row["recording_id"]),
            kind=str(row["kind"]),
            attempts=attempts,
            input_revision=int(row["input_revision"]),
            settings_fingerprint=str(row["settings_fingerprint"]),
        )


def complete_job(database_path: Path, job_id: str) -> None:
    _finish_job(database_path, job_id, status="succeeded")


def fail_job(
    database_path: Path,
    job_id: str,
    error_code: str,
    error_message: str,
    retry_at: str | None = None,
) -> None:
    timestamp = utc_now()
    status = "queued" if retry_at is not None else "failed"
    available_at = retry_at or timestamp
    with connect(database_path) as connection:
        cursor = connection.execute(
            """
            UPDATE jobs
            SET status = ?, available_at = ?, locked_at = NULL,
                error_code = ?, error_message = ?, updated_at = ?
            WHERE id = ? AND status = 'running'
            """,
            (status, available_at, error_code, error_message, timestamp, job_id),
        )
        if cursor.rowcount != 1:
            raise ValueError("job is not running")


def release_job(database_path: Path, job_id: str) -> None:
    timestamp = utc_now()
    with connect(database_path) as connection:
        cursor = connection.execute(
            """
            UPDATE jobs
            SET status = 'queued', available_at = ?, locked_at = NULL, updated_at = ?
            WHERE id = ? AND status = 'running'
            """,
            (timestamp, timestamp, job_id),
        )
        if cursor.rowcount != 1:
            raise ValueError("job is not running")


def _finish_job(database_path: Path, job_id: str, status: str) -> None:
    timestamp = utc_now()
    with connect(database_path) as connection:
        cursor = connection.execute(
            """
            UPDATE jobs
            SET status = ?, locked_at = NULL, updated_at = ?
            WHERE id = ? AND status = 'running'
            """,
            (status, timestamp, job_id),
        )
        if cursor.rowcount != 1:
            raise ValueError("job is not running")
