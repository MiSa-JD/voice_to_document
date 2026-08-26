from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from app.db import connect, migrate_database
from app.repository import register_recording


def test_registration_creates_recording_and_job_together(tmp_path: Path) -> None:
    source = tmp_path / "새 녹음.m4a"
    source.write_bytes(b"audio")
    database_path = tmp_path / "app.db"

    result = register_recording(database_path, source, "a" * 64, 5, 1000)

    assert result.created is True
    assert result.job_id is not None
    with connect(database_path) as connection:
        recording = connection.execute("SELECT * FROM recordings").fetchone()
        job = connection.execute("SELECT * FROM jobs").fetchone()
    assert recording["id"] == result.recording_id
    assert recording["status"] == "DISCOVERED"
    assert recording["original_name"] == "새 녹음.m4a"
    assert job["recording_id"] == result.recording_id
    assert job["kind"] == "transcribe"
    assert job["status"] == "queued"


@pytest.mark.parametrize("iteration", range(10))
def test_same_hash_concurrently_creates_one_recording_and_job(
    tmp_path: Path, iteration: int
) -> None:
    first = tmp_path / "first.m4a"
    second = tmp_path / "second.m4a"
    first.write_bytes(b"same")
    second.write_bytes(b"same")
    database_path = tmp_path / f"app-{iteration}.db"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda path: register_recording(database_path, path, "b" * 64, 4, 1000),
                (first, second),
            )
        )

    assert {result.recording_id for result in results}.__len__() == 1
    assert sum(result.created for result in results) == 1
    with connect(database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM recordings").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1
        row = connection.execute("SELECT original_name, source_path FROM recordings").fetchone()
    assert row["original_name"] in {"first.m4a", "second.m4a"}
    assert Path(row["source_path"]).name in {"first.m4a", "second.m4a"}


def test_job_insert_failure_rolls_back_recording(tmp_path: Path) -> None:
    source = tmp_path / "source.m4a"
    source.write_bytes(b"audio")
    database_path = tmp_path / "app.db"
    migrate_database(database_path)
    with connect(database_path) as connection:
        connection.execute(
            """
            CREATE TRIGGER fail_job_insert
            BEFORE INSERT ON jobs BEGIN
                SELECT RAISE(ABORT, 'injected job failure');
            END
            """
        )

    with pytest.raises(Exception, match="injected job failure"):
        register_recording(database_path, source, "c" * 64, 5, 1000)

    with connect(database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM recordings").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0
