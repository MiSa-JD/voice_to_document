from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from app.db import CURRENT_SCHEMA_VERSION, MIGRATIONS, FutureSchemaError, connect, migrate_database


def test_empty_database_migrates_to_current_schema(tmp_path: Path) -> None:
    database_path = tmp_path / "app.db"

    assert migrate_database(database_path) == CURRENT_SCHEMA_VERSION

    with connect(database_path) as connection:
        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        version = connection.execute(
            "SELECT MAX(version) AS version FROM schema_migrations"
        ).fetchone()["version"]
        foreign_keys = connection.execute("PRAGMA foreign_keys").fetchone()[0]
    assert {
        "recordings",
        "jobs",
        "artifacts",
        "audit_events",
        "segments",
        "persons",
        "recording_speakers",
        "speaker_embeddings",
        "speaker_clips",
        "speaker_vector_keys",
        "speaker_vectors",
        "speaker_profiles",
        "speaker_profile_members",
    } <= tables
    assert version == CURRENT_SCHEMA_VERSION
    assert foreign_keys == 1


def test_migration_is_safe_to_run_twice(tmp_path: Path) -> None:
    database_path = tmp_path / "app.db"

    migrate_database(database_path)
    migrate_database(database_path)

    with connect(database_path) as connection:
        count = connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
    assert count == CURRENT_SCHEMA_VERSION


def test_future_schema_is_not_overwritten(tmp_path: Path) -> None:
    database_path = tmp_path / "future.db"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
            (CURRENT_SCHEMA_VERSION + 1, "2026-01-01T00:00:00+00:00"),
        )

    with pytest.raises(FutureSchemaError, match="newer than supported"):
        migrate_database(database_path)


def test_constraints_reject_invalid_recording(tmp_path: Path) -> None:
    database_path = tmp_path / "app.db"
    migrate_database(database_path)

    with connect(database_path) as connection, pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """
            INSERT INTO recordings(
                id, content_sha256, source_path, original_name, size_bytes, duration_ms,
                status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("id", "hash", "/source", "source.m4a", 0, 1, "DISCOVERED", "now", "now"),
        )


def test_version_one_database_upgrades_to_current_version(tmp_path: Path) -> None:
    database_path = tmp_path / "app.db"
    with connect(database_path) as connection:
        connection.execute(
            "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        for statement in MIGRATIONS[1]:
            connection.execute(statement)
        connection.execute("INSERT INTO schema_migrations(version, applied_at) VALUES (1, 'now')")

    assert migrate_database(database_path) == CURRENT_SCHEMA_VERSION

    with connect(database_path) as connection:
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(jobs)").fetchall()}
        segment_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(segments)").fetchall()
        }
    assert {"input_revision", "settings_fingerprint"} <= columns
    assert {"assignment_status", "overlapping_speaker_ids_json"} <= segment_columns


def test_speaker_clip_schema_defaults_existing_speakers_to_pending(tmp_path: Path) -> None:
    database_path = tmp_path / "app.db"
    with connect(database_path) as connection:
        connection.execute(
            "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        for version in range(1, 6):
            for statement in MIGRATIONS[version]:
                connection.execute(statement)
            connection.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (?, 'now')", (version,)
            )
        _insert_recording(connection)
        connection.execute(
            """
            INSERT INTO recording_speakers(
                recording_id, local_speaker_id, speaker_source, revision, created_at, updated_at
            ) VALUES ('recording', 'SPEAKER_00', 'unresolved', 1, 'now', 'now')
            """
        )

    migrate_database(database_path)

    with connect(database_path) as connection:
        speaker = connection.execute(
            "SELECT clip_status, clip_error_code FROM recording_speakers"
        ).fetchone()
    assert dict(speaker) == {"clip_status": "pending", "clip_error_code": None}


def test_version_two_segments_are_preserved_as_assigned(tmp_path: Path) -> None:
    database_path = tmp_path / "app.db"
    with connect(database_path) as connection:
        connection.execute(
            "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        for version in (1, 2):
            for statement in MIGRATIONS[version]:
                connection.execute(statement)
            connection.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (?, 'now')", (version,)
            )
        connection.execute(
            """
            INSERT INTO recordings(
                id, content_sha256, source_path, original_name, size_bytes, duration_ms,
                status, created_at, updated_at
            ) VALUES ('recording', ?, '/source', 'source.m4a', 1, 1000, 'DISCOVERED', 'now', 'now')
            """,
            ("a" * 64,),
        )
        connection.execute(
            """
            INSERT INTO segments(
                id, recording_id, start_ms, end_ms, text, local_speaker_id, revision
            ) VALUES ('segment', 'recording', 0, 900, '테스트', 'SPEAKER_00', 1)
            """
        )

    assert migrate_database(database_path) == CURRENT_SCHEMA_VERSION

    with connect(database_path) as connection:
        row = connection.execute(
            """
            SELECT local_speaker_id, assignment_status, overlapping_speaker_ids_json
            FROM segments
            """
        ).fetchone()
    assert dict(row) == {
        "local_speaker_id": "SPEAKER_00",
        "assignment_status": "assigned",
        "overlapping_speaker_ids_json": "[]",
    }


def test_version_three_recordings_receive_stable_ordered_sequences(tmp_path: Path) -> None:
    database_path = tmp_path / "app.db"
    with connect(database_path) as connection:
        connection.execute(
            "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        for version in (1, 2, 3):
            for statement in MIGRATIONS[version]:
                connection.execute(statement)
            connection.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (?, 'now')", (version,)
            )
        for recording_id, created_at in (
            ("b", "2026-01-02"),
            ("c", "2026-01-01"),
            ("a", "2026-01-02"),
        ):
            connection.execute(
                """
                INSERT INTO recordings(
                    id, content_sha256, source_path, original_name, size_bytes, duration_ms,
                    status, created_at, updated_at
                ) VALUES (?, ?, '/source', 'source.m4a', 1, 1000, 'COMPLETED', ?, 'now')
                """,
                (recording_id, recording_id * 64, created_at),
            )

    migrate_database(database_path)

    with connect(database_path) as connection:
        rows = connection.execute(
            """
            SELECT id, document_sequence, document_title
            FROM recordings ORDER BY document_sequence
            """
        ).fetchall()
        counter = connection.execute(
            "SELECT last_value FROM document_sequence_counter WHERE singleton = 1"
        ).fetchone()[0]
    assert [dict(row) for row in rows] == [
        {"id": "c", "document_sequence": 1, "document_title": None},
        {"id": "a", "document_sequence": 2, "document_title": None},
        {"id": "b", "document_sequence": 3, "document_title": None},
    ]
    assert counter == 3


def _create_version_four_database(database_path: Path) -> None:
    with connect(database_path) as connection:
        connection.execute(
            "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        for version in range(1, 5):
            for statement in MIGRATIONS[version]:
                connection.execute(statement)
            connection.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (?, 'now')", (version,)
            )


def _insert_recording(connection: sqlite3.Connection, recording_id: str = "recording") -> None:
    connection.execute(
        """
        INSERT INTO recordings(
            id, content_sha256, source_path, original_name, size_bytes, duration_ms,
            status, created_at, updated_at
        ) VALUES (?, ?, '/source', 'source.m4a', 1, 1000, 'COMPLETED', 'created', 'updated')
        """,
        (recording_id, recording_id[0] * 64),
    )


def test_version_four_data_is_preserved_and_speakers_are_backfilled_once(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "app.db"
    _create_version_four_database(database_path)
    with connect(database_path) as connection:
        _insert_recording(connection)
        connection.executemany(
            """
            INSERT INTO segments(
                id, recording_id, start_ms, end_ms, text, local_speaker_id,
                assignment_status, overlapping_speaker_ids_json, person_id,
                speaker_name, speaker_source, speaker_score, revision
            ) VALUES (?, 'recording', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "segment-1",
                    0,
                    400,
                    "first",
                    "SPEAKER_00",
                    "overlap",
                    '["SPEAKER_00", "SPEAKER_01"]',
                    "legacy-person-without-source-of-truth",
                    "legacy name",
                    "auto",
                    0.9,
                    2,
                ),
                (
                    "segment-2",
                    400,
                    900,
                    "second",
                    "SPEAKER_00",
                    "assigned",
                    "[]",
                    None,
                    None,
                    "unresolved",
                    None,
                    1,
                ),
            ],
        )

    assert migrate_database(database_path) == CURRENT_SCHEMA_VERSION
    assert migrate_database(database_path) == CURRENT_SCHEMA_VERSION

    with connect(database_path) as connection:
        recording_count = connection.execute("SELECT COUNT(*) FROM recordings").fetchone()[0]
        segments = connection.execute(
            """
            SELECT id, text, person_id, speaker_name, speaker_source, speaker_score, revision
            FROM segments ORDER BY id
            """
        ).fetchall()
        speakers = connection.execute(
            """
            SELECT local_speaker_id, person_id, speaker_source, speaker_score, revision,
                   created_at, updated_at
            FROM recording_speakers ORDER BY local_speaker_id
            """
        ).fetchall()

    assert recording_count == 1
    assert [dict(row) for row in segments] == [
        {
            "id": "segment-1",
            "text": "first",
            "person_id": None,
            "speaker_name": "legacy name",
            "speaker_source": "auto",
            "speaker_score": 0.9,
            "revision": 2,
        },
        {
            "id": "segment-2",
            "text": "second",
            "person_id": None,
            "speaker_name": None,
            "speaker_source": "unresolved",
            "speaker_score": None,
            "revision": 1,
        },
    ]
    assert [dict(row) for row in speakers] == [
        {
            "local_speaker_id": "SPEAKER_00",
            "person_id": None,
            "speaker_source": "unresolved",
            "speaker_score": None,
            "revision": 1,
            "created_at": "created",
            "updated_at": "updated",
        },
        {
            "local_speaker_id": "SPEAKER_01",
            "person_id": None,
            "speaker_source": "unresolved",
            "speaker_score": None,
            "revision": 1,
            "created_at": "created",
            "updated_at": "updated",
        },
    ]


def test_person_names_may_repeat_and_segment_person_is_set_null_on_delete(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "app.db"
    migrate_database(database_path)
    with connect(database_path) as connection:
        _insert_recording(connection)
        connection.executemany(
            """
            INSERT INTO persons(id, display_name, revision, created_at, updated_at)
            VALUES (?, 'Same name', 1, 'now', 'now')
            """,
            [("person-1",), ("person-2",)],
        )
        connection.execute(
            """
            INSERT INTO segments(
                id, recording_id, start_ms, end_ms, text, local_speaker_id,
                person_id, speaker_source, revision
            ) VALUES ('segment', 'recording', 0, 500, 'text', 'SPEAKER_00',
                      'person-1', 'manual', 1)
            """
        )
        connection.execute("DELETE FROM persons WHERE id = 'person-1'")
        person_id = connection.execute(
            "SELECT person_id FROM segments WHERE id = 'segment'"
        ).fetchone()[0]
    assert person_id is None


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("speaker_source", "guessed"),
        ("speaker_score", -0.1),
        ("speaker_score", 1.1),
        ("revision", 0),
    ],
)
def test_recording_speaker_rejects_invalid_values(
    tmp_path: Path, column: str, value: object
) -> None:
    database_path = tmp_path / "app.db"
    migrate_database(database_path)
    with connect(database_path) as connection:
        _insert_recording(connection)
        values: dict[str, object] = {
            "speaker_source": "unresolved",
            "speaker_score": None,
            "revision": 1,
        }
        values[column] = value
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO recording_speakers(
                    recording_id, local_speaker_id, speaker_source, speaker_score,
                    revision, created_at, updated_at
                ) VALUES ('recording', 'SPEAKER_00', ?, ?, ?, 'now', 'now')
                """,
                (values["speaker_source"], values["speaker_score"], values["revision"]),
            )


def test_recording_speaker_rejects_duplicates_and_unknown_foreign_keys(tmp_path: Path) -> None:
    database_path = tmp_path / "app.db"
    migrate_database(database_path)
    with connect(database_path) as connection:
        _insert_recording(connection)
        connection.execute(
            """
            INSERT INTO recording_speakers(
                recording_id, local_speaker_id, revision, created_at, updated_at
            ) VALUES ('recording', 'SPEAKER_00', 1, 'now', 'now')
            """
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO recording_speakers(
                    recording_id, local_speaker_id, revision, created_at, updated_at
                ) VALUES ('recording', 'SPEAKER_00', 1, 'now', 'now')
                """
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO recording_speakers(
                    recording_id, local_speaker_id, revision, created_at, updated_at
                ) VALUES ('missing', 'SPEAKER_00', 1, 'now', 'now')
                """
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                UPDATE recording_speakers SET person_id = 'missing'
                WHERE recording_id = 'recording' AND local_speaker_id = 'SPEAKER_00'
                """
            )


def _insert_embedding_sources(connection: sqlite3.Connection) -> None:
    _insert_recording(connection)
    connection.execute(
        """
        INSERT INTO persons(id, display_name, revision, created_at, updated_at)
        VALUES ('person', 'Person', 1, 'now', 'now')
        """
    )
    connection.execute(
        """
        INSERT INTO recording_speakers(
            recording_id, local_speaker_id, person_id, speaker_source, revision,
            created_at, updated_at
        ) VALUES ('recording', 'SPEAKER_00', 'person', 'manual', 1, 'now', 'now')
        """
    )
    connection.execute(
        """
        INSERT INTO segments(
            id, recording_id, start_ms, end_ms, text, local_speaker_id,
            person_id, speaker_source, revision
        ) VALUES ('segment', 'recording', 100, 500, 'text', 'SPEAKER_00',
                  'person', 'manual', 1)
        """
    )


def _insert_embedding(
    connection: sqlite3.Connection,
    *,
    embedding_id: str = "embedding",
    vector_key: str = "embedding",
    person_id: str = "person",
    recording_id: str = "recording",
    local_speaker_id: str = "SPEAKER_00",
    segment_id: str = "segment",
    status: str = "active",
    invalidated_at: str | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO speaker_embeddings(
            id, person_id, recording_id, local_speaker_id, segment_id,
            model_fingerprint, vector_store, collection_name, vector_key,
            status, invalidated_at, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, 'model:v1', 'vdb', 'speakers', ?, ?, ?, 'now', 'now')
        """,
        (
            embedding_id,
            person_id,
            recording_id,
            local_speaker_id,
            segment_id,
            vector_key,
            status,
            invalidated_at,
        ),
    )


def test_embedding_metadata_enforces_sources_vector_identity_and_invalidation(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "app.db"
    migrate_database(database_path)
    with connect(database_path) as connection:
        _insert_embedding_sources(connection)
        _insert_embedding(connection)

        for changes in (
            {"embedding_id": "other", "vector_key": "embedding"},
            {"embedding_id": "other", "vector_key": "different"},
            {"embedding_id": "other", "vector_key": "other", "person_id": "missing"},
            {"embedding_id": "other", "vector_key": "other", "segment_id": "missing"},
            {
                "embedding_id": "other",
                "vector_key": "other",
                "local_speaker_id": "SPEAKER_01",
            },
            {"embedding_id": "other", "vector_key": "other", "status": "invalidated"},
            {
                "embedding_id": "other",
                "vector_key": "other",
                "status": "active",
                "invalidated_at": "now",
            },
        ):
            with pytest.raises(sqlite3.IntegrityError):
                _insert_embedding(connection, **changes)

        _insert_embedding(
            connection,
            embedding_id="invalidated",
            vector_key="invalidated",
            status="invalidated",
            invalidated_at="now",
        )


def test_speaker_schema_has_required_foreign_keys_and_indexes(tmp_path: Path) -> None:
    database_path = tmp_path / "app.db"
    migrate_database(database_path)
    with connect(database_path) as connection:
        segment_foreign_keys = connection.execute("PRAGMA foreign_key_list(segments)").fetchall()
        indexes = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            ).fetchall()
        }
    assert any(
        row["table"] == "persons" and row["from"] == "person_id" and row["on_delete"] == "SET NULL"
        for row in segment_foreign_keys
    )
    assert {
        "persons_display_name",
        "recording_speakers_person",
        "segments_embedding_source",
        "speaker_embeddings_person_status",
        "speaker_embeddings_source",
    } <= indexes
