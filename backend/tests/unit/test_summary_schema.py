from __future__ import annotations

import uuid
from copy import deepcopy

import pytest
from app.schema import (
    CategorySummary,
    MeetingSummary,
    Segment,
    Transcript,
    summary_template_for_category,
    validate_summary_evidence,
)
from app.summary_renderer import render_summary_markdown
from pydantic import TypeAdapter, ValidationError

SEGMENT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
EVIDENCE = {
    "segment_id": str(SEGMENT_ID),
    "start_ms": 0,
    "end_ms": 900,
    "quote": "테스트 발화",
}
FACT = {"text": "확인된 사실", "evidence": [EVIDENCE]}


def _summary(template: str) -> dict[str, object]:
    values: dict[str, dict[str, object]] = {
        "lecture": {
            "template": "lecture",
            "core_topics": [FACT],
            "concepts": [],
            "examples": [],
            "review_items": [],
        },
        "meeting": {
            "template": "meeting",
            "purpose": FACT,
            "discussion": [],
            "decisions": [],
            "action_items": [
                {
                    "task": "초안 작성",
                    "assignee": None,
                    "due_date": None,
                    "evidence": [EVIDENCE],
                }
            ],
            "open_questions": [],
        },
        "daily_conversation": {
            "template": "daily_conversation",
            "main_topics": [FACT],
            "agreements": [],
            "reminders": [],
        },
        "game_list": {
            "template": "game_list",
            "games": [FACT],
            "preferences": [],
            "follow_ups": [],
        },
        "other": {
            "template": "other",
            "key_summary": FACT,
            "key_facts": [],
            "follow_ups": [],
        },
    }
    return deepcopy(values[template])


def _transcript() -> Transcript:
    return Transcript(
        recording_id=uuid.uuid4(),
        content_sha256="a" * 64,
        revision=1,
        language="ko",
        needs_speaker_review=False,
        segments=[
            Segment(
                id=SEGMENT_ID,
                start_ms=0,
                end_ms=900,
                local_speaker_id="SPEAKER_00",
                text="이것은 테스트 발화입니다.",
            )
        ],
    )


@pytest.mark.parametrize(
    ("template", "heading"),
    [
        ("lecture", "## 핵심 주제"),
        ("meeting", "## 할 일"),
        ("daily_conversation", "## 합의·약속"),
        ("game_list", "## 선호·평가"),
        ("other", "## 주요 사실"),
    ],
)
def test_category_summaries_validate_evidence_and_render(template: str, heading: str) -> None:
    summary: CategorySummary = TypeAdapter(CategorySummary).validate_python(_summary(template))

    validate_summary_evidence(summary, _transcript())
    markdown = render_summary_markdown(summary, "사용자 범주").decode()

    assert heading in markdown
    assert "근거:" in markdown
    if template == "meeting":
        assert "담당자: 확인되지 않음, 기한: 확인되지 않음" in markdown


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("segment_id", "00000000-0000-0000-0000-000000000099", "unknown segment"),
        ("start_ms", 1, "timestamps"),
        ("quote", "없는 문장", "quote"),
    ],
)
def test_summary_rejects_fabricated_evidence(field: str, value: object, message: str) -> None:
    raw = _summary("other")
    raw["key_summary"]["evidence"][0][field] = value  # type: ignore[index]
    summary: CategorySummary = TypeAdapter(CategorySummary).validate_python(raw)

    with pytest.raises(ValueError, match=message):
        validate_summary_evidence(summary, _transcript())


def test_summary_rejects_empty_text_extra_fields_and_empty_evidence() -> None:
    raw = _summary("other")
    raw["extra"] = True
    with pytest.raises(ValidationError):
        TypeAdapter(CategorySummary).validate_python(raw)

    raw = _summary("other")
    raw["key_summary"] = {"text": " ", "evidence": []}
    with pytest.raises(ValidationError):
        TypeAdapter(CategorySummary).validate_python(raw)


def test_custom_category_uses_other_template_and_preserves_display_name() -> None:
    summary: CategorySummary = TypeAdapter(CategorySummary).validate_python(_summary("other"))

    assert summary_template_for_category("사용자 정의") == "other"
    assert "범주: 사용자 정의" in render_summary_markdown(summary, "사용자 정의").decode()


def test_meeting_optional_fields_reject_empty_strings() -> None:
    raw = _summary("meeting")
    raw["action_items"][0]["assignee"] = " "  # type: ignore[index]
    with pytest.raises(ValidationError):
        TypeAdapter(CategorySummary).validate_python(raw)

    meeting: CategorySummary = TypeAdapter(CategorySummary).validate_python(_summary("meeting"))
    assert isinstance(meeting, MeetingSummary)
    assert meeting.action_items[0].assignee is None
