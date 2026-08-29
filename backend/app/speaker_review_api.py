from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter
from fastapi import Path as ApiPath
from pydantic import BaseModel, Field, field_validator

from app.db import connect, migrate_database, utc_now
from app.recordings_api import ApiErrorResponse, ApiProblem


class PersonResponse(BaseModel):
    id: str
    display_name: str
    revision: int
    created_at: str
    updated_at: str


class PersonListResponse(BaseModel):
    items: list[PersonResponse]
    total: int


class PersonCreateRequest(BaseModel):
    display_name: str

    @field_validator("display_name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return _validated_display_name(value)


class PersonUpdateRequest(PersonCreateRequest):
    expected_revision: int = Field(ge=1)


class SpeakerAssignmentRequest(BaseModel):
    person_id: str | None
    expected_revision: int = Field(ge=1)


class BatchSpeakerAssignmentRequest(SpeakerAssignmentRequest):
    recording_id: str
    segment_ids: list[str] = Field(min_length=1, max_length=500)

    @field_validator("segment_ids")
    @classmethod
    def unique_segment_ids(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("segment_ids must not contain duplicates")
        return values


class SpeakerAssignmentResponse(BaseModel):
    recording_id: str
    recording_revision: int
    person_id: str | None
    speaker_name: str | None
    updated_segment_count: int


def create_speaker_review_router(database_path: Path) -> APIRouter:
    router = APIRouter(tags=["speaker-review"])

    @router.get("/api/persons", response_model=PersonListResponse)
    def list_persons() -> PersonListResponse:
        migrate_database(database_path)
        with connect(database_path) as connection:
            rows = connection.execute(
                """
                SELECT id, display_name, revision, created_at, updated_at
                FROM persons ORDER BY display_name, created_at, id
                """
            ).fetchall()
        return PersonListResponse(
            items=[PersonResponse.model_validate(dict(row)) for row in rows],
            total=len(rows),
        )

    @router.post(
        "/api/persons",
        response_model=PersonResponse,
        status_code=201,
        responses={422: {"model": ApiErrorResponse}},
    )
    def create_person(request: PersonCreateRequest) -> PersonResponse:
        migrate_database(database_path)
        person_id = str(uuid.uuid4())
        timestamp = utc_now()
        with connect(database_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO persons(id, display_name, revision, created_at, updated_at)
                VALUES (?, ?, 1, ?, ?)
                """,
                (person_id, request.display_name, timestamp, timestamp),
            )
            _audit(
                connection,
                "person_created",
                {"person_id": person_id, "revision": 1},
            )
            row = connection.execute(
                """
                SELECT id, display_name, revision, created_at, updated_at
                FROM persons WHERE id = ?
                """,
                (person_id,),
            ).fetchone()
            connection.commit()
        return PersonResponse.model_validate(dict(row))

    @router.patch(
        "/api/persons/{person_id}",
        response_model=PersonResponse,
        responses={404: {"model": ApiErrorResponse}, 409: {"model": ApiErrorResponse}},
    )
    def update_person(person_id: str, request: PersonUpdateRequest) -> PersonResponse:
        migrate_database(database_path)
        with connect(database_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute(
                "SELECT revision FROM persons WHERE id = ?", (person_id,)
            ).fetchone()
            if current is None:
                raise ApiProblem(404, "PERSON_NOT_FOUND", "인물을 찾을 수 없습니다.")
            current_revision = int(current["revision"])
            _check_revision(current_revision, request.expected_revision)
            new_revision = current_revision + 1
            connection.execute(
                """
                UPDATE persons SET display_name = ?, revision = ?, updated_at = ?
                WHERE id = ?
                """,
                (request.display_name, new_revision, utc_now(), person_id),
            )
            _audit(
                connection,
                "person_updated",
                {
                    "person_id": person_id,
                    "previous_revision": current_revision,
                    "revision": new_revision,
                },
            )
            row = connection.execute(
                """
                SELECT id, display_name, revision, created_at, updated_at
                FROM persons WHERE id = ?
                """,
                (person_id,),
            ).fetchone()
            connection.commit()
        return PersonResponse.model_validate(dict(row))

    @router.put(
        "/api/recordings/{recording_id}/speakers/{local_speaker_id}",
        response_model=SpeakerAssignmentResponse,
        responses={
            404: {"model": ApiErrorResponse},
            409: {"model": ApiErrorResponse},
            422: {"model": ApiErrorResponse},
        },
    )
    def assign_recording_speaker(
        recording_id: str,
        local_speaker_id: Annotated[str, ApiPath(min_length=1, max_length=100)],
        request: SpeakerAssignmentRequest,
    ) -> SpeakerAssignmentResponse:
        migrate_database(database_path)
        with connect(database_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            current_revision = _recording_revision(connection, recording_id)
            _check_revision(current_revision, request.expected_revision)
            speaker = connection.execute(
                """
                SELECT 1 FROM recording_speakers
                WHERE recording_id = ? AND local_speaker_id = ?
                """,
                (recording_id, local_speaker_id),
            ).fetchone()
            if speaker is None:
                raise ApiProblem(
                    404, "RECORDING_SPEAKER_NOT_FOUND", "녹음 화자를 찾을 수 없습니다."
                )
            speaker_name = _person_name(connection, request.person_id)
            new_revision = current_revision + 1
            timestamp = utc_now()
            connection.execute(
                """
                UPDATE recording_speakers
                SET person_id = ?, speaker_source = 'manual', speaker_score = NULL,
                    revision = ?, updated_at = ?
                WHERE recording_id = ? AND local_speaker_id = ?
                """,
                (request.person_id, new_revision, timestamp, recording_id, local_speaker_id),
            )
            cursor = connection.execute(
                """
                UPDATE segments
                SET person_id = ?, speaker_name = ?, speaker_source = 'manual',
                    speaker_score = NULL, revision = ?
                WHERE recording_id = ? AND local_speaker_id = ?
                """,
                (
                    request.person_id,
                    speaker_name,
                    new_revision,
                    recording_id,
                    local_speaker_id,
                ),
            )
            _update_recording_revision(connection, recording_id, new_revision, timestamp)
            _audit(
                connection,
                "recording_speaker_assigned",
                {
                    "local_speaker_id": local_speaker_id,
                    "person_id": request.person_id,
                    "previous_revision": current_revision,
                    "revision": new_revision,
                    "updated_segment_count": cursor.rowcount,
                },
                recording_id,
            )
            connection.commit()
        return SpeakerAssignmentResponse(
            recording_id=recording_id,
            recording_revision=new_revision,
            person_id=request.person_id,
            speaker_name=speaker_name,
            updated_segment_count=cursor.rowcount,
        )

    @router.patch(
        "/api/segments/{segment_id}/speaker",
        response_model=SpeakerAssignmentResponse,
        responses={
            404: {"model": ApiErrorResponse},
            409: {"model": ApiErrorResponse},
            422: {"model": ApiErrorResponse},
        },
    )
    def assign_segment(
        segment_id: str, request: SpeakerAssignmentRequest
    ) -> SpeakerAssignmentResponse:
        migrate_database(database_path)
        with connect(database_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            segment = connection.execute(
                "SELECT recording_id FROM segments WHERE id = ?", (segment_id,)
            ).fetchone()
            if segment is None:
                raise ApiProblem(404, "SEGMENT_NOT_FOUND", "발화 구간을 찾을 수 없습니다.")
            recording_id = str(segment["recording_id"])
            current_revision = _recording_revision(connection, recording_id)
            _check_revision(current_revision, request.expected_revision)
            speaker_name = _person_name(connection, request.person_id)
            new_revision = current_revision + 1
            timestamp = utc_now()
            connection.execute(
                """
                UPDATE segments
                SET person_id = ?, speaker_name = ?, speaker_source = 'manual',
                    speaker_score = NULL, revision = ?
                WHERE id = ?
                """,
                (request.person_id, speaker_name, new_revision, segment_id),
            )
            _update_recording_revision(connection, recording_id, new_revision, timestamp)
            _audit(
                connection,
                "segment_speaker_assigned",
                {
                    "segment_ids": [segment_id],
                    "person_id": request.person_id,
                    "previous_revision": current_revision,
                    "revision": new_revision,
                },
                recording_id,
            )
            connection.commit()
        return SpeakerAssignmentResponse(
            recording_id=recording_id,
            recording_revision=new_revision,
            person_id=request.person_id,
            speaker_name=speaker_name,
            updated_segment_count=1,
        )

    @router.patch(
        "/api/segments/speakers",
        response_model=SpeakerAssignmentResponse,
        responses={
            404: {"model": ApiErrorResponse},
            409: {"model": ApiErrorResponse},
            422: {"model": ApiErrorResponse},
        },
    )
    def assign_segments(request: BatchSpeakerAssignmentRequest) -> SpeakerAssignmentResponse:
        migrate_database(database_path)
        with connect(database_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            current_revision = _recording_revision(connection, request.recording_id)
            _check_revision(current_revision, request.expected_revision)
            placeholders = ",".join("?" for _ in request.segment_ids)
            rows = connection.execute(
                f"SELECT id, recording_id FROM segments WHERE id IN ({placeholders})",
                request.segment_ids,
            ).fetchall()
            found = {str(row["id"]): str(row["recording_id"]) for row in rows}
            if len(found) != len(request.segment_ids):
                raise ApiProblem(404, "SEGMENT_NOT_FOUND", "발화 구간을 찾을 수 없습니다.")
            if any(recording_id != request.recording_id for recording_id in found.values()):
                raise ApiProblem(
                    422,
                    "SEGMENTS_RECORDING_MISMATCH",
                    "모든 발화 구간은 같은 녹음에 속해야 합니다.",
                )
            speaker_name = _person_name(connection, request.person_id)
            new_revision = current_revision + 1
            timestamp = utc_now()
            cursor = connection.execute(
                f"""
                UPDATE segments
                SET person_id = ?, speaker_name = ?, speaker_source = 'manual',
                    speaker_score = NULL, revision = ?
                WHERE id IN ({placeholders})
                """,
                (request.person_id, speaker_name, new_revision, *request.segment_ids),
            )
            _update_recording_revision(connection, request.recording_id, new_revision, timestamp)
            _audit(
                connection,
                "segments_speaker_assigned",
                {
                    "segment_ids": sorted(request.segment_ids),
                    "person_id": request.person_id,
                    "previous_revision": current_revision,
                    "revision": new_revision,
                },
                request.recording_id,
            )
            connection.commit()
        return SpeakerAssignmentResponse(
            recording_id=request.recording_id,
            recording_revision=new_revision,
            person_id=request.person_id,
            speaker_name=speaker_name,
            updated_segment_count=cursor.rowcount,
        )

    return router


def _validated_display_name(value: str) -> str:
    normalized = value.strip()
    if not 1 <= len(normalized) <= 100:
        raise ValueError("display_name must contain between 1 and 100 characters")
    return normalized


def _recording_revision(connection: sqlite3.Connection, recording_id: str) -> int:
    row = connection.execute(
        "SELECT revision FROM recordings WHERE id = ?", (recording_id,)
    ).fetchone()
    if row is None:
        raise ApiProblem(404, "RECORDING_NOT_FOUND", "녹음을 찾을 수 없습니다.")
    return int(row["revision"])


def _check_revision(current: int, expected: int) -> None:
    if current != expected:
        raise ApiProblem(
            409,
            "REVISION_CONFLICT",
            "다른 변경이 먼저 저장되었습니다.",
            {"current_revision": current},
        )


def _person_name(connection: sqlite3.Connection, person_id: str | None) -> str | None:
    if person_id is None:
        return None
    row = connection.execute(
        "SELECT display_name FROM persons WHERE id = ?", (person_id,)
    ).fetchone()
    if row is None:
        raise ApiProblem(404, "PERSON_NOT_FOUND", "인물을 찾을 수 없습니다.")
    return str(row["display_name"])


def _update_recording_revision(
    connection: sqlite3.Connection,
    recording_id: str,
    revision: int,
    timestamp: str,
) -> None:
    connection.execute(
        "UPDATE recordings SET revision = ?, updated_at = ? WHERE id = ?",
        (revision, timestamp, recording_id),
    )


def _audit(
    connection: sqlite3.Connection,
    event_type: str,
    details: dict[str, Any],
    recording_id: str | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO audit_events(id, recording_id, event_type, details_json, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            str(uuid.uuid4()),
            recording_id,
            event_type,
            json.dumps(details, ensure_ascii=False, sort_keys=True),
            utc_now(),
        ),
    )
