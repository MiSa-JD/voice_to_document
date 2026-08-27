from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.classification import ClassificationAdapter
from app.schema import Classification, Segment, Transcript


@dataclass(frozen=True)
class SegmentSlice:
    segment_id: str
    start_ms: int
    end_ms: int
    local_speaker_id: str | None
    part_index: int
    text: str


@dataclass(frozen=True)
class TranscriptIdentity:
    recording_id: str
    content_sha256: str
    revision: int
    language: str


@dataclass(frozen=True)
class TopicEvidence:
    topic: str
    segments: tuple[SegmentSlice, ...]


class TopicExtractor(Protocol):
    @property
    def fingerprint(self) -> dict[str, object]: ...

    def extract(self, segments: tuple[SegmentSlice, ...]) -> str: ...


class TopicClassificationAdapter(Protocol):
    @property
    def fingerprint(self) -> dict[str, object]: ...

    def classify_topics(
        self,
        identity: TranscriptIdentity,
        topics: tuple[TopicEvidence, ...],
        allowed_categories: tuple[str, ...],
    ) -> Classification: ...


class LongTranscriptClassifier:
    def __init__(
        self,
        direct_adapter: ClassificationAdapter,
        topic_extractor: TopicExtractor,
        topic_adapter: TopicClassificationAdapter,
        *,
        max_context_chars: int,
    ) -> None:
        if max_context_chars <= 0:
            raise ValueError("max_context_chars must be positive")
        self.direct_adapter = direct_adapter
        self.topic_extractor = topic_extractor
        self.topic_adapter = topic_adapter
        self.max_context_chars = max_context_chars

    @property
    def fingerprint(self) -> dict[str, object]:
        return {
            "strategy": "full-or-segment-topics-v1",
            "max_context_chars": self.max_context_chars,
            "direct": self.direct_adapter.fingerprint,
            "topic_extractor": self.topic_extractor.fingerprint,
            "topic_classifier": self.topic_adapter.fingerprint,
        }

    def classify(
        self,
        transcript: Transcript,
        allowed_categories: tuple[str, ...],
    ) -> Classification:
        if transcript_character_count(transcript) <= self.max_context_chars:
            return self.direct_adapter.classify(transcript, allowed_categories)

        chunks = chunk_transcript(transcript, self.max_context_chars)
        topics = tuple(
            TopicEvidence(topic=self.topic_extractor.extract(chunk), segments=chunk)
            for chunk in chunks
        )
        identity = TranscriptIdentity(
            recording_id=str(transcript.recording_id),
            content_sha256=transcript.content_sha256,
            revision=transcript.revision,
            language=transcript.language,
        )
        return self.topic_adapter.classify_topics(identity, topics, allowed_categories)


def transcript_character_count(transcript: Transcript) -> int:
    return sum(len(segment.text) for segment in transcript.segments)


def chunk_transcript(
    transcript: Transcript,
    max_context_chars: int,
) -> tuple[tuple[SegmentSlice, ...], ...]:
    if max_context_chars <= 0:
        raise ValueError("max_context_chars must be positive")
    slices = tuple(
        item
        for segment in transcript.segments
        for item in _slice_segment(segment, max_context_chars)
    )
    chunks: list[tuple[SegmentSlice, ...]] = []
    current: list[SegmentSlice] = []
    current_size = 0
    for item in slices:
        item_size = len(item.text)
        if current and current_size + item_size > max_context_chars:
            chunks.append(tuple(current))
            current = []
            current_size = 0
        current.append(item)
        current_size += item_size
    if current:
        chunks.append(tuple(current))
    return tuple(chunks)


def _slice_segment(segment: Segment, max_context_chars: int) -> tuple[SegmentSlice, ...]:
    return tuple(
        SegmentSlice(
            segment_id=str(segment.id),
            start_ms=segment.start_ms,
            end_ms=segment.end_ms,
            local_speaker_id=segment.local_speaker_id,
            part_index=part_index,
            text=segment.text[offset : offset + max_context_chars],
        )
        for part_index, offset in enumerate(range(0, len(segment.text), max_context_chars))
    )
