from __future__ import annotations

import fcntl
import hashlib
import json
import logging
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import TypeAdapter

from app.config import Settings
from app.db import connect, utc_now
from app.jobs import Job
from app.schema import (
    CategorySummary,
    Transcript,
    summary_template_for_category,
    validate_summary_evidence,
)
from app.state import _enqueue
from app.summary import _summary_fingerprint, summary_settings_fingerprint

if TYPE_CHECKING:
    from app.pipeline import FakePipelineHandler


class RecoveryError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@contextmanager
def worker_lock(database_path: Path) -> Iterator[None]:
    # Single host worker: the descriptor owns the lock, including across SIGKILL.
    database_path.parent.mkdir(parents=True, exist_ok=True)
    with database_path.with_suffix(".worker.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RecoveryError("WORKER_ALREADY_RUNNING") from None
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


@dataclass(frozen=True)
class RecoveryPlan:
    action: Literal["complete", "resume", "restart"]
    revision: int
    transcript: Transcript | None = None
    recording_status: str | None = None
    followup: tuple[str, str] | None = None


def artifact_bytes(
    connection: sqlite3.Connection, root: Path, recording_id: str, kind: str, revision: int
) -> bytes | None:
    row = connection.execute(
        "SELECT * FROM artifacts WHERE recording_id = ? AND kind = ? AND revision = ?",
        (recording_id, kind, revision),
    ).fetchone()
    if row is None:
        return None
    path = (root / str(row["relative_path"])).resolve()
    if not path.is_relative_to(root.resolve()):
        raise RecoveryError("RECOVERY_INPUT_INVALID")
    try:
        content = path.read_bytes()
    except OSError:
        raise RecoveryError("RECOVERY_INPUT_MISSING") from None
    if hashlib.sha256(content).hexdigest() != row["content_sha256"]:
        raise RecoveryError("RECOVERY_INPUT_INVALID")
    if kind.endswith("_json"):
        try:
            if json.loads(content)["schema_version"] != row["schema_version"]:
                raise ValueError
        except (ValueError, KeyError, TypeError):
            raise RecoveryError("RECOVERY_INPUT_INVALID") from None
    return content


def validate_source(settings: Settings, recording: sqlite3.Row) -> None:
    source = Path(str(recording["source_path"])).resolve()
    if not source.is_relative_to(settings.recording_input_dir.resolve()):
        raise RecoveryError("RECOVERY_INPUT_MISSING")
    try:
        with source.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
    except OSError:
        raise RecoveryError("RECOVERY_INPUT_MISSING") from None
    if digest != recording["content_sha256"]:
        raise RecoveryError("RECOVERY_INPUT_INVALID")


def inspect_recovery(
    connection: sqlite3.Connection, handler: FakePipelineHandler, job: Job
) -> RecoveryPlan:
    settings = handler.settings
    recording = connection.execute(
        "SELECT * FROM recordings WHERE id = ?", (job.recording_id,)
    ).fetchone()
    if recording is None:
        raise RecoveryError("RECOVERY_INPUT_MISSING")
    request = connection.execute(
        "SELECT * FROM retranscription_requests WHERE job_id = ?", (job.id,)
    ).fetchone()
    revision = int(recording["revision"])
    target = int(request["target_revision"]) if request else job.input_revision
    if revision != job.input_revision and not (request and revision == target):
        raise RecoveryError("RECOVERY_REVISION_CHANGED")
    content = artifact_bytes(
        connection, settings.transcript_root, job.recording_id, "transcript_json", revision
    )
    transcript = None
    if content is not None:
        transcript = validated_transcript(content, recording, revision)
        rows = connection.execute(
            "SELECT id, start_ms, end_ms, text FROM segments WHERE recording_id = ?",
            (job.recording_id,),
        ).fetchall()
        expected = {(str(s.id), s.start_ms, s.end_ms, s.text) for s in transcript.segments}
        if {tuple(row) for row in rows} != expected:
            raise RecoveryError("RECOVERY_INPUT_INVALID")
    if job.kind == "transcribe":
        if request:
            if job.settings_fingerprint != f"retranscription:{request['id']}":
                raise RecoveryError("RECOVERY_SETTINGS_CHANGED")
        elif job.settings_fingerprint != "input-v1":
            raise RecoveryError("RECOVERY_SETTINGS_CHANGED")
        if transcript is not None and revision == target:
            followup = connection.execute(
                "SELECT status FROM jobs WHERE recording_id = ? AND input_revision = ? "
                "AND kind = 'finalize_speakers' LIMIT 1",
                (job.recording_id, revision),
            ).fetchone()
            pending = connection.execute(
                "SELECT 1 FROM recording_speakers WHERE recording_id = ? "
                "AND clip_status = 'pending' LIMIT 1",
                (job.recording_id,),
            ).fetchone()
            clips = connection.execute(
                "SELECT kind FROM artifacts WHERE recording_id = ? AND revision = ? "
                "AND kind LIKE 'speaker_clip:%'",
                (job.recording_id, revision),
            ).fetchall()
            for clip in clips:
                artifact_bytes(
                    connection, settings.speaker_root, job.recording_id, str(clip["kind"]), revision
                )
            if followup and not pending:
                return RecoveryPlan("complete", revision, transcript)
            validate_source(settings, recording)
            return RecoveryPlan("resume", revision, transcript)
        if request:
            fingerprint = hashlib.sha256(
                json.dumps(
                    {
                        "model": settings.whisper_model,
                        "device": settings.whisper_device,
                        "compute_type": settings.whisper_compute_type,
                        "batch_size": settings.whisper_batch_size,
                    },
                    sort_keys=True,
                ).encode()
            ).hexdigest()
            if request["completed_at"] or request["config_fingerprint"] != fingerprint:
                raise RecoveryError("RECOVERY_SETTINGS_CHANGED")
            if revision != int(request["base_revision"]):
                raise RecoveryError("RECOVERY_INPUT_MISSING")
        validate_source(settings, recording)
        return RecoveryPlan("restart", revision)
    if job.kind == "render" and job.settings_fingerprint not in {
        "speaker-edit-v1",
        "category-edit-v1",
        "speaker-auto-match-v1",
    }:
        raise RecoveryError("RECOVERY_SETTINGS_CHANGED")
    if job.kind == "render":
        if transcript is not None:
            if (
                transcript.classification is None
                or transcript.classification.category != recording["category"]
                or transcript.classification_source != recording["category_source"]
            ):
                raise RecoveryError("RECOVERY_INPUT_INVALID")
            plan = document_completion_plan(connection, handler, job, transcript)
            if plan.action == "complete":
                return plan
        previous = connection.execute(
            "SELECT revision FROM artifacts WHERE recording_id = ? "
            "AND kind = 'transcript_json' AND revision < ? ORDER BY revision DESC LIMIT 1",
            (job.recording_id, revision),
        ).fetchone()
        if previous is None:
            raise RecoveryError("RECOVERY_INPUT_MISSING")
        previous_revision = int(previous["revision"])
        previous_content = artifact_bytes(
            connection,
            settings.transcript_root,
            job.recording_id,
            "transcript_json",
            previous_revision,
        )
        if previous_content is None:
            raise RecoveryError("RECOVERY_INPUT_MISSING")
        validated_transcript(previous_content, recording, previous_revision)
        return RecoveryPlan("restart", revision)
    if transcript is None:
        raise RecoveryError("RECOVERY_INPUT_MISSING")
    if job.kind == "summarize":
        category = str(recording["category"])
        data = artifact_bytes(
            connection, settings.summary_root, job.recording_id, "summary_json", revision
        )
        if data is not None:
            try:
                payload = json.loads(data)
                summary: CategorySummary = TypeAdapter(CategorySummary).validate_python(
                    payload["summary"]
                )
                validate_summary_evidence(summary, transcript)
                valid = (
                    payload["recording_id"] == job.recording_id
                    and payload["revision"] == revision
                    and payload["content_sha256"] == recording["content_sha256"]
                    and payload["category"] == category
                    and summary.template == summary_template_for_category(category)
                    and _summary_fingerprint(payload["summary_fingerprint"], category)
                    == job.settings_fingerprint
                )
                if not valid:
                    raise ValueError
            except (ValueError, KeyError, TypeError):
                raise RecoveryError("RECOVERY_INPUT_INVALID") from None
            if (
                artifact_bytes(
                    connection,
                    settings.summary_root,
                    job.recording_id,
                    "summary_markdown",
                    revision,
                )
                is None
            ):
                return RecoveryPlan("resume", revision, transcript)
            return RecoveryPlan("complete", revision, transcript, "COMPLETED")
        expected_fingerprint = summary_settings_fingerprint(handler.summary_adapter, category)
    elif job.kind == "classify":
        expected_fingerprint = hashlib.sha256(
            json.dumps(
                handler.classification_adapter.fingerprint, sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()
        if transcript.classification is not None:
            stored_fingerprint = hashlib.sha256(
                json.dumps(
                    transcript.classification_fingerprint, sort_keys=True, separators=(",", ":")
                ).encode()
            ).hexdigest()
            if (
                stored_fingerprint != job.settings_fingerprint
                or transcript.classification.category != recording["category"]
                or transcript.classification_source != recording["category_source"]
            ):
                raise RecoveryError("RECOVERY_SETTINGS_CHANGED")
            return document_completion_plan(connection, handler, job, transcript)
    elif job.kind == "finalize_speakers":
        expected_fingerprint = settings.speaker_finalization_settings_fingerprint
        clips = connection.execute(
            "SELECT kind, revision FROM artifacts WHERE recording_id = ? "
            "AND kind LIKE 'speaker_clip:%'",
            (job.recording_id,),
        ).fetchall()
        for clip in clips:
            artifact_bytes(
                connection,
                settings.speaker_root,
                job.recording_id,
                str(clip["kind"]),
                int(clip["revision"]),
            )
    else:
        raise RecoveryError("RECOVERY_INPUT_INVALID")
    if job.settings_fingerprint != expected_fingerprint:
        raise RecoveryError("RECOVERY_SETTINGS_CHANGED")
    return RecoveryPlan("restart", revision, transcript)


def validated_transcript(content: bytes, recording: sqlite3.Row, revision: int) -> Transcript:
    try:
        transcript = Transcript.model_validate_json(content)
    except ValueError:
        raise RecoveryError("RECOVERY_INPUT_INVALID") from None
    if (
        str(transcript.recording_id) != recording["id"]
        or transcript.revision != revision
        or transcript.content_sha256 != recording["content_sha256"]
    ):
        raise RecoveryError("RECOVERY_INPUT_INVALID")
    return transcript


def document_completion_plan(
    connection: sqlite3.Connection, handler: FakePipelineHandler, job: Job, transcript: Transcript
) -> RecoveryPlan:
    revision = transcript.revision
    if (
        artifact_bytes(
            connection,
            handler.settings.document_root,
            job.recording_id,
            "transcript_markdown",
            revision,
        )
        is None
    ):
        return RecoveryPlan("resume", revision, transcript)
    assert transcript.classification is not None
    category = transcript.classification.category
    had_summary = connection.execute(
        "SELECT 1 FROM artifacts WHERE recording_id = ? AND kind = 'summary_json' "
        "AND revision < ? LIMIT 1",
        (job.recording_id, revision),
    ).fetchone()
    if had_summary or category in handler.settings.auto_summary_categories:
        follow = ("summarize", summary_settings_fingerprint(handler.summary_adapter, category))
        return RecoveryPlan("complete", revision, transcript, "SUMMARIZING", follow)
    return RecoveryPlan("complete", revision, transcript, "COMPLETED")


def apply_completion(connection: sqlite3.Connection, job: Job, plan: RecoveryPlan) -> None:
    status = plan.recording_status
    if plan.followup:
        kind, fingerprint = plan.followup
        followup = connection.execute(
            "SELECT status, settings_fingerprint FROM jobs "
            "WHERE recording_id = ? AND kind = ? AND input_revision = ? "
            "ORDER BY created_at DESC, id DESC LIMIT 1",
            (job.recording_id, kind, plan.revision),
        ).fetchone()
        if followup is not None and followup["settings_fingerprint"] != fingerprint:
            raise RecoveryError("RECOVERY_SETTINGS_CHANGED")
        if followup is None:
            result = _enqueue(connection, job.recording_id, kind, plan.revision, fingerprint)
            followup = connection.execute(
                "SELECT status FROM jobs WHERE id = ?", (result.job_id,)
            ).fetchone()
        if followup["status"] not in ("queued", "running"):
            status = None
    if status:
        connection.execute(
            "UPDATE recordings SET status = ?, last_error_code = NULL, "
            "last_error_message = NULL, updated_at = ? WHERE id = ? AND revision = ?",
            (status, utc_now(), job.recording_id, plan.revision),
        )


def recovery_requested(database_path: Path, job_id: str) -> bool:
    with connect(database_path) as connection:
        return (
            connection.execute(
                "SELECT 1 FROM audit_events "
                "WHERE event_type IN ('job_recovered', 'job_manual_retry') "
                "AND json_extract(details_json, '$.job_id') = ? LIMIT 1",
                (job_id,),
            ).fetchone()
            is not None
        )


def recover_stale_jobs(handler: FakePipelineHandler, logger: logging.Logger) -> None:
    with connect(handler.settings.database_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        rows = connection.execute("SELECT * FROM jobs WHERE status = 'running'").fetchall()
        for row in rows:
            job = Job(
                *(
                    row[key]
                    for key in (
                        "id",
                        "recording_id",
                        "kind",
                        "attempts",
                        "input_revision",
                        "settings_fingerprint",
                    )
                )
            )
            code = None
            try:
                plan = inspect_recovery(connection, handler, job)
                action: str = plan.action
                if action == "complete":
                    apply_completion(connection, job, plan)
                    status = "succeeded"
                elif job.attempts >= 3:
                    raise RecoveryError("RECOVERY_ATTEMPTS_EXHAUSTED")
                else:
                    status = "queued"
            except RecoveryError as error:
                code = error.code
                action, status = "failed", "failed"
            timestamp = utc_now()
            connection.execute(
                "UPDATE jobs SET status = ?, locked_at = NULL, available_at = ?, "
                "updated_at = ?, error_code = ?, error_message = ? WHERE id = ?",
                (
                    status,
                    row["created_at"] if status == "queued" else timestamp,
                    timestamp,
                    code,
                    "작업 복구 조건을 확인한 뒤 다시 요청해 주세요." if code else None,
                    job.id,
                ),
            )
            if status in ("succeeded", "failed"):
                connection.execute(
                    "UPDATE retranscription_requests SET content_hint = NULL, terms_json = NULL, "
                    "completed_at = ?, updated_at = ? WHERE job_id = ?",
                    (timestamp, timestamp, job.id),
                )
            if status == "failed":
                connection.execute(
                    "UPDATE recordings SET status = 'FAILED', last_error_code = ?, "
                    "last_error_message = ?, updated_at = ? WHERE id = ? AND revision = ? "
                    "AND status != 'COMPLETED' AND NOT EXISTS "
                    "(SELECT 1 FROM retranscription_requests WHERE job_id = ?) "
                    "AND NOT EXISTS (SELECT 1 FROM jobs WHERE recording_id = ? AND id != ? "
                    "AND status IN ('queued', 'running'))",
                    (
                        code,
                        "작업 복구 조건을 확인한 뒤 다시 요청해 주세요.",
                        timestamp,
                        job.recording_id,
                        job.input_revision,
                        job.id,
                        job.recording_id,
                        job.id,
                    ),
                )
            details = dict(
                job_id=job.id, stage=job.kind, attempt=job.attempts, action=action, error_code=code
            )
            connection.execute(
                "INSERT INTO audit_events VALUES (?, ?, ?, ?, ?)",
                (
                    str(uuid.uuid4()),
                    job.recording_id,
                    "job_recovered",
                    json.dumps(details),
                    timestamp,
                ),
            )
            logger.info("job_recovered", extra={**details, "recording_id": job.recording_id})
