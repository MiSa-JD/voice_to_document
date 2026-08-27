from __future__ import annotations

import json

from app.alignment import (
    AlignedSegment,
    AlignedWord,
    AlignmentFingerprint,
    AlignmentResult,
)
from app.alignment_smoke import public_smoke_report
from app.transcription import ModelFingerprint


def test_public_report_omits_transcript_token_and_source_path() -> None:
    result = AlignmentResult(
        language="ko",
        segments=(
            AlignedSegment(
                start=0,
                end=1,
                text="절대 출력하면 안 되는 전문",
                words=(AlignedWord("비밀단어", 0, 1, 0.9),),
            ),
        ),
        word_segments=(AlignedWord("비밀단어", 0, 1, 0.9),),
        model_fingerprint=AlignmentFingerprint(
            whisperx_version="3.8.6",
            device="cuda",
            interpolate_method="nearest",
            language="ko",
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
        result=result,
        cache_bytes_before=10,
        cache_bytes_after=20,
        elapsed_seconds=1.23456,
        max_observed_gpu_memory_mb=1024,
    )
    rendered = json.dumps(report, ensure_ascii=False, sort_keys=True)

    assert report["segment_count"] == 1
    assert report["word_count"] == 1
    assert report["segments_with_word_timestamps"] == 1
    assert report["elapsed_seconds"] == 1.235
    assert "절대 출력하면 안 되는 전문" not in rendered
    assert "비밀단어" not in rendered
    assert "HF_TOKEN" not in rendered
    assert "hf_private_test_value" not in rendered
    assert "/private/source.m4a" not in rendered
