from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path

from app.db import connect, migrate_database, utc_now


@dataclass(frozen=True)
class RegistrationResult:
    recording_id: str
    job_id: str | None
    created: bool


def record_audit_event(
    database_path: Path,
    event_type: str,
    details: dict[str, object],
    recording_id: str | None = None,
) -> str:
    migrate_database(database_path)
    event_id = str(uuid.uuid4())
    with connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO audit_events(id, recording_id, event_type, details_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                event_id,
                recording_id,
                event_type,
                json.dumps(details, ensure_ascii=False, sort_keys=True),
                utc_now(),
            ),
        )
    return event_id


def register_recording(
    database_path: Path,
    source_path: Path,
    content_sha256: str,
    size_bytes: int,
    duration_ms: int,
    recorded_at: str | None = None,
) -> RegistrationResult:
    migrate_database(database_path)
    timestamp = utc_now()
    with connect(database_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        existing = connection.execute(
            "SELECT id FROM recordings WHERE content_sha256 = ?",
            (content_sha256,),
        ).fetchone()
        if existing is not None:
            connection.execute(
                "UPDATE recordings SET source_path = ?, updated_at = ? WHERE id = ?",
                (str(source_path.resolve()), timestamp, existing["id"]),
            )
            connection.commit()
            return RegistrationResult(
                recording_id=str(existing["id"]),
                job_id=None,
                created=False,
            )

        recording_id = str(uuid.uuid4())
        job_id = str(uuid.uuid4())
        try:
            connection.execute(
                """
                INSERT INTO recordings(
                    id, content_sha256, source_path, original_name, size_bytes, duration_ms,
                    recorded_at, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'DISCOVERED', ?, ?)
                """,
                (
                    recording_id,
                    content_sha256,
                    str(source_path.resolve()),
                    source_path.name,
                    size_bytes,
                    duration_ms,
                    recorded_at,
                    timestamp,
                    timestamp,
                ),
            )
            connection.execute(
                """
                INSERT INTO jobs(
                    id, recording_id, kind, status, attempts, available_at, created_at, updated_at,
                    input_revision, settings_fingerprint
                ) VALUES (?, ?, 'transcribe', 'queued', 0, ?, ?, ?, 1, 'input-v1')
                """,
                (job_id, recording_id, timestamp, timestamp, timestamp),
            )
            connection.commit()
        except sqlite3.Error:
            connection.rollback()
            raise
        return RegistrationResult(recording_id=recording_id, job_id=job_id, created=True)
