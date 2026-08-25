from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

from app.db import connect
from app.ingest import ingest_file, sha256_file

FIXTURES = Path(__file__).parents[1] / "fixtures"


def test_sha256_reads_large_file_in_chunks(tmp_path: Path) -> None:
    payload = b"abc123" * 400_000
    target = tmp_path / "large.m4a"
    target.write_bytes(payload)

    assert sha256_file(target, chunk_size=4096) == hashlib.sha256(payload).hexdigest()


def test_same_content_with_different_names_is_registered_once(tmp_path: Path) -> None:
    first = tmp_path / "first.m4a"
    second = tmp_path / "두 번째.m4a"
    shutil.copyfile(FIXTURES / "complete.m4a", first)
    shutil.copyfile(FIXTURES / "complete.m4a", second)
    database_path = tmp_path / "app.db"

    first_result = ingest_file(database_path, first)
    second_result = ingest_file(database_path, second)

    assert first_result.created is True
    assert second_result.created is False
    assert first_result.recording_id == second_result.recording_id
    with connect(database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM recordings").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1
        row = connection.execute("SELECT original_name, source_path FROM recordings").fetchone()
    assert row["original_name"] == "first.m4a"
    assert Path(row["source_path"]).name == "두 번째.m4a"


def test_same_path_with_new_content_creates_new_recording(tmp_path: Path) -> None:
    source = tmp_path / "recording.m4a"
    database_path = tmp_path / "app.db"
    shutil.copyfile(FIXTURES / "complete.m4a", source)
    first = ingest_file(database_path, source)
    shutil.copyfile(FIXTURES / "speaker-review.m4a", source)

    second = ingest_file(database_path, source)

    assert first.recording_id != second.recording_id
    with connect(database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM recordings").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 2
