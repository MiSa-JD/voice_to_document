from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from app.long_transcript import (
    LongTranscriptClassifier,
    SegmentSlice,
    TopicEvidence,
    TranscriptIdentity,
    chunk_transcript,
)
from app.schema import Classification, Segment, Transcript


def _transcript(texts: tuple[str, ...]) -> Transcript:
    namespace = uuid.uuid4()
    return Transcript(
        recording_id=namespace,
        content_sha256="a" * 64,
        revision=3,
        language="ko",
        needs_speaker_review=True,
        segments=[
            Segment(
                id=uuid.uuid5(namespace, f"segment:{index}"),
                start_ms=index * 1_000,
                end_ms=(index + 1) * 1_000,
                local_speaker_id=f"SPEAKER_{index:02d}",
                text=text,
            )
            for index, text in enumerate(texts)
        ],
    )


def _result() -> Classification:
    return Classification(schema_version=1, category="회의", confidence=0.8, reason="주제")


@dataclass
class SpyDirectAdapter:
    calls: list[Transcript] = field(default_factory=list)
    fingerprint: dict[str, object] = field(default_factory=lambda: {"model": "direct"})

    def classify(
        self, transcript: Transcript, allowed_categories: tuple[str, ...]
    ) -> Classification:
        self.calls.append(transcript)
        assert "회의" in allowed_categories
        return _result()


@dataclass
class SpyTopicBackend:
    extracted: list[tuple[SegmentSlice, ...]] = field(default_factory=list)
    classified: list[tuple[TranscriptIdentity, tuple[TopicEvidence, ...]]] = field(
        default_factory=list
    )
    fingerprint: dict[str, object] = field(default_factory=lambda: {"model": "topics"})

    def extract(self, segments: tuple[SegmentSlice, ...]) -> str:
        self.extracted.append(segments)
        return f"topic-{len(self.extracted)}"

    def classify_topics(
        self,
        identity: TranscriptIdentity,
        topics: tuple[TopicEvidence, ...],
        allowed_categories: tuple[str, ...],
    ) -> Classification:
        self.classified.append((identity, topics))
        assert allowed_categories == ("회의", "기타")
        return _result()


def test_within_context_classifies_whole_transcript_once() -> None:
    transcript = _transcript(("abc", "def"))
    direct = SpyDirectAdapter()
    topics = SpyTopicBackend()
    classifier = LongTranscriptClassifier(direct, topics, topics, max_context_chars=6)

    assert classifier.classify(transcript, ("회의", "기타")) == _result()
    assert direct.calls == [transcript]
    assert topics.extracted == []
    assert topics.classified == []


def test_over_context_extracts_all_segments_then_classifies_topics() -> None:
    transcript = _transcript(("abcd", "efgh", "ijkl"))
    direct = SpyDirectAdapter()
    topics = SpyTopicBackend()
    classifier = LongTranscriptClassifier(direct, topics, topics, max_context_chars=5)

    classifier.classify(transcript, ("회의", "기타"))

    assert direct.calls == []
    flattened = [item for chunk in topics.extracted for item in chunk]
    assert "".join(item.text for item in flattened) == "abcdefghijkl"
    assert [item.segment_id for item in flattened] == [
        str(segment.id) for segment in transcript.segments
    ]
    assert [item.start_ms for item in flattened] == [0, 1_000, 2_000]
    assert [item.local_speaker_id for item in flattened] == [
        "SPEAKER_00",
        "SPEAKER_01",
        "SPEAKER_02",
    ]
    assert len(topics.classified) == 1
    assert topics.classified[0][0].revision == 3


def test_long_single_segment_is_sliced_without_front_truncation() -> None:
    transcript = _transcript(("abcdefghijk",))

    chunks = chunk_transcript(transcript, 4)
    slices = [item for chunk in chunks for item in chunk]

    assert [item.text for item in slices] == ["abcd", "efgh", "ijk"]
    assert [item.part_index for item in slices] == [0, 1, 2]
    assert {item.segment_id for item in slices} == {str(transcript.segments[0].id)}
    assert {item.start_ms for item in slices} == {0}
    assert {item.end_ms for item in slices} == {1_000}
    assert {item.local_speaker_id for item in slices} == {"SPEAKER_00"}


def test_fingerprint_records_strategy_and_context_limit() -> None:
    direct = SpyDirectAdapter()
    topics = SpyTopicBackend()
    classifier = LongTranscriptClassifier(direct, topics, topics, max_context_chars=42)

    assert classifier.fingerprint["strategy"] == "full-or-segment-topics-v1"
    assert classifier.fingerprint["max_context_chars"] == 42
