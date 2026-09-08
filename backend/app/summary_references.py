"""Provider-only evidence references; persisted summaries keep the original schema."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import Field

from app.schema import NonEmptyText, StrictModel, SummaryValidationError, Transcript


class EvidenceReference(StrictModel):
    segment_id: UUID


class ReferenceFact(StrictModel):
    text: NonEmptyText
    evidence: list[EvidenceReference] = Field(min_length=1)


class ReferenceActionItem(StrictModel):
    task: NonEmptyText
    assignee: str | None = None
    due_date: str | None = None
    evidence: list[EvidenceReference] = Field(min_length=1)


class ReferenceLecture(StrictModel):
    template: Literal["lecture"]
    core_topics: list[ReferenceFact]
    concepts: list[ReferenceFact]
    examples: list[ReferenceFact]
    review_items: list[ReferenceFact]


class ReferenceMeeting(StrictModel):
    template: Literal["meeting"]
    purpose: ReferenceFact
    discussion: list[ReferenceFact]
    decisions: list[ReferenceFact]
    action_items: list[ReferenceActionItem]
    open_questions: list[ReferenceFact]


class ReferenceConversation(StrictModel):
    template: Literal["daily_conversation"]
    main_topics: list[ReferenceFact]
    agreements: list[ReferenceFact]
    reminders: list[ReferenceFact]


class ReferenceGames(StrictModel):
    template: Literal["game_list"]
    games: list[ReferenceFact]
    preferences: list[ReferenceFact]
    follow_ups: list[ReferenceFact]


class ReferenceOther(StrictModel):
    template: Literal["other"]
    key_summary: ReferenceFact
    key_facts: list[ReferenceFact]
    follow_ups: list[ReferenceFact]


class ReferenceFacts(StrictModel):
    facts: list[ReferenceFact]


REFERENCE_MODELS: dict[str, type[StrictModel]] = {
    "lecture": ReferenceLecture,
    "meeting": ReferenceMeeting,
    "daily_conversation": ReferenceConversation,
    "game_list": ReferenceGames,
    "other": ReferenceOther,
}


def resolve_evidence_references(value: StrictModel, transcript: Transcript) -> dict[str, object]:
    """Resolve only validated fact nodes against this call's input revision."""
    segments = {segment.id: segment for segment in transcript.segments}
    result = value.model_dump(mode="json")
    for name, field in value:
        items = field if isinstance(field, list) else [field]
        for index, item in enumerate(items):
            if not isinstance(item, (ReferenceFact, ReferenceActionItem)):
                continue
            path = f"{name}[{index}]" if isinstance(field, list) else name
            target = result[name][index] if isinstance(field, list) else result[name]
            for evidence_index, reference in enumerate(item.evidence):
                segment = segments.get(reference.segment_id)
                if segment is None:
                    raise SummaryValidationError(
                        "unknown_segment", f"{path}.evidence[{evidence_index}]"
                    )
                target["evidence"][evidence_index].update(
                    start_ms=segment.start_ms, end_ms=segment.end_ms, quote=segment.text
                )
    return result
