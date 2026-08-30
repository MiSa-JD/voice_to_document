from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field, field_validator

from app.config import Settings
from app.db import connect, migrate_database, utc_now
from app.recordings_api import ApiErrorResponse, ApiProblem
from app.schema import Transcript


class RetranscriptionCreateRequest(BaseModel):
    expected_revision: int = Field(ge=1)
    language: Literal["auto", "ko", "en", "ja"] = "auto"
    content_description: str | None = Field(default=None, max_length=1000)
    terms: list[str] = Field(default_factory=list, max_length=50)
    confirm_impact: Literal[True]

    @field_validator("content_description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.split())
        return normalized or None

    @field_validator("terms")
    @classmethod
    def normalize_terms(cls, values: list[str]) -> list[str]:
        normalized = [" ".join(value.split()) for value in values]
        if any(not value or len(value) > 100 for value in normalized):
            raise ValueError("terms must contain 1 to 100 characters")
        if len(normalized) != len(set(normalized)):
            raise ValueError("terms must not contain duplicates")
        if sum(len(value) for value in normalized) > 2000:
            raise ValueError("terms are too long")
        return normalized


class RetranscriptionJobResponse(BaseModel):
    id: str
    kind: str = "transcribe"
    status: str
    input_revision: int


class RetranscriptionCreateResponse(BaseModel):
    request_id: str
    recording_id: str
    base_revision: int
    target_revision: int
    language: str
    hint_applied: bool
    warning: str
    job: RetranscriptionJobResponse


class RetranscriptionLatestResponse(BaseModel):
    request_id: str
    recording_id: str
    status: str
    base_revision: int
    target_revision: int
    previous_language: str | None
    requested_language: str
    new_language: str | None
    previous_segment_count: int
    new_segment_count: int | None
    unresolved_speaker_count: int | None
    hint_applied: bool
    history_available: bool
    history_location: str | None
    error_code: str | None
    created_at: str
    updated_at: str


WARNING = (
    "힌트는 정확도 향상을 보장하지 않으며 잘못된 언어 또는 힌트는 결과를 악화시킬 수 있습니다."
)


def create_retranscriptions_router(settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/api/recordings", tags=["retranscriptions"])

    @router.post(
        "/{recording_id}/retranscriptions",
        response_model=RetranscriptionCreateResponse,
        status_code=202,
        responses={404: {"model": ApiErrorResponse}, 409: {"model": ApiErrorResponse}},
    )
    def create_retranscription(
        recording_id: str, request: RetranscriptionCreateRequest
    ) -> RetranscriptionCreateResponse:
        migrate_database(settings.database_path)
        request_id = str(uuid.uuid4())
        job_id = str(uuid.uuid4())
        timestamp = utc_now()
        prompt = _initial_prompt(request.content_description, request.terms)
        hint_hash = hashlib.sha256(prompt.encode()).hexdigest()
        with connect(settings.database_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            recording = connection.execute(
                "SELECT revision FROM recordings WHERE id = ?", (recording_id,)
            ).fetchone()
            if recording is None:
                raise ApiProblem(404, "RECORDING_NOT_FOUND", "녹음을 찾을 수 없습니다.")
            current_revision = int(recording["revision"])
            if current_revision != request.expected_revision:
                raise ApiProblem(
                    409,
                    "REVISION_CONFLICT",
                    "다른 변경이 먼저 저장되었습니다.",
                    {"current_revision": current_revision},
                )
            active = connection.execute(
                """
                SELECT jobs.id FROM jobs
                WHERE recording_id = ? AND status IN ('queued', 'running')
                  AND kind IN ('transcribe', 'render') LIMIT 1
                """,
                (recording_id,),
            ).fetchone()
            if active is not None:
                raise ApiProblem(
                    409,
                    "RETRANSCRIPTION_IN_PROGRESS",
                    "이미 처리 중인 음성 작업이 있습니다.",
                    {"job_id": str(active["id"])},
                )
            duplicate = connection.execute(
                """
                SELECT id FROM retranscription_requests
                WHERE recording_id = ? AND base_revision = ?
                  AND requested_language = ? AND hint_hash = ?
                LIMIT 1
                """,
                (recording_id, current_revision, request.language, hint_hash),
            ).fetchone()
            if duplicate is not None:
                raise ApiProblem(
                    409,
                    "DUPLICATE_RETRANSCRIPTION",
                    "같은 설정의 재전사 요청이 이미 존재합니다.",
                )
            previous_segment_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM segments WHERE recording_id = ?",
                    (recording_id,),
                ).fetchone()[0]
            )
            previous_language = _current_language(settings, connection, recording_id)
            target_revision = current_revision + 1
            config_fingerprint = hashlib.sha256(
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
            connection.execute(
                """
                INSERT INTO jobs(
                    id, recording_id, kind, status, attempts, available_at,
                    created_at, updated_at, input_revision, settings_fingerprint
                ) VALUES (?, ?, 'transcribe', 'queued', 0, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    recording_id,
                    timestamp,
                    timestamp,
                    timestamp,
                    current_revision,
                    f"retranscription:{request_id}",
                ),
            )
            connection.execute(
                """
                INSERT INTO retranscription_requests(
                    id, recording_id, job_id, base_revision, target_revision,
                    requested_language, previous_language, content_hint, terms_json,
                    hint_hash, hint_applied, model_fingerprint, config_fingerprint,
                    previous_segment_count, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    request_id,
                    recording_id,
                    job_id,
                    current_revision,
                    target_revision,
                    request.language,
                    previous_language,
                    request.content_description,
                    json.dumps(request.terms, ensure_ascii=False),
                    hint_hash,
                    int(bool(prompt)),
                    settings.whisper_model,
                    config_fingerprint,
                    previous_segment_count,
                    timestamp,
                    timestamp,
                ),
            )
            connection.commit()
        return RetranscriptionCreateResponse(
            request_id=request_id,
            recording_id=recording_id,
            base_revision=current_revision,
            target_revision=target_revision,
            language=request.language,
            hint_applied=bool(prompt),
            warning=WARNING,
            job=RetranscriptionJobResponse(
                id=job_id, status="queued", input_revision=current_revision
            ),
        )

    @router.get(
        "/{recording_id}/retranscriptions/latest",
        response_model=RetranscriptionLatestResponse,
        responses={404: {"model": ApiErrorResponse}},
    )
    def latest_retranscription(recording_id: str) -> RetranscriptionLatestResponse:
        migrate_database(settings.database_path)
        with connect(settings.database_path) as connection:
            row = connection.execute(
                """
                SELECT rr.*, jobs.status, jobs.error_code
                FROM retranscription_requests AS rr
                JOIN jobs ON jobs.id = rr.job_id
                WHERE rr.recording_id = ?
                ORDER BY rr.created_at DESC, rr.id DESC LIMIT 1
                """,
                (recording_id,),
            ).fetchone()
        if row is None:
            raise ApiProblem(404, "RETRANSCRIPTION_NOT_FOUND", "재전사 요청이 없습니다.")
        value = dict(row)
        value["request_id"] = value.pop("id")
        value["hint_applied"] = bool(value["hint_applied"])
        value["history_available"] = value["history_relative_dir"] is not None
        value["history_location"] = (
            "app_data/history" if value["history_relative_dir"] is not None else None
        )
        value["new_language"] = _language_for_revision(
            settings, recording_id, int(value["target_revision"])
        )
        return RetranscriptionLatestResponse.model_validate(value)

    return router


def _initial_prompt(description: str | None, terms: list[str]) -> str:
    parts = [description or ""]
    if terms:
        parts.append("전문용어: " + ", ".join(terms))
    return "\n".join(part for part in parts if part)


def _current_language(settings: Settings, connection: object, recording_id: str) -> str | None:
    row = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT relative_path, revision FROM artifacts
        WHERE recording_id = ? AND kind = 'transcript_json'
        ORDER BY revision DESC LIMIT 1
        """,
        (recording_id,),
    ).fetchone()
    if row is None:
        return None
    return _read_language(settings.transcript_root, str(row["relative_path"]))


def _language_for_revision(settings: Settings, recording_id: str, revision: int) -> str | None:
    with connect(settings.database_path) as connection:
        row = connection.execute(
            """
            SELECT relative_path FROM artifacts
            WHERE recording_id = ? AND kind = 'transcript_json' AND revision = ?
            """,
            (recording_id, revision),
        ).fetchone()
    return (
        None if row is None else _read_language(settings.transcript_root, str(row["relative_path"]))
    )


def _read_language(root: Path, relative_path: str) -> str | None:
    path = (root.resolve() / relative_path).resolve()
    if not path.is_relative_to(root.resolve()):
        return None
    try:
        return Transcript.model_validate_json(path.read_bytes()).language
    except (OSError, ValueError):
        return None
