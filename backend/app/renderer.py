from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path

from app.schema import Classification, Segment, Transcript

MARKDOWN_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class TranscriptArtifactPaths:
    json: Path
    markdown: Path


@dataclass(frozen=True)
class MarkdownTurn:
    start_ms: int
    end_ms: int
    speaker: str
    text: str


def with_classification(
    transcript: Transcript,
    classification: Classification,
) -> Transcript:
    return transcript.model_copy(update={"classification": classification}, deep=True)


def render_transcript_json(transcript: Transcript) -> bytes:
    if transcript.classification is None:
        raise ValueError("classified transcript is required")
    value = transcript.model_dump(mode="json")
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def render_transcript_markdown(transcript: Transcript) -> bytes:
    classification = transcript.classification
    if classification is None:
        raise ValueError("classified transcript is required")
    lines = [
        f"# Transcript {transcript.recording_id}",
        "",
        f"- Recording ID: `{transcript.recording_id}`",
        f"- Revision: {transcript.revision}",
        f"- Category: {classification.category}",
        f"- Confidence: {classification.confidence:.4f}",
        f"- Reason: {classification.reason}",
        "",
        "## Transcript",
        "",
    ]
    for turn in merge_adjacent_speaker_turns(transcript.segments):
        lines.extend(
            [
                f"**[{format_timestamp(turn.start_ms)}–{format_timestamp(turn.end_ms)}] "
                f"{turn.speaker}**",
                "",
                turn.text,
                "",
            ]
        )
    return ("\n".join(lines).rstrip() + "\n").encode()


def transcript_artifact_paths(recording_id: str) -> TranscriptArtifactPaths:
    normalized = str(uuid.UUID(recording_id))
    if normalized != recording_id:
        raise ValueError("recording_id must be a canonical UUID")
    base = Path(normalized)
    return TranscriptArtifactPaths(base / "transcript.json", base / "transcript.md")


def merge_adjacent_speaker_turns(segments: list[Segment]) -> tuple[MarkdownTurn, ...]:
    turns: list[MarkdownTurn] = []
    previous_key: tuple[str, str] | None = None
    for segment in segments:
        key = _merge_key(segment)
        speaker = _speaker_label(segment)
        if turns and key is not None and key == previous_key:
            previous = turns[-1]
            turns[-1] = MarkdownTurn(
                start_ms=previous.start_ms,
                end_ms=segment.end_ms,
                speaker=previous.speaker,
                text=f"{previous.text} {segment.text}",
            )
        else:
            turns.append(
                MarkdownTurn(
                    start_ms=segment.start_ms,
                    end_ms=segment.end_ms,
                    speaker=speaker,
                    text=segment.text,
                )
            )
        previous_key = key
    return tuple(turns)


def format_timestamp(milliseconds: int) -> str:
    if milliseconds < 0:
        raise ValueError("timestamp must not be negative")
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1_000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{millis:03d}"


def _merge_key(segment: Segment) -> tuple[str, str] | None:
    if segment.local_speaker_id is None:
        return None
    overlap = ",".join(segment.overlapping_speaker_ids)
    return segment.assignment_status, f"{segment.local_speaker_id}:{overlap}"


def _speaker_label(segment: Segment) -> str:
    if segment.assignment_status == "unassigned" or segment.local_speaker_id is None:
        return "UNASSIGNED"
    if segment.assignment_status == "overlap":
        return " + ".join(segment.overlapping_speaker_ids)
    return segment.local_speaker_id
