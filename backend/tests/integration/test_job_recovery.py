from __future__ import annotations

import logging
import multiprocessing
import shutil
from pathlib import Path
from typing import Any

import pytest
from app.config import Settings
from app.db import connect
from app.ingest import ingest_file
from app.jobs import Job, claim_next_job, complete_job
from app.pipeline import FakePipelineHandler
from app.recovery import RecoveryError, recover_stale_jobs, worker_lock
from app.runtime import process_one_job

LOGGER = logging.getLogger("test")


def prepare(values: dict[str, Any]) -> tuple[Settings, FakePipelineHandler, Job]:
    settings = Settings(**values)
    source = settings.recording_input_dir / "complete.m4a"
    shutil.copyfile(Path(__file__).parents[1] / "fixtures/complete.m4a", source)
    ingest_file(settings.database_path, source)
    job = claim_next_job(settings.database_path)
    assert job is not None
    return settings, FakePipelineHandler(settings, LOGGER), job


def test_lock_excludes_second_owner_and_releases(tmp_path: Path) -> None:
    database = tmp_path / "app.db"
    with (
        worker_lock(database),
        pytest.raises(RecoveryError, match="WORKER_ALREADY_RUNNING"),
        worker_lock(database),
    ):
        pytest.fail("second worker acquired lock")
    with worker_lock(database):
        pass


def hold_lock(database: Path, ready: Any) -> None:
    with worker_lock(database):
        ready.set()
        multiprocessing.Event().wait(30)


def test_sigkill_releases_process_lock_and_job_is_recovered(
    settings_values: dict[str, Any],
) -> None:
    settings, handler, job = prepare(settings_values)
    ctx = multiprocessing.get_context("spawn")
    ready = ctx.Event()
    process = ctx.Process(target=hold_lock, args=(settings.database_path, ready))
    process.start()
    try:
        assert ready.wait(10)
        with pytest.raises(RecoveryError), worker_lock(settings.database_path):
            pass
        process.kill()
        process.join(10)
        assert not process.is_alive()
        with worker_lock(settings.database_path):
            recover_stale_jobs(handler, LOGGER)
            recovered = claim_next_job(settings.database_path)
            assert recovered is not None
            assert recovered.id == job.id and recovered.attempts == 2
            handler(recovered)
            complete_job(settings.database_path, recovered.id)
    finally:
        if process.is_alive():
            process.kill()
            process.join(10)


def test_transcript_checkpoint_resumes_without_transcription(
    settings_values: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    settings, handler, job = prepare(settings_values)

    def crash(*args: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(handler, "_generate_speaker_clips", crash)
    with pytest.raises(KeyboardInterrupt):
        handler(job)
    recover_stale_jobs(handler, LOGGER)
    replacement = FakePipelineHandler(settings, LOGGER)
    monkeypatch.setattr(replacement.adapters, "transcribe", crash)
    assert process_one_job(settings.database_path, replacement, LOGGER)
    with connect(settings.database_path) as connection:
        recovered = connection.execute("SELECT * FROM jobs WHERE id = ?", (job.id,)).fetchone()
        assert recovered["status"] == "succeeded" and recovered["attempts"] == 2
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM jobs WHERE kind = 'finalize_speakers'"
            ).fetchone()[0]
            == 1
        )


def test_completed_transcription_restores_without_extra_attempt(
    settings_values: dict[str, Any],
) -> None:
    settings, handler, job = prepare(settings_values)
    handler(job)
    with connect(settings.database_path) as connection:
        connection.execute("UPDATE jobs SET attempts = 3 WHERE id = ?", (job.id,))
    recover_stale_jobs(handler, LOGGER)
    recover_stale_jobs(handler, LOGGER)
    with connect(settings.database_path) as connection:
        row = connection.execute(
            "SELECT status, attempts FROM jobs WHERE id = ?", (job.id,)
        ).fetchone()
        assert tuple(row) == ("succeeded", 3)
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM audit_events WHERE event_type = 'job_recovered'"
            ).fetchone()[0]
            == 1
        )


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ("UPDATE recordings SET revision = 2, status = 'COMPLETED'", "RECOVERY_REVISION_CHANGED"),
        ("UPDATE jobs SET attempts = 3", "RECOVERY_ATTEMPTS_EXHAUSTED"),
        ("UPDATE jobs SET settings_fingerprint = 'different'", "RECOVERY_SETTINGS_CHANGED"),
    ],
)
def test_unsafe_recovery_fails(settings_values: dict[str, Any], change: str, code: str) -> None:
    settings, handler, job = prepare(settings_values)
    with connect(settings.database_path) as connection:
        connection.execute(change)
    recover_stale_jobs(handler, LOGGER)
    with connect(settings.database_path) as connection:
        row = connection.execute("SELECT * FROM jobs WHERE id = ?", (job.id,)).fetchone()
        assert row["status"] == "failed" and row["error_code"] == code
        if code == "RECOVERY_REVISION_CHANGED":
            assert connection.execute("SELECT status FROM recordings").fetchone()[0] == "COMPLETED"


@pytest.mark.parametrize("missing", [False, True])
def test_source_hash_or_missing_input_rejected(
    settings_values: dict[str, Any], missing: bool
) -> None:
    settings, handler, _ = prepare(settings_values)
    source = settings.recording_input_dir / "complete.m4a"
    if missing:
        source.unlink()
    else:
        source.write_bytes(b"changed")
    recover_stale_jobs(handler, LOGGER)
    with connect(settings.database_path) as connection:
        assert connection.execute("SELECT status FROM jobs").fetchone()[0] == "failed"


@pytest.mark.parametrize("kind", ["classify", "summarize"])
def test_completed_document_reused_without_provider(
    settings_values: dict[str, Any], kind: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings, handler, job = prepare(settings_values)
    while job.kind != kind:
        handler(job)
        complete_job(settings.database_path, job.id)
        next_job = claim_next_job(settings.database_path)
        assert next_job is not None
        job = next_job
    handler(job)
    with connect(settings.database_path) as connection:
        connection.execute("UPDATE jobs SET attempts = 3 WHERE id = ?", (job.id,))

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("provider should not be called")

    monkeypatch.setattr(handler.summary_adapter, "summarize", forbidden)
    monkeypatch.setattr(handler.classification_adapter, "classify", forbidden)
    recover_stale_jobs(handler, LOGGER)
    with connect(settings.database_path) as connection:
        assert (
            connection.execute("SELECT status FROM jobs WHERE id = ?", (job.id,)).fetchone()[0]
            == "succeeded"
        )
        assert (
            connection.execute("SELECT COUNT(*) FROM jobs WHERE kind = 'summarize'").fetchone()[0]
            == 1
        )


def test_registered_artifact_hash_mismatch_not_reused(settings_values: dict[str, Any]) -> None:
    settings, handler, job = prepare(settings_values)
    handler(job)
    with connect(settings.database_path) as connection:
        connection.execute(
            "UPDATE artifacts SET content_sha256 = 'invalid' WHERE kind = 'transcript_json'"
        )
    recover_stale_jobs(handler, LOGGER)
    with connect(settings.database_path) as connection:
        assert (
            connection.execute("SELECT error_code FROM jobs WHERE id = ?", (job.id,)).fetchone()[0]
            == "RECOVERY_INPUT_INVALID"
        )


def test_committed_retranscription_resumes_target_without_overwrite(
    settings_values: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api import create_app
    from fastapi.testclient import TestClient

    settings, handler, job = prepare(settings_values)
    handler(job)
    complete_job(settings.database_path, job.id)
    while process_one_job(settings.database_path, handler, LOGGER):
        pass
    client = TestClient(create_app(settings))
    accepted = client.post(
        f"/api/recordings/{job.recording_id}/retranscriptions",
        json={
            "expected_revision": 1,
            "language": "en",
            "content_description": "test hint",
            "terms": [],
            "confirm_impact": True,
        },
    )
    assert accepted.status_code == 202
    rerun = claim_next_job(settings.database_path)
    assert rerun is not None and rerun.kind == "transcribe"

    def crash(*args: object, **kwargs: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(handler, "_generate_speaker_clips", crash)
    with pytest.raises(KeyboardInterrupt):
        handler(rerun)
    with connect(settings.database_path) as connection:
        connection.execute(
            "UPDATE segments SET speaker_name = 'preserve', speaker_source = 'manual'"
        )
    replacement = FakePipelineHandler(settings, LOGGER)
    monkeypatch.setattr(replacement.adapters, "transcribe", crash)
    recover_stale_jobs(replacement, LOGGER)
    # The already queued finalization may run first; drain the full queue.
    while process_one_job(settings.database_path, replacement, LOGGER):
        pass
    with connect(settings.database_path) as connection:
        assert connection.execute("SELECT revision FROM recordings").fetchone()[0] == 2
        assert (
            connection.execute("SELECT status FROM jobs WHERE id = ?", (rerun.id,)).fetchone()[0]
            == "succeeded"
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM jobs WHERE kind = 'finalize_speakers' AND input_revision = 2"
            ).fetchone()[0]
            == 1
        )
        assert (
            connection.execute("SELECT content_hint FROM retranscription_requests").fetchone()[0]
            is None
        )
