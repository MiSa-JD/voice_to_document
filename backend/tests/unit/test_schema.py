from __future__ import annotations

import uuid

import pytest
from app.schema import Classification, RecordingStatus, Segment, Transcript
from pydantic import ValidationError


def _segment(**changes: object) -> Segment:
    values: dict[str, object] = {
        "id": uuid.uuid4(),
        "start_ms": 0,
        "end_ms": 900,
        "local_speaker_id": "SPEAKER_00",
        "text": "테스트 발화",
    }
    values.update(changes)
    return Segment.model_validate(values)


def test_normalized_transcript_accepts_valid_data() -> None:
    transcript = Transcript(
        recording_id=uuid.uuid4(),
        content_sha256="a" * 64,
        revision=1,
        language="ko",
        needs_speaker_review=False,
        segments=[_segment()],
    )

    assert transcript.schema_version == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"start_ms": 900, "end_ms": 900},
        {"local_speaker_id": "speaker-0"},
        {"text": "   "},
    ],
)
def test_segment_rejects_invalid_data(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _segment(**changes)


def test_unknown_recording_status_is_rejected() -> None:
    with pytest.raises(ValueError):
        RecordingStatus("UNKNOWN")


def test_classification_rejects_category_outside_settings() -> None:
    result = Classification(category="비밀 범주", confidence=0.9, reason="테스트")

    with pytest.raises(ValueError, match="not allowed"):
        result.ensure_allowed(("회의", "기타"))
