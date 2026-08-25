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
    assert {"recordings", "jobs", "artifacts", "audit_events", "segments"} <= tables
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


def test_version_one_database_upgrades_to_version_two(tmp_path: Path) -> None:
    database_path = tmp_path / "app.db"
    with connect(database_path) as connection:
        connection.execute(
            "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        for statement in MIGRATIONS[1]:
            connection.execute(statement)
        connection.execute("INSERT INTO schema_migrations(version, applied_at) VALUES (1, 'now')")

    assert migrate_database(database_path) == 2

    with connect(database_path) as connection:
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(jobs)").fetchall()}
    assert {"input_revision", "settings_fingerprint"} <= columns
