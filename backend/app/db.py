from __future__ import annotations

import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path

CURRENT_SCHEMA_VERSION = 6


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
    4: (
        "ALTER TABLE recordings ADD COLUMN document_sequence INTEGER",
        "ALTER TABLE recordings ADD COLUMN document_title TEXT",
        """
        UPDATE recordings
        SET document_sequence = (
            SELECT COUNT(*)
            FROM recordings AS earlier
            WHERE earlier.created_at < recordings.created_at
               OR (
                   earlier.created_at = recordings.created_at
                   AND earlier.id <= recordings.id
               )
        )
        """,
        """
        CREATE UNIQUE INDEX recordings_document_sequence_unique
        ON recordings(document_sequence)
        WHERE document_sequence IS NOT NULL
        """,
        """
        CREATE TABLE document_sequence_counter (
            singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
            last_value INTEGER NOT NULL CHECK (last_value >= 0)
        )
        """,
        """
        INSERT INTO document_sequence_counter(singleton, last_value)
        SELECT 1, COALESCE(MAX(document_sequence), 0) FROM recordings
        """,
    ),
    5: (
        """
        CREATE TABLE persons (
            id TEXT PRIMARY KEY,
            display_name TEXT NOT NULL CHECK (length(trim(display_name)) > 0),
            revision INTEGER NOT NULL DEFAULT 1 CHECK (revision > 0),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        """
        CREATE INDEX persons_display_name
        ON persons(display_name)
        """,
        """
        CREATE TABLE segments_v5 (
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
            person_id TEXT REFERENCES persons(id) ON DELETE SET NULL,
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
        INSERT INTO segments_v5(
            id, recording_id, start_ms, end_ms, text, local_speaker_id,
            assignment_status, overlapping_speaker_ids_json, person_id, speaker_name,
            speaker_source, speaker_score, revision
        )
        SELECT id, recording_id, start_ms, end_ms, text, local_speaker_id,
               assignment_status, overlapping_speaker_ids_json, NULL, speaker_name,
               speaker_source, speaker_score, revision
        FROM segments
        """,
        "DROP TABLE segments",
        "ALTER TABLE segments_v5 RENAME TO segments",
        """
        CREATE INDEX segments_recording_time
        ON segments(recording_id, start_ms, end_ms, id)
        """,
        """
        CREATE UNIQUE INDEX segments_embedding_source
        ON segments(id, recording_id, local_speaker_id)
        """,
        """
        CREATE TABLE recording_speakers (
            recording_id TEXT NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
            local_speaker_id TEXT NOT NULL CHECK (length(trim(local_speaker_id)) > 0),
            person_id TEXT REFERENCES persons(id) ON DELETE SET NULL,
            speaker_source TEXT NOT NULL DEFAULT 'unresolved' CHECK (
                speaker_source IN ('manual', 'auto', 'unresolved')
            ),
            speaker_score REAL CHECK (
                speaker_score IS NULL OR (speaker_score >= 0.0 AND speaker_score <= 1.0)
            ),
            revision INTEGER NOT NULL DEFAULT 1 CHECK (revision > 0),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (recording_id, local_speaker_id)
        )
        """,
        """
        CREATE INDEX recording_speakers_person
        ON recording_speakers(person_id, recording_id, local_speaker_id)
        """,
        """
        INSERT INTO recording_speakers(
            recording_id, local_speaker_id, speaker_source, revision, created_at, updated_at
        )
        SELECT discovered.recording_id, discovered.local_speaker_id, 'unresolved', 1,
               recordings.created_at, recordings.updated_at
        FROM (
            SELECT recording_id, local_speaker_id
            FROM segments
            WHERE local_speaker_id IS NOT NULL
            UNION
            SELECT segments.recording_id, json_each.value
            FROM segments
            JOIN json_each(
                CASE
                    WHEN json_valid(segments.overlapping_speaker_ids_json)
                    THEN segments.overlapping_speaker_ids_json
                    ELSE '[]'
                END
            )
            WHERE json_each.type = 'text'
              AND length(trim(json_each.value)) > 0
        ) AS discovered
        JOIN recordings ON recordings.id = discovered.recording_id
        """,
        """
        CREATE TABLE speaker_embeddings (
            id TEXT PRIMARY KEY,
            person_id TEXT NOT NULL REFERENCES persons(id) ON DELETE CASCADE,
            recording_id TEXT NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
            local_speaker_id TEXT NOT NULL,
            segment_id TEXT NOT NULL,
            model_fingerprint TEXT NOT NULL CHECK (length(trim(model_fingerprint)) > 0),
            vector_store TEXT NOT NULL CHECK (length(trim(vector_store)) > 0),
            collection_name TEXT NOT NULL CHECK (length(trim(collection_name)) > 0),
            vector_key TEXT NOT NULL UNIQUE CHECK (vector_key = id),
            status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'invalidated')),
            invalidated_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (recording_id, local_speaker_id)
                REFERENCES recording_speakers(recording_id, local_speaker_id)
                ON DELETE CASCADE,
            FOREIGN KEY (segment_id, recording_id, local_speaker_id)
                REFERENCES segments(id, recording_id, local_speaker_id)
                ON DELETE CASCADE,
            CHECK (
                (status = 'active' AND invalidated_at IS NULL)
                OR (status = 'invalidated' AND invalidated_at IS NOT NULL)
            )
        )
        """,
        """
        CREATE INDEX speaker_embeddings_person_status
        ON speaker_embeddings(person_id, status, created_at)
        """,
        """
        CREATE INDEX speaker_embeddings_source
        ON speaker_embeddings(recording_id, local_speaker_id, segment_id)
        """,
    ),
    6: (
        """
        ALTER TABLE recording_speakers ADD COLUMN clip_status TEXT NOT NULL DEFAULT 'pending'
        CHECK (clip_status IN ('pending', 'ready', 'insufficient', 'failed'))
        """,
        "ALTER TABLE recording_speakers ADD COLUMN clip_error_code TEXT",
        """
        CREATE TABLE speaker_clips (
            id TEXT PRIMARY KEY,
            recording_id TEXT NOT NULL,
            local_speaker_id TEXT NOT NULL,
            segment_id TEXT NOT NULL REFERENCES segments(id) ON DELETE CASCADE,
            artifact_id TEXT NOT NULL UNIQUE REFERENCES artifacts(id) ON DELETE CASCADE,
            revision INTEGER NOT NULL CHECK (revision > 0),
            clip_index INTEGER NOT NULL CHECK (clip_index >= 0 AND clip_index < 3),
            start_ms INTEGER NOT NULL CHECK (start_ms >= 0),
            end_ms INTEGER NOT NULL CHECK (end_ms > start_ms),
            silence_ratio REAL NOT NULL CHECK (silence_ratio >= 0.0 AND silence_ratio <= 1.0),
            created_at TEXT NOT NULL,
            FOREIGN KEY (recording_id, local_speaker_id)
                REFERENCES recording_speakers(recording_id, local_speaker_id)
                ON DELETE CASCADE,
            UNIQUE(recording_id, local_speaker_id, revision, clip_index)
        )
        """,
        """
        CREATE INDEX speaker_clips_speaker_revision
        ON speaker_clips(recording_id, local_speaker_id, revision, clip_index)
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
