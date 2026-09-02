from __future__ import annotations

import json
import uuid

import pytest
from app.renderer import (
    format_timestamp,
    merge_adjacent_speaker_turns,
    render_transcript_json,
    render_transcript_markdown,
    transcript_artifact_paths,
    with_classification,
)
from app.schema import Classification, Segment, Transcript


def _segment(
    namespace: uuid.UUID,
    index: int,
    speaker: str | None,
    text: str,
    *,
    status: str = "assigned",
) -> Segment:
    return Segment.model_validate(
        {
            "id": uuid.uuid5(namespace, f"segment:{index}"),
            "start_ms": index * 1_001,
            "end_ms": (index + 1) * 1_001,
            "local_speaker_id": speaker,
            "assignment_status": status,
            "text": text,
        }
    )


def _classified_transcript() -> Transcript:
    namespace = uuid.uuid4()
    transcript = Transcript(
        recording_id=namespace,
        content_sha256="a" * 64,
        revision=7,
        language="ko",
        needs_speaker_review=True,
        segments=[
            _segment(namespace, 0, "SPEAKER_00", "첫 발화"),
            _segment(namespace, 1, "SPEAKER_00", "둘째 발화"),
            _segment(namespace, 2, "SPEAKER_01", "셋째 발화"),
            _segment(namespace, 3, None, "미배정 A", status="unassigned"),
            _segment(namespace, 4, None, "미배정 B", status="unassigned"),
        ],
    )
    return with_classification(
        transcript,
        Classification(schema_version=1, category="회의", confidence=0.875, reason="결정"),
    )


def test_json_preserves_segments_and_classification_without_markdown_merge() -> None:
    transcript = _classified_transcript()
    original_segments = transcript.segments.copy()

    value = json.loads(render_transcript_json(transcript))

    assert value["schema_version"] == 2
    assert value["recording_id"] == str(transcript.recording_id)
    assert value["content_sha256"] == "a" * 64
    assert value["revision"] == 7
    assert value["classification"] == {
        "schema_version": 1,
        "category": "회의",
        "confidence": 0.875,
        "reason": "결정",
    }
    assert len(value["segments"]) == 5
    assert value["segments"][0]["start_ms"] == 0
    assert value["segments"][0]["end_ms"] == 1_001
    assert value["segments"][0]["local_speaker_id"] == "SPEAKER_00"
    assert transcript.segments == original_segments


def test_markdown_merges_only_adjacent_assigned_same_speaker() -> None:
    transcript = _classified_transcript()

    markdown = render_transcript_markdown(transcript).decode()
    turns = merge_adjacent_speaker_turns(transcript.segments)

    assert len(turns) == 4
    assert turns[0].text == "첫 발화 둘째 발화"
    assert turns[1].speaker == "SPEAKER_01"
    assert turns[2].speaker == turns[3].speaker == "UNASSIGNED"
    assert "Recording ID:" in markdown
    assert "Revision: 7" in markdown
    assert "Category: 회의" in markdown
    assert "Category Source: auto" in markdown
    assert "Confidence: 0.8750" in markdown
    assert "Reason: 결정" in markdown
    assert "[00:00:00.000–00:00:02.002] SPEAKER_00" in markdown


def test_manual_classification_renders_source_without_fake_confidence() -> None:
    transcript = with_classification(
        _classified_transcript(),
        Classification(
            schema_version=1,
            category="강의",
            confidence=None,
            reason="사용자가 수동으로 선택한 범주입니다.",
        ),
        source="manual",
    )

    value = json.loads(render_transcript_json(transcript))
    markdown = render_transcript_markdown(transcript).decode()

    assert value["classification_source"] == "manual"
    assert value["classification"]["category"] == "강의"
    assert value["classification"]["confidence"] is None
    assert "Category Source: manual" in markdown
    assert "Confidence: N/A" in markdown


def test_renderer_requires_classification() -> None:
    classified = _classified_transcript()
    transcript = classified.model_copy(update={"classification": None})

    with pytest.raises(ValueError, match="classified transcript"):
        render_transcript_json(transcript)
    with pytest.raises(ValueError, match="classified transcript"):
        render_transcript_markdown(transcript)


@pytest.mark.parametrize("value", ["../escape", str(uuid.uuid4()).upper(), "not-a-uuid"])
def test_artifact_paths_reject_noncanonical_or_unsafe_recording_id(value: str) -> None:
    with pytest.raises(ValueError):
        transcript_artifact_paths(value)


def test_artifact_paths_are_recording_id_relative() -> None:
    recording_id = str(uuid.uuid4())

    paths = transcript_artifact_paths(recording_id)

    assert paths.json.as_posix() == f"{recording_id}/transcript.json"
    assert paths.markdown.as_posix() == f"{recording_id}/transcript.md"


def test_timestamp_preserves_millisecond_precision() -> None:
    assert format_timestamp(3_661_007) == "01:01:01.007"
