from __future__ import annotations

import re
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field, StringConstraints, field_validator, model_validator

SCHEMA_VERSION: Literal[1] = 1
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
SPEAKER_PATTERN = re.compile(r"^SPEAKER_[0-9]{2,}$")
NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class RecordingStatus(StrEnum):
    DISCOVERED = "DISCOVERED"
    TRANSCRIBING = "TRANSCRIBING"
    SPEAKER_REVIEW = "SPEAKER_REVIEW"
    CLASSIFYING = "CLASSIFYING"
    READY_FOR_SUMMARY = "READY_FOR_SUMMARY"
    SUMMARIZING = "SUMMARIZING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class Segment(BaseModel):
    id: UUID
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    local_speaker_id: str
    person_id: UUID | None = None
    speaker_name: str | None = None
    text: NonEmptyText

    @field_validator("local_speaker_id")
    @classmethod
    def validate_speaker_id(cls, value: str) -> str:
        if SPEAKER_PATTERN.fullmatch(value) is None:
            raise ValueError("local_speaker_id must match SPEAKER_00")
        return value

    @model_validator(mode="after")
    def validate_time_range(self) -> Segment:
        if self.end_ms <= self.start_ms:
            raise ValueError("segment end_ms must be greater than start_ms")
        return self


class Transcript(BaseModel):
    schema_version: Literal[1] = SCHEMA_VERSION
    recording_id: UUID
    content_sha256: str
    revision: int = Field(ge=1)
    language: NonEmptyText
    needs_speaker_review: bool
    segments: list[Segment] = Field(min_length=1)

    @field_validator("content_sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        if SHA256_PATTERN.fullmatch(value) is None:
            raise ValueError("content_sha256 must be a lowercase SHA-256 digest")
        return value


class Classification(BaseModel):
    category: NonEmptyText
    confidence: float = Field(ge=0, le=1)
    reason: NonEmptyText

    def ensure_allowed(self, categories: tuple[str, ...]) -> Classification:
        if self.category not in categories:
            raise ValueError(f"category is not allowed: {self.category}")
        return self


class ActionItem(BaseModel):
    assignee: str | None = None
    due_date: str | None = None
    task: NonEmptyText


class MeetingSummary(BaseModel):
    purpose: NonEmptyText
    discussion: list[NonEmptyText]
    decisions: list[NonEmptyText]
    action_items: list[ActionItem]
    open_questions: list[NonEmptyText]
