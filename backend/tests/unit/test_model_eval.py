from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from app.model_eval import (
    BatchEvaluation,
    ModelEvaluationError,
    SampleEvaluation,
    evaluation_sources,
    normalized_batch_sizes,
    select_batch_size,
    summarize_transcript,
)
from app.schema import Segment, SpeechModelFingerprints, Transcript


def transcript_with_speakers(*speaker_ids: str) -> Transcript:
    return Transcript(
        recording_id=uuid.uuid4(),
        content_sha256="a" * 64,
        revision=1,
        language="ko",
        needs_speaker_review=True,
        segments=[
            Segment(
                id=uuid.uuid4(),
                start_ms=index * 1000,
                end_ms=(index + 1) * 1000,
                local_speaker_id=speaker_id,
                text=f"private transcript {index}",
            )
            for index, speaker_id in enumerate(speaker_ids)
        ],
        model_fingerprints=SpeechModelFingerprints(
            transcription={"model": "large-v3"},
            alignment={"language": "ko"},
            diarization={"model": "community-1"},
        ),
    )


def candidate(batch_size: int, elapsed: float, memory: int) -> BatchEvaluation:
    return BatchEvaluation(
        batch_size=batch_size,
        elapsed_seconds=elapsed,
        max_observed_gpu_memory_mb=memory,
        model_fingerprints={"transcription": {"batch_size": batch_size}},
        samples=(
            SampleEvaluation(
                role="single-speaker",
                duration_ms=1000,
                segment_count=1,
                speaker_count=1,
                assigned_segment_count=1,
                overlap_segment_count=0,
                unassigned_segment_count=0,
                elapsed_seconds=elapsed,
            ),
        ),
    )


def test_requires_all_private_evaluation_inputs(tmp_path: Path) -> None:
    for name in ("single-speaker.m4a", "multi-speaker.m4a"):
        (tmp_path / name).write_bytes(b"private")

    with pytest.raises(ModelEvaluationError) as error:
        evaluation_sources(tmp_path)

    assert error.value.code == "EVALUATION_INPUT_MISSING"
    assert str(tmp_path) not in str(error.value)


def test_normalizes_batch_candidates() -> None:
    assert normalized_batch_sizes((16, 4, 8, 4)) == (4, 8, 16)

    with pytest.raises(ModelEvaluationError, match="INVALID_BATCH_SIZES"):
        normalized_batch_sizes((4, 0))


def test_validates_single_and_multiple_speaker_roles() -> None:
    single = summarize_transcript(
        "single-speaker", 2000, transcript_with_speakers("SPEAKER_00"), 1.2345
    )
    multiple = summarize_transcript(
        "multi-speaker",
        3000,
        transcript_with_speakers("SPEAKER_00", "SPEAKER_01"),
        2,
    )

    assert single.speaker_count == 1
    assert single.elapsed_seconds == 1.234
    assert multiple.speaker_count == 2


def test_rejects_wrong_speaker_count_for_role() -> None:
    with pytest.raises(ModelEvaluationError, match="SPEAKER_COUNT_MISMATCH"):
        summarize_transcript("multi-speaker", 2000, transcript_with_speakers("SPEAKER_00"), 1)


def test_records_single_speaker_oversegmentation_without_hiding_it() -> None:
    result = summarize_transcript(
        "single-speaker",
        2000,
        transcript_with_speakers("SPEAKER_00", "SPEAKER_01"),
        1,
    )

    assert result.speaker_count == 2


def test_selects_smallest_candidate_within_ten_percent_of_fastest() -> None:
    candidates = (
        candidate(4, 100, 4000),
        candidate(8, 92, 6000),
        candidate(16, 70, 11500),
    )

    assert select_batch_size(candidates, total_gpu_memory_mb=12000) == 4


def test_selects_larger_batch_when_improvement_exceeds_ten_percent() -> None:
    candidates = (
        candidate(4, 100, 4000),
        candidate(8, 80, 6000),
        candidate(16, 75, 8000),
    )

    assert select_batch_size(candidates, total_gpu_memory_mb=12000) == 8


def test_rejects_candidates_over_gpu_memory_limit() -> None:
    with pytest.raises(ModelEvaluationError, match="NO_SAFE_BATCH_SIZE"):
        select_batch_size((candidate(4, 10, 11000),), total_gpu_memory_mb=12000)


def test_public_report_excludes_transcript_and_paths() -> None:
    public_json = json.dumps(candidate(4, 10, 4000).public_report(), ensure_ascii=False)

    assert "private transcript" not in public_json
    assert ".m4a" not in public_json
    assert "/" not in public_json
