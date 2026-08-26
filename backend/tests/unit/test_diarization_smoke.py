from __future__ import annotations

import json

from app.alignment import AlignmentFingerprint
from app.diarization import (
    AssignmentStatus,
    DiarizationFingerprint,
    DiarizationResult,
    DiarizationTurn,
    SegmentSpeakerAssignment,
)
from app.diarization_smoke import public_smoke_report
from app.transcription import ModelFingerprint


def test_public_report_omits_transcript_token_and_source_path() -> None:
    result = DiarizationResult(
        turns=(DiarizationTurn(0, 1, "SPEAKER_00"),),
        assignments=(
            SegmentSpeakerAssignment(0, "SPEAKER_00", AssignmentStatus.ASSIGNED),
            SegmentSpeakerAssignment(
                1,
                "SPEAKER_00",
                AssignmentStatus.OVERLAP,
                ("SPEAKER_00", "SPEAKER_01"),
            ),
            SegmentSpeakerAssignment(2, None, AssignmentStatus.UNASSIGNED),
        ),
        speaker_ids=("SPEAKER_00",),
        model_fingerprint=DiarizationFingerprint(
            whisperx_version="3.8.6",
            pyannote_audio_version="4.0.7",
            model="pyannote/speaker-diarization-community-1",
            device="cuda",
        ),
    )

    report = public_smoke_report(
        runtime={"status": "ready", "devices": ["Test GPU"]},
        transcription_fingerprint=ModelFingerprint(
            whisperx_version="3.8.6",
            model="large-v3",
            device="cuda",
            compute_type="float16",
            batch_size=4,
            language=None,
        ),
        alignment_fingerprint=AlignmentFingerprint(
            whisperx_version="3.8.6",
            device="cuda",
            interpolate_method="nearest",
            language="ko",
        ),
        result=result,
        cache_bytes_before=10,
        cache_bytes_after=20,
        elapsed_seconds=1.23456,
        max_observed_gpu_memory_mb=2048,
    )
    rendered = json.dumps(report, ensure_ascii=False, sort_keys=True)

    assert report["turn_count"] == 1
    assert report["speaker_count"] == 1
    assert report["segment_count"] == 3
    assert report["assigned_segment_count"] == 1
    assert report["overlap_segment_count"] == 1
    assert report["unassigned_segment_count"] == 1
    assert report["elapsed_seconds"] == 1.235
    assert "절대 출력하면 안 되는 전문" not in rendered
    assert "HF_TOKEN" not in rendered
    assert "hf_private_test_value" not in rendered
    assert "/private/source.m4a" not in rendered
