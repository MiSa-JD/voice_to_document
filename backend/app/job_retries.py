from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from typing import Literal, cast

from pydantic import SecretStr

from app.config import Settings
from app.db import utc_now
from app.document_adapters import build_document_adapters
from app.jobs import Job
from app.pipeline import FakePipelineHandler
from app.recovery import RecoveryError, inspect_recovery, validate_source
from app.state import _enqueue

RecoveryAction = Literal["retry", "request_summary", "retranscribe", "none"]


def recovery_handler(settings: Settings) -> FakePipelineHandler:
    # Inspection needs document fingerprints and settings, never speech initialization.
    config = settings.model_copy(update={"llm_api_key": SecretStr("")})
    classification_adapter, summary_adapter = build_document_adapters(config)
    return FakePipelineHandler(
        config,
        logging.getLogger("api"),
        classification_adapter=classification_adapter,
        summary_adapter=summary_adapter,
    )


def row_job(row: sqlite3.Row) -> Job:
    return Job(
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


def retry_child(connection: sqlite3.Connection, job_id: str) -> sqlite3.Row | None:
    row = connection.execute(
        "SELECT jobs.* FROM audit_events JOIN jobs "
        "ON jobs.id = json_extract(details_json, '$.job_id') "
        "WHERE event_type = 'job_manual_retry' "
        "AND json_extract(details_json, '$.original_job_id') = ? LIMIT 1",
        (job_id,),
    ).fetchone()
    return cast(sqlite3.Row | None, row)


def recovery_action(
    connection: sqlite3.Connection, handler: FakePipelineHandler, row: sqlite3.Row
) -> tuple[RecoveryAction, str | None]:
    if row["status"] != "failed":
        return "none", None
    recording = connection.execute(
        "SELECT * FROM recordings WHERE id = ?", (row["recording_id"],)
    ).fetchone()
    if recording is None or recording["revision"] != row["input_revision"]:
        return "none", "최신 revision의 작업에서 다시 요청해 주세요."
    if retry_child(connection, str(row["id"])) is not None:
        return "none", "이미 재시도한 작업입니다. 새 작업의 처리 이력을 확인해 주세요."
    active = connection.execute(
        "SELECT 1 FROM jobs WHERE recording_id = ? AND status IN ('queued', 'running') LIMIT 1",
        (row["recording_id"],),
    ).fetchone()
    if active:
        return "none", "관련 작업이 처리 중입니다. 완료 후 다시 확인해 주세요."
    if row["kind"] == "summarize":
        return "request_summary", "요약 영역에서 현재 입력으로 다시 요청해 주세요."
    request = connection.execute(
        "SELECT 1 FROM retranscription_requests WHERE job_id = ?", (row["id"],)
    ).fetchone()
    try:
        if request:
            validate_source(handler.settings, recording)
            return "retranscribe", "STT 재수행에서 언어와 힌트를 새로 입력해 주세요."
        inspect_recovery(connection, handler, row_job(row))
    except RecoveryError as error:
        from app.job_failures import job_failure_policy

        policy = job_failure_policy(error.code)
        return "none", policy.message if policy else "입력을 확인해 주세요."
    succeeded = connection.execute(
        "SELECT 1 FROM jobs WHERE recording_id = ? AND kind = ? AND input_revision = ? "
        "AND settings_fingerprint = ? AND status = 'succeeded' LIMIT 1",
        (row["recording_id"], row["kind"], row["input_revision"], row["settings_fingerprint"]),
    ).fetchone()
    if succeeded:
        return "none", "같은 입력의 작업이 이미 완료되었습니다."
    return "retry", "입력과 실행 환경을 확인한 뒤 새 작업으로 다시 시도할 수 있습니다."


def enqueue_retry(connection: sqlite3.Connection, row: sqlite3.Row) -> tuple[str, bool]:
    result = _enqueue(
        connection,
        str(row["recording_id"]),
        str(row["kind"]),
        int(row["input_revision"]),
        str(row["settings_fingerprint"]),
    )
    if not result.created:
        return result.job_id, False
    timestamp = utc_now()
    connection.execute(
        "INSERT INTO audit_events VALUES (?, ?, ?, ?, ?)",
        (
            str(uuid.uuid4()),
            row["recording_id"],
            "job_manual_retry",
            json.dumps(
                {
                    "job_id": result.job_id,
                    "original_job_id": row["id"],
                    "stage": row["kind"],
                    "input_revision": row["input_revision"],
                }
            ),
            timestamp,
        ),
    )
    if row["kind"] in {"transcribe", "classify"}:
        status = "TRANSCRIBING" if row["kind"] == "transcribe" else "CLASSIFYING"
        connection.execute(
            "UPDATE recordings SET status = ?, last_error_code = NULL, last_error_message = NULL, "
            "updated_at = ? WHERE id = ? AND revision = ?",
            (status, timestamp, row["recording_id"], row["input_revision"]),
        )
    else:
        connection.execute(
            "UPDATE recordings SET status = CASE WHEN category IS NULL THEN 'TRANSCRIBING' "
            "ELSE 'COMPLETED' END, last_error_code = NULL, "
            "last_error_message = NULL, updated_at = ? "
            "WHERE id = ? AND revision = ? AND status = 'FAILED'",
            (timestamp, row["recording_id"], row["input_revision"]),
        )
    return result.job_id, True
