from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel, Field, TypeAdapter

from app.config import Settings
from app.db import connect, migrate_database, utc_now
from app.schema import CategorySummary, RecordingStatus
from app.summary import configured_summary_settings_fingerprint

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
    automatic_category: str | None
    category_source: Literal["auto", "manual"] | None
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


SpeakerMatchDecision = Literal[
    "insufficient_clips",
    "no_profiles",
    "insufficient_profiles",
    "auto_disabled",
    "below_threshold",
    "insufficient_margin",
    "duplicate_person",
    "rejected_candidate",
    "auto_matched",
]


class SpeakerMatchCandidateResponse(BaseModel):
    person_id: str
    display_name: str
    rank: int
    score: float
    rejected: bool


class SpeakerMatchResponse(BaseModel):
    decision: SpeakerMatchDecision
    best_score: float
    second_best_score: float
    margin: float
    input_revision: int
    candidates: list[SpeakerMatchCandidateResponse]


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
    match: SpeakerMatchResponse | None = None


class RecordingDetailResponse(BaseModel):
    recording: RecordingItem
    speakers: list[RecordingSpeakerResponse]
    segments: list[SegmentResponse]
    artifacts: list[ArtifactResponse]
    jobs: list[JobResponse]
    summary: CategorySummary | None
    allowed_categories: list[str]


class CategoryUpdateRequest(BaseModel):
    category: str = Field(min_length=1)
    expected_revision: int = Field(ge=1)


class CategoryRenderJobResponse(BaseModel):
    id: str
    kind: Literal["render"] = "render"
    status: Literal["queued"] = "queued"
    input_revision: int


class CategoryUpdateResponse(BaseModel):
    recording_id: str
    category: str
    category_source: Literal["manual"] = "manual"
    revision: int
    render_job: CategoryRenderJobResponse


class SummaryRequest(BaseModel):
    expected_revision: int = Field(ge=1)


class SummaryRequestResponse(BaseModel):
    recording_id: str
    revision: int
    created: bool
    job_id: str
    job_status: Literal["queued", "running", "succeeded"]


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
                       automatic_category, category_source,
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
                       automatic_category, category_source,
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
            match_rows = connection.execute(
                """
                SELECT local_speaker_id, decision, best_score, second_best_score,
                       margin, input_revision
                FROM speaker_match_results
                WHERE recording_id = ?
                ORDER BY local_speaker_id
                """,
                (recording_id,),
            ).fetchall()
            candidate_rows = connection.execute(
                """
                SELECT candidates.local_speaker_id, candidates.person_id,
                       persons.display_name, candidates.rank, candidates.score,
                       candidates.rejected
                FROM speaker_match_candidates AS candidates
                JOIN persons ON persons.id = candidates.person_id
                WHERE candidates.recording_id = ?
                ORDER BY candidates.local_speaker_id, candidates.rank
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
        candidates_by_speaker: dict[str, list[SpeakerMatchCandidateResponse]] = {}
        for candidate in candidate_rows:
            value = dict(candidate)
            value["rejected"] = bool(value["rejected"])
            candidates_by_speaker.setdefault(str(candidate["local_speaker_id"]), []).append(
                SpeakerMatchCandidateResponse.model_validate(value)
            )
        matches = {
            str(row["local_speaker_id"]): SpeakerMatchResponse(
                decision=row["decision"],
                best_score=row["best_score"],
                second_best_score=row["second_best_score"],
                margin=row["margin"],
                input_revision=row["input_revision"],
                candidates=candidates_by_speaker.get(str(row["local_speaker_id"]), []),
            )
            for row in match_rows
        }
        speaker_responses = []
        for row in speakers:
            value = dict(row)
            value["match"] = matches.get(str(row["local_speaker_id"]))
            speaker_responses.append(RecordingSpeakerResponse.model_validate(value))
        return RecordingDetailResponse(
            recording=_recording_item(dict(recording)),
            speakers=speaker_responses,
            segments=[_segment_response(dict(row)) for row in segments],
            artifacts=[ArtifactResponse.model_validate(dict(row)) for row in artifacts],
            jobs=[JobResponse.model_validate(dict(row)) for row in jobs],
            summary=_load_summary(settings.summary_root, artifacts, int(recording["revision"])),
            allowed_categories=list(settings.categories),
        )

    @router.post(
        "/{recording_id}/summary",
        response_model=SummaryRequestResponse,
        status_code=202,
        responses={
            404: {"model": ApiErrorResponse},
            409: {"model": ApiErrorResponse},
            422: {"model": ApiErrorResponse},
        },
    )
    def request_summary(
        recording_id: str, request: SummaryRequest, response: Response
    ) -> SummaryRequestResponse:
        migrate_database(settings.database_path)
        with connect(settings.database_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                recording = connection.execute(
                    "SELECT status, category, revision FROM recordings WHERE id = ?",
                    (recording_id,),
                ).fetchone()
                if recording is None:
                    raise ApiProblem(404, "RECORDING_NOT_FOUND", "녹음을 찾을 수 없습니다.")
                revision = int(recording["revision"])
                if revision != request.expected_revision:
                    raise ApiProblem(
                        409,
                        "REVISION_CONFLICT",
                        "다른 변경이 먼저 반영되었습니다. 최신 내용을 다시 확인해 주세요.",
                        {"current_revision": revision},
                    )
                category = recording["category"]
                if category is None:
                    raise ApiProblem(
                        422,
                        "SUMMARY_NOT_READY",
                        "분류가 완료된 뒤 요약을 요청할 수 있습니다.",
                    )
                active_input = connection.execute(
                    """
                    SELECT id, kind FROM jobs
                    WHERE recording_id = ? AND kind IN ('classify', 'render')
                      AND status IN ('queued', 'running')
                    ORDER BY created_at LIMIT 1
                    """,
                    (recording_id,),
                ).fetchone()
                if active_input is not None:
                    code = (
                        "CLASSIFICATION_IN_PROGRESS"
                        if active_input["kind"] == "classify"
                        else "RENDER_IN_PROGRESS"
                    )
                    raise ApiProblem(
                        422,
                        code,
                        "입력 문서를 처리하는 중입니다. 완료 후 다시 요청해 주세요.",
                        {"job_id": str(active_input["id"])},
                    )
                fingerprint = configured_summary_settings_fingerprint(settings, str(category))
                existing = connection.execute(
                    """
                    SELECT id, status FROM jobs
                    WHERE recording_id = ? AND kind = 'summarize' AND input_revision = ?
                      AND settings_fingerprint = ?
                      AND status IN ('queued', 'running', 'succeeded')
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    (recording_id, revision, fingerprint),
                ).fetchone()
                if existing is not None:
                    connection.commit()
                    response.status_code = 200
                    return SummaryRequestResponse(
                        recording_id=recording_id,
                        revision=revision,
                        created=False,
                        job_id=str(existing["id"]),
                        job_status=existing["status"],
                    )
                active_summary = connection.execute(
                    """
                    SELECT id FROM jobs WHERE recording_id = ? AND kind = 'summarize'
                      AND status IN ('queued', 'running') LIMIT 1
                    """,
                    (recording_id,),
                ).fetchone()
                if active_summary is not None:
                    raise ApiProblem(
                        422,
                        "SUMMARY_IN_PROGRESS",
                        "다른 입력의 요약을 처리하는 중입니다.",
                        {"job_id": str(active_summary["id"])},
                    )
                status = RecordingStatus(str(recording["status"]))
                if status not in {
                    RecordingStatus.READY_FOR_SUMMARY,
                    RecordingStatus.COMPLETED,
                    RecordingStatus.FAILED,
                }:
                    raise ApiProblem(
                        422,
                        "SUMMARY_NOT_READY",
                        "현재 처리 단계에서는 요약을 요청할 수 없습니다.",
                    )
                job_id = str(uuid.uuid4())
                timestamp = utc_now()
                connection.execute(
                    """
                    INSERT INTO jobs(
                        id, recording_id, kind, status, attempts, available_at,
                        created_at, updated_at, input_revision, settings_fingerprint
                    ) VALUES (?, ?, 'summarize', 'queued', 0, ?, ?, ?, ?, ?)
                    """,
                    (
                        job_id,
                        recording_id,
                        timestamp,
                        timestamp,
                        timestamp,
                        revision,
                        fingerprint,
                    ),
                )
                connection.execute(
                    """
                    UPDATE recordings SET status = 'SUMMARIZING', last_error_code = NULL,
                        last_error_message = NULL, updated_at = ? WHERE id = ?
                    """,
                    (timestamp, recording_id),
                )
                connection.execute(
                    """
                    INSERT INTO audit_events(id, recording_id, event_type, details_json, created_at)
                    VALUES (?, ?, 'summary_requested', ?, ?)
                    """,
                    (
                        str(uuid.uuid4()),
                        recording_id,
                        json.dumps(
                            {"revision": revision, "category": category},
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                        timestamp,
                    ),
                )
                connection.commit()
            except (ApiProblem, sqlite3.Error):
                connection.rollback()
                raise
        return SummaryRequestResponse(
            recording_id=recording_id,
            revision=revision,
            created=True,
            job_id=job_id,
            job_status="queued",
        )

    @router.patch(
        "/{recording_id}/category",
        response_model=CategoryUpdateResponse,
        responses={
            404: {"model": ApiErrorResponse},
            409: {"model": ApiErrorResponse},
            422: {"model": ApiErrorResponse},
        },
    )
    def update_category(
        recording_id: str, request: CategoryUpdateRequest
    ) -> CategoryUpdateResponse:
        if request.category not in settings.categories:
            raise ApiProblem(
                422,
                "INVALID_CATEGORY",
                "허용되지 않은 범주입니다.",
                {"allowed": list(settings.categories)},
            )
        migrate_database(settings.database_path)
        with connect(settings.database_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                recording = connection.execute(
                    "SELECT category, category_source, revision FROM recordings WHERE id = ?",
                    (recording_id,),
                ).fetchone()
                if recording is None:
                    raise ApiProblem(404, "RECORDING_NOT_FOUND", "녹음을 찾을 수 없습니다.")
                if int(recording["revision"]) != request.expected_revision:
                    raise ApiProblem(
                        409,
                        "REVISION_CONFLICT",
                        "다른 변경이 먼저 반영되었습니다. 최신 내용을 다시 확인해 주세요.",
                        {"current_revision": int(recording["revision"])},
                    )
                if str(recording["category"]) == request.category:
                    raise ApiProblem(
                        422,
                        "CATEGORY_UNCHANGED",
                        "현재 적용된 범주와 같습니다.",
                    )
                active = connection.execute(
                    """
                    SELECT id, kind FROM jobs
                    WHERE recording_id = ?
                      AND kind IN ('classify', 'render', 'summarize')
                      AND status IN ('queued', 'running')
                    ORDER BY created_at LIMIT 1
                    """,
                    (recording_id,),
                ).fetchone()
                if active is not None:
                    code = {
                        "classify": "CLASSIFICATION_IN_PROGRESS",
                        "render": "RENDER_IN_PROGRESS",
                        "summarize": "SUMMARY_IN_PROGRESS",
                    }[str(active["kind"])]
                    raise ApiProblem(
                        409,
                        code,
                        "관련 결과를 처리하는 중입니다. 완료 후 다시 시도해 주세요.",
                        {"job_id": str(active["id"]), "kind": str(active["kind"])},
                    )
                if recording["category"] is None:
                    raise ApiProblem(
                        422,
                        "CATEGORY_NOT_CLASSIFIED",
                        "자동 분류가 완료된 뒤 범주를 수정할 수 있습니다.",
                    )
                previous = str(recording["category"])
                revision = request.expected_revision + 1
                timestamp = utc_now()
                connection.execute(
                    """
                    UPDATE recordings
                    SET category = ?, category_source = 'manual', revision = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (request.category, revision, timestamp, recording_id),
                )
                job_id = str(uuid.uuid4())
                connection.execute(
                    """
                    INSERT INTO jobs(
                        id, recording_id, kind, status, attempts, available_at,
                        created_at, updated_at, input_revision, settings_fingerprint
                    ) VALUES (?, ?, 'render', 'queued', 0, ?, ?, ?, ?, 'category-edit-v1')
                    """,
                    (job_id, recording_id, timestamp, timestamp, timestamp, revision),
                )
                connection.execute(
                    """
                    INSERT INTO audit_events(
                        id, recording_id, event_type, details_json, created_at
                    ) VALUES (?, ?, 'recording_category_updated', ?, ?)
                    """,
                    (
                        str(uuid.uuid4()),
                        recording_id,
                        json.dumps(
                            {
                                "before": previous,
                                "after": request.category,
                                "revision": revision,
                            },
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                        timestamp,
                    ),
                )
                connection.commit()
            except (ApiProblem, sqlite3.Error):
                connection.rollback()
                raise
        return CategoryUpdateResponse(
            recording_id=recording_id,
            category=request.category,
            revision=revision,
            render_job=CategoryRenderJobResponse(id=job_id, input_revision=revision),
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


def _load_summary(
    root: Path, artifacts: list[Any], current_revision: int
) -> CategorySummary | None:
    row = next(
        (
            artifact
            for artifact in artifacts
            if artifact["kind"] == "summary_json" and int(artifact["revision"]) == current_revision
        ),
        None,
    )
    if row is None:
        return None
    root = root.resolve()
    path = (root / str(row["relative_path"])).resolve()
    if not path.is_relative_to(root):
        raise ApiProblem(500, "INVALID_ARTIFACT_PATH", "결과 파일 경로가 유효하지 않습니다.")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))["summary"]
        return TypeAdapter(CategorySummary).validate_python(value)
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise ApiProblem(500, "INVALID_ARTIFACT", "요약 결과를 읽을 수 없습니다.") from error
