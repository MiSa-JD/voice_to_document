from __future__ import annotations

import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path

CURRENT_SCHEMA_VERSION = 3


class FutureSchemaError(RuntimeError):
    pass


MIGRATIONS: dict[int, tuple[str, ...]] = {
    1: (
        """
        CREATE TABLE recordings (
            id TEXT PRIMARY KEY,
            content_sha256 TEXT NOT NULL UNIQUE,
            source_path TEXT NOT NULL,
            original_name TEXT NOT NULL,
            size_bytes INTEGER NOT NULL CHECK (size_bytes > 0),
            duration_ms INTEGER NOT NULL CHECK (duration_ms > 0),
            recorded_at TEXT,
            status TEXT NOT NULL CHECK (status IN (
                'DISCOVERED', 'TRANSCRIBING', 'SPEAKER_REVIEW', 'CLASSIFYING',
                'READY_FOR_SUMMARY', 'SUMMARIZING', 'COMPLETED', 'FAILED'
            )),
            category TEXT,
            category_confidence REAL,
            needs_speaker_review INTEGER NOT NULL DEFAULT 0 CHECK (needs_speaker_review IN (0, 1)),
            revision INTEGER NOT NULL DEFAULT 1 CHECK (revision > 0),
            last_error_code TEXT,
            last_error_message TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE jobs (
            id TEXT PRIMARY KEY,
            recording_id TEXT NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
            kind TEXT NOT NULL CHECK (kind IN (
                'transcribe', 'finalize_speakers', 'classify', 'summarize', 'render'
            )),
            status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'succeeded', 'failed')),
            attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
            available_at TEXT NOT NULL,
            locked_at TEXT,
            error_code TEXT,
            error_message TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        """
        CREATE UNIQUE INDEX jobs_one_active_kind
        ON jobs(recording_id, kind)
        WHERE status IN ('queued', 'running')
        """,
        """
        CREATE INDEX jobs_claim_order
        ON jobs(status, available_at, created_at)
        """,
        """
        CREATE TABLE artifacts (
            id TEXT PRIMARY KEY,
            recording_id TEXT NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
            kind TEXT NOT NULL,
            relative_path TEXT NOT NULL,
            content_sha256 TEXT NOT NULL,
            schema_version INTEGER NOT NULL CHECK (schema_version > 0),
            revision INTEGER NOT NULL CHECK (revision > 0),
            created_at TEXT NOT NULL,
            UNIQUE(recording_id, kind, revision)
        )
        """,
        """
        CREATE TABLE audit_events (
            id TEXT PRIMARY KEY,
            recording_id TEXT REFERENCES recordings(id) ON DELETE SET NULL,
            event_type TEXT NOT NULL,
            details_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """,
    ),
    2: (
        "ALTER TABLE recordings ADD COLUMN category_reason TEXT",
        (
            "ALTER TABLE jobs ADD COLUMN input_revision INTEGER NOT NULL "
            "DEFAULT 1 CHECK (input_revision > 0)"
        ),
        "ALTER TABLE jobs ADD COLUMN settings_fingerprint TEXT NOT NULL DEFAULT 'legacy'",
        """
        CREATE UNIQUE INDEX jobs_one_successful_input
        ON jobs(recording_id, kind, input_revision, settings_fingerprint)
        WHERE status = 'succeeded'
        """,
        """
        CREATE TABLE segments (
            id TEXT PRIMARY KEY,
            recording_id TEXT NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
            start_ms INTEGER NOT NULL CHECK (start_ms >= 0),
            end_ms INTEGER NOT NULL CHECK (end_ms > start_ms),
            text TEXT NOT NULL CHECK (length(trim(text)) > 0),
            local_speaker_id TEXT NOT NULL,
            person_id TEXT,
            speaker_name TEXT,
            speaker_source TEXT NOT NULL DEFAULT 'unresolved' CHECK (
                speaker_source IN ('manual', 'auto', 'unresolved')
            ),
            speaker_score REAL,
            revision INTEGER NOT NULL CHECK (revision > 0)
        )
        """,
        """
        CREATE INDEX segments_recording_time
        ON segments(recording_id, start_ms, end_ms, id)
        """,
    ),
    3: (
        "ALTER TABLE segments RENAME TO segments_v2",
        """
        CREATE TABLE segments (
            id TEXT PRIMARY KEY,
            recording_id TEXT NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
            start_ms INTEGER NOT NULL CHECK (start_ms >= 0),
            end_ms INTEGER NOT NULL CHECK (end_ms > start_ms),
            text TEXT NOT NULL CHECK (length(trim(text)) > 0),
            local_speaker_id TEXT,
            assignment_status TEXT NOT NULL DEFAULT 'assigned' CHECK (
                assignment_status IN ('assigned', 'overlap', 'unassigned')
            ),
            overlapping_speaker_ids_json TEXT NOT NULL DEFAULT '[]',
            person_id TEXT,
            speaker_name TEXT,
            speaker_source TEXT NOT NULL DEFAULT 'unresolved' CHECK (
                speaker_source IN ('manual', 'auto', 'unresolved')
            ),
            speaker_score REAL,
            revision INTEGER NOT NULL CHECK (revision > 0),
            CHECK (
                (assignment_status = 'unassigned' AND local_speaker_id IS NULL)
                OR (assignment_status != 'unassigned' AND local_speaker_id IS NOT NULL)
            )
        )
        """,
        """
        INSERT INTO segments(
            id, recording_id, start_ms, end_ms, text, local_speaker_id,
            assignment_status, overlapping_speaker_ids_json, person_id, speaker_name,
            speaker_source, speaker_score, revision
        )
        SELECT id, recording_id, start_ms, end_ms, text, local_speaker_id,
               'assigned', '[]', person_id, speaker_name, speaker_source, speaker_score, revision
        FROM segments_v2
        """,
        "DROP TABLE segments_v2",
        """
        CREATE INDEX segments_recording_time
        ON segments(recording_id, start_ms, end_ms, id)
        """,
    ),
}


def connect(database_path: Path) -> sqlite3.Connection:
    for attempt in range(6):
        connection = sqlite3.connect(database_path, timeout=5)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA busy_timeout = 5000")
            journal_mode = str(connection.execute("PRAGMA journal_mode").fetchone()[0])
            if journal_mode.casefold() != "wal":
                connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = NORMAL")
            return connection
        except sqlite3.OperationalError as error:
            connection.close()
            if attempt == 5 or not _is_database_busy(error):
                raise
            time.sleep(0.01 * (2**attempt))
    raise AssertionError("SQLite connection retry loop did not return")


def _is_database_busy(error: sqlite3.OperationalError) -> bool:
    message = str(error).casefold()
    return "locked" in message or "busy" in message


def check_database(database_path: Path) -> None:
    with connect(database_path) as connection:
        connection.execute("SELECT 1").fetchone()


def migrate_database(database_path: Path) -> int:
    with connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            )
            """
        )
        connection.commit()
        connection.execute("BEGIN IMMEDIATE")
        try:
            row = connection.execute(
                "SELECT MAX(version) AS version FROM schema_migrations"
            ).fetchone()
            current = int(row["version"] or 0)
            if current > CURRENT_SCHEMA_VERSION:
                raise FutureSchemaError(
                    f"database schema {current} is newer than supported {CURRENT_SCHEMA_VERSION}"
                )

            for version in range(current + 1, CURRENT_SCHEMA_VERSION + 1):
                statements = MIGRATIONS[version]
                for statement in statements:
                    connection.execute(statement)
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (version, utc_now()),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        return CURRENT_SCHEMA_VERSION


def utc_now() -> str:
    return datetime.now(UTC).isoformat()
