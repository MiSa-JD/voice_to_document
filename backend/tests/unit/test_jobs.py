from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.db import connect
from app.jobs import claim_next_job, complete_job, fail_job, release_job
from app.repository import register_recording


def _queued_job(tmp_path: Path) -> tuple[Path, str]:
    source = tmp_path / "source.m4a"
    source.write_bytes(b"audio")
    database_path = tmp_path / "app.db"
    result = register_recording(database_path, source, "d" * 64, 5, 1000)
    assert result.job_id is not None
    return database_path, result.job_id


def test_two_workers_cannot_claim_same_job(tmp_path: Path) -> None:
    database_path, job_id = _queued_job(tmp_path)

    with ThreadPoolExecutor(max_workers=2) as executor:
        claimed = list(executor.map(lambda _: claim_next_job(database_path), range(2)))

    jobs = [job for job in claimed if job is not None]
    assert len(jobs) == 1
    assert jobs[0].id == job_id
    assert jobs[0].attempts == 1


def test_complete_job_preserves_attempt_count(tmp_path: Path) -> None:
    database_path, job_id = _queued_job(tmp_path)
    assert claim_next_job(database_path) is not None

    complete_job(database_path, job_id)

    with connect(database_path) as connection:
        row = connection.execute("SELECT status, attempts, locked_at FROM jobs").fetchone()
    assert dict(row) == {"status": "succeeded", "attempts": 1, "locked_at": None}


def test_failure_can_be_retried_without_erasing_history(tmp_path: Path) -> None:
    database_path, job_id = _queued_job(tmp_path)
    assert claim_next_job(database_path) is not None
    fail_job(
        database_path,
        job_id,
        "TEMPORARY_IO",
        "temporary input error",
        retry_at="2000-01-01T00:00:00+00:00",
    )

    retried = claim_next_job(database_path)

    assert retried is not None
    assert retried.attempts == 2


def test_release_returns_running_job_to_queue(tmp_path: Path) -> None:
    database_path, job_id = _queued_job(tmp_path)
    assert claim_next_job(database_path) is not None

    release_job(database_path, job_id)

    with connect(database_path) as connection:
        row = connection.execute("SELECT status, attempts, locked_at FROM jobs").fetchone()
    assert dict(row) == {"status": "queued", "attempts": 1, "locked_at": None}
