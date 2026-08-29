from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.config import Settings
from app.db import connect, migrate_database
from app.schema import MeetingSummary, RecordingStatus

PAGE_SIZE = 50


class ApiErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ApiErrorResponse(BaseModel):
    error: ApiErrorBody


class ApiProblem(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or {}


class RecordingItem(BaseModel):
    id: str
    original_name: str
    duration_ms: int
    status: RecordingStatus
    category: str | None
    category_confidence: float | None
    category_reason: str | None
    needs_speaker_review: bool
    revision: int
    created_at: str
    updated_at: str


class RecordingListResponse(BaseModel):
    items: list[RecordingItem]
    total: int
    page_size: int = PAGE_SIZE
    status_counts: dict[RecordingStatus, int]


class SegmentResponse(BaseModel):
    id: str
    start_ms: int
    end_ms: int
    local_speaker_id: str | None
    assignment_status: Literal["assigned", "overlap", "unassigned"]
    overlapping_speaker_ids: list[str]
    person_id: str | None
    speaker_name: str | None
    speaker_source: Literal["manual", "auto", "unresolved"]
    speaker_score: float | None
    text: str
    revision: int


class ArtifactResponse(BaseModel):
    id: str
    kind: str
    content_sha256: str
    schema_version: int
    revision: int
    created_at: str


class JobResponse(BaseModel):
    id: str
    kind: str
    status: str
    attempts: int
    input_revision: int
    settings_fingerprint: str
    error_code: str | None
    error_message: str | None
    created_at: str
    updated_at: str


class RecordingSpeakerResponse(BaseModel):
    local_speaker_id: str
    person_id: str | None
    speaker_name: str | None
    speaker_source: Literal["manual", "auto", "unresolved"]
    speaker_score: float | None
    segment_count: int
    duration_ms: int
    clip_status: Literal["pending", "ready", "insufficient", "failed"]
    clip_error_code: str | None
    representative_clip_artifact_id: str | None
    representative_clip_start_ms: int | None
    representative_clip_end_ms: int | None


class RecordingDetailResponse(BaseModel):
    recording: RecordingItem
    speakers: list[RecordingSpeakerResponse]
    segments: list[SegmentResponse]
    artifacts: list[ArtifactResponse]
    jobs: list[JobResponse]
    summary: MeetingSummary | None


def create_recordings_router(settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/api/recordings", tags=["recordings"])

    @router.get("", response_model=RecordingListResponse)
    def list_recordings(
        status: RecordingStatus | None = None,
        category: Annotated[str | None, Query(min_length=1)] = None,
    ) -> RecordingListResponse:
        if category is not None and category not in settings.categories:
            raise ApiProblem(
                422,
                "INVALID_CATEGORY",
                "허용되지 않은 범주입니다.",
                {"allowed": list(settings.categories)},
            )
        migrate_database(settings.database_path)
        clauses: list[str] = []
        parameters: list[str] = []
        if status is not None:
            clauses.append("status = ?")
            parameters.append(status.value)
        if category is not None:
            clauses.append("category = ?")
            parameters.append(category)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with connect(settings.database_path) as connection:
            rows = connection.execute(
                f"""
                SELECT id, original_name, duration_ms, status, category,
                       category_confidence, category_reason, needs_speaker_review,
                       revision, created_at, updated_at
                FROM recordings{where}
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (*parameters, PAGE_SIZE),
            ).fetchall()
            total = int(
                connection.execute(
                    f"SELECT COUNT(*) FROM recordings{where}", parameters
                ).fetchone()[0]
            )
            count_rows = connection.execute(
                "SELECT status, COUNT(*) AS count FROM recordings GROUP BY status"
            ).fetchall()
        counts = {value: 0 for value in RecordingStatus}
        counts.update({RecordingStatus(row["status"]): int(row["count"]) for row in count_rows})
        return RecordingListResponse(
            items=[_recording_item(dict(row)) for row in rows],
            total=total,
            status_counts=counts,
        )

    @router.get(
        "/{recording_id}",
        response_model=RecordingDetailResponse,
        responses={404: {"model": ApiErrorResponse}},
    )
    def recording_detail(recording_id: str) -> RecordingDetailResponse:
        migrate_database(settings.database_path)
        with connect(settings.database_path) as connection:
            recording = connection.execute(
                """
                SELECT id, original_name, duration_ms, status, category,
                       category_confidence, category_reason, needs_speaker_review,
                       revision, created_at, updated_at
                FROM recordings WHERE id = ?
                """,
                (recording_id,),
            ).fetchone()
            if recording is None:
                raise ApiProblem(404, "RECORDING_NOT_FOUND", "녹음을 찾을 수 없습니다.")
            segments = connection.execute(
                """
                SELECT segments.id, segments.start_ms, segments.end_ms,
                       segments.local_speaker_id, segments.assignment_status,
                       segments.overlapping_speaker_ids_json, segments.person_id,
                       COALESCE(persons.display_name, segments.speaker_name) AS speaker_name,
                       segments.speaker_source, segments.speaker_score,
                       segments.text, segments.revision
                FROM segments
                LEFT JOIN persons ON persons.id = segments.person_id
                WHERE segments.recording_id = ?
                ORDER BY segments.start_ms, segments.end_ms, segments.id
                """,
                (recording_id,),
            ).fetchall()
            speakers = connection.execute(
                """
                SELECT rs.local_speaker_id, rs.person_id,
                       persons.display_name AS speaker_name,
                       rs.speaker_source, rs.speaker_score,
                       COUNT(segments.id) AS segment_count,
                       COALESCE(SUM(segments.end_ms - segments.start_ms), 0) AS duration_ms,
                       rs.clip_status, rs.clip_error_code,
                       clip.artifact_id AS representative_clip_artifact_id,
                       clip.start_ms AS representative_clip_start_ms,
                       clip.end_ms AS representative_clip_end_ms
                FROM recording_speakers AS rs
                LEFT JOIN persons ON persons.id = rs.person_id
                LEFT JOIN segments
                  ON segments.recording_id = rs.recording_id
                 AND segments.local_speaker_id = rs.local_speaker_id
                LEFT JOIN speaker_clips AS clip
                  ON clip.recording_id = rs.recording_id
                 AND clip.local_speaker_id = rs.local_speaker_id
                 AND clip.clip_index = 0
                 AND clip.revision = (
                     SELECT MAX(latest.revision)
                     FROM speaker_clips AS latest
                     WHERE latest.recording_id = rs.recording_id
                       AND latest.local_speaker_id = rs.local_speaker_id
                 )
                WHERE rs.recording_id = ?
                GROUP BY rs.recording_id, rs.local_speaker_id
                ORDER BY rs.local_speaker_id
                """,
                (recording_id,),
            ).fetchall()
            artifacts = connection.execute(
                """
                SELECT id, kind, relative_path, content_sha256, schema_version,
                       revision, created_at
                FROM artifacts WHERE recording_id = ? ORDER BY created_at, kind
                """,
                (recording_id,),
            ).fetchall()
            jobs = connection.execute(
                """
                SELECT id, kind, status, attempts, input_revision, settings_fingerprint,
                       error_code, error_message, created_at, updated_at
                FROM jobs WHERE recording_id = ? ORDER BY created_at DESC, id DESC
                """,
                (recording_id,),
            ).fetchall()
        return RecordingDetailResponse(
            recording=_recording_item(dict(recording)),
            speakers=[RecordingSpeakerResponse.model_validate(dict(row)) for row in speakers],
            segments=[_segment_response(dict(row)) for row in segments],
            artifacts=[ArtifactResponse.model_validate(dict(row)) for row in artifacts],
            jobs=[JobResponse.model_validate(dict(row)) for row in jobs],
            summary=_load_summary(settings.summary_root, artifacts),
        )

    return router


def _recording_item(row: dict[str, Any]) -> RecordingItem:
    row["needs_speaker_review"] = bool(row["needs_speaker_review"])
    return RecordingItem.model_validate(row)


def _segment_response(row: dict[str, Any]) -> SegmentResponse:
    try:
        row["overlapping_speaker_ids"] = json.loads(row.pop("overlapping_speaker_ids_json"))
        return SegmentResponse.model_validate(row)
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise ApiProblem(500, "INVALID_SEGMENT", "발화 구간을 읽을 수 없습니다.") from error


def _load_summary(root: Path, artifacts: list[Any]) -> MeetingSummary | None:
    row = next((artifact for artifact in artifacts if artifact["kind"] == "summary_json"), None)
    if row is None:
        return None
    root = root.resolve()
    path = (root / str(row["relative_path"])).resolve()
    if not path.is_relative_to(root):
        raise ApiProblem(500, "INVALID_ARTIFACT_PATH", "결과 파일 경로가 유효하지 않습니다.")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))["summary"]
        return MeetingSummary.model_validate(value)
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise ApiProblem(500, "INVALID_ARTIFACT", "요약 결과를 읽을 수 없습니다.") from error
