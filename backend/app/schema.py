from __future__ import annotations

import re
from enum import StrEnum
from typing import Annotated, Literal, cast
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

SCHEMA_VERSION: Literal[2] = 2
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
    local_speaker_id: str | None
    assignment_status: Literal["assigned", "overlap", "unassigned"] = "assigned"
    overlapping_speaker_ids: list[str] = Field(default_factory=list)
    person_id: UUID | None = None
    speaker_name: str | None = None
    text: NonEmptyText

    @field_validator("local_speaker_id")
    @classmethod
    def validate_speaker_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if SPEAKER_PATTERN.fullmatch(value) is None:
            raise ValueError("local_speaker_id must match SPEAKER_00")
        return value

    @field_validator("overlapping_speaker_ids")
    @classmethod
    def validate_overlapping_speaker_ids(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("overlapping_speaker_ids must not contain duplicates")
        if any(SPEAKER_PATTERN.fullmatch(value) is None for value in values):
            raise ValueError("overlapping speaker IDs must match SPEAKER_00")
        return values

    @model_validator(mode="after")
    def validate_time_range(self) -> Segment:
        if self.end_ms <= self.start_ms:
            raise ValueError("segment end_ms must be greater than start_ms")
        if self.assignment_status == "unassigned":
            if self.local_speaker_id is not None or self.overlapping_speaker_ids:
                raise ValueError("unassigned segments must not have speaker IDs")
        elif self.local_speaker_id is None:
            raise ValueError("assigned and overlap segments require local_speaker_id")
        if self.assignment_status == "overlap":
            if len(self.overlapping_speaker_ids) < 2:
                raise ValueError("overlap segments require at least two overlapping speakers")
        elif self.overlapping_speaker_ids:
            raise ValueError("only overlap segments may have overlapping_speaker_ids")
        return self


class SpeechModelFingerprints(BaseModel):
    transcription: dict[str, object] = Field(min_length=1)
    alignment: dict[str, object] = Field(min_length=1)
    diarization: dict[str, object] = Field(min_length=1)


class Classification(BaseModel):
    schema_version: Literal[1]
    category: NonEmptyText
    confidence: float | None = Field(ge=0, le=1)
    reason: NonEmptyText

    def ensure_allowed(self, categories: tuple[str, ...]) -> Classification:
        if self.category not in categories:
            raise ValueError(f"category is not allowed: {self.category}")
        return self


class Transcript(BaseModel):
    schema_version: Literal[2] = SCHEMA_VERSION
    recording_id: UUID
    content_sha256: str
    revision: int = Field(ge=1)
    language: NonEmptyText
    needs_speaker_review: bool
    segments: list[Segment] = Field(min_length=1)
    model_fingerprints: SpeechModelFingerprints | None = None
    classification: Classification | None = None
    classification_source: Literal["auto", "manual"] | None = None
    classification_fingerprint: dict[str, object] | None = None

    @field_validator("content_sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        if SHA256_PATTERN.fullmatch(value) is None:
            raise ValueError("content_sha256 must be a lowercase SHA-256 digest")
        return value

    @model_validator(mode="after")
    def validate_segment_order(self) -> Transcript:
        ordered = sorted(self.segments, key=lambda segment: (segment.start_ms, segment.end_ms))
        if self.segments != ordered:
            raise ValueError("segments must be ordered by start_ms and end_ms")
        return self


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Evidence(StrictModel):
    segment_id: UUID
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    quote: NonEmptyText | None = None

    @model_validator(mode="after")
    def validate_time_range(self) -> Evidence:
        if self.end_ms <= self.start_ms:
            raise ValueError("evidence end_ms must be greater than start_ms")
        return self


class SummaryFact(StrictModel):
    text: NonEmptyText
    evidence: list[Evidence] = Field(min_length=1)


class ActionItem(StrictModel):
    assignee: str | None = None
    due_date: str | None = None
    task: NonEmptyText
    evidence: list[Evidence] = Field(min_length=1)

    @field_validator("assignee", "due_date")
    @classmethod
    def reject_empty_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("optional text must be null or non-empty")
        return normalized


class LectureSummary(StrictModel):
    template: Literal["lecture"]
    core_topics: list[SummaryFact]
    concepts: list[SummaryFact]
    examples: list[SummaryFact]
    review_items: list[SummaryFact]


class MeetingSummary(StrictModel):
    template: Literal["meeting"]
    purpose: SummaryFact
    discussion: list[SummaryFact]
    decisions: list[SummaryFact]
    action_items: list[ActionItem]
    open_questions: list[SummaryFact]


class DailyConversationSummary(StrictModel):
    template: Literal["daily_conversation"]
    main_topics: list[SummaryFact]
    agreements: list[SummaryFact]
    reminders: list[SummaryFact]


class GameListSummary(StrictModel):
    template: Literal["game_list"]
    games: list[SummaryFact]
    preferences: list[SummaryFact]
    follow_ups: list[SummaryFact]


class OtherSummary(StrictModel):
    template: Literal["other"]
    key_summary: SummaryFact
    key_facts: list[SummaryFact]
    follow_ups: list[SummaryFact]


CategorySummary = Annotated[
    LectureSummary | MeetingSummary | DailyConversationSummary | GameListSummary | OtherSummary,
    Field(discriminator="template"),
]


def summary_template_for_category(category: str) -> str:
    return {
        "강의": "lecture",
        "회의": "meeting",
        "일상 대화": "daily_conversation",
        "게임 목록": "game_list",
        "기타": "other",
    }.get(category, "other")


def summary_model_for_category(category: str) -> type[StrictModel]:
    template = summary_template_for_category(category)
    return cast(
        type[StrictModel],
        {
            "lecture": LectureSummary,
            "meeting": MeetingSummary,
            "daily_conversation": DailyConversationSummary,
            "game_list": GameListSummary,
            "other": OtherSummary,
        }[template],
    )


def validate_summary_evidence(summary: CategorySummary, transcript: Transcript) -> None:
    segments = {segment.id: segment for segment in transcript.segments}
    for evidence in _summary_evidence(summary):
        segment = segments.get(evidence.segment_id)
        if segment is None:
            raise ValueError(f"summary evidence references unknown segment: {evidence.segment_id}")
        if (evidence.start_ms, evidence.end_ms) != (segment.start_ms, segment.end_ms):
            raise ValueError("summary evidence timestamps do not match transcript")
        if evidence.quote is not None and evidence.quote not in segment.text:
            raise ValueError("summary evidence quote is not present in transcript")


def _summary_evidence(summary: CategorySummary) -> list[Evidence]:
    evidence: list[Evidence] = []
    for name, value in summary:
        if name == "template":
            continue
        values = value if isinstance(value, list) else [value]
        for item in values:
            if isinstance(item, (SummaryFact, ActionItem)):
                evidence.extend(item.evidence)
    return evidence
