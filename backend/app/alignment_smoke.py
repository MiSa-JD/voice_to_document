from __future__ import annotations

import json
import os
import time
from pathlib import Path

from app.alignment import (
    AlignmentConfig,
    AlignmentResult,
    WhisperXAlignmentAdapter,
    WhisperXAlignmentError,
)
from app.config import Settings
from app.media import normalized_audio, probe_media
from app.model_runtime import runtime_report
from app.transcription import (
    ModelFingerprint,
    WhisperXAdapter,
    WhisperXAdapterError,
    WhisperXConfig,
)
from app.transcription_smoke import GpuMemoryMonitor, _directory_size


def run_alignment_smoke(settings: Settings, source: Path) -> dict[str, object]:
    transcription_adapter = WhisperXAdapter(
        WhisperXConfig(
            model=settings.whisper_model,
            device=settings.whisper_device,
            compute_type=settings.whisper_compute_type,
            language=settings.whisper_language,
            batch_size=settings.whisper_batch_size,
            model_cache_root=settings.model_cache_root,
        ),
        hf_token=settings.hf_token,
    )
    alignment_adapter = WhisperXAlignmentAdapter(
        AlignmentConfig(
            device=settings.whisper_device,
            model_cache_root=settings.model_cache_root,
        )
    )
    duration = probe_media(source).duration_ms / 1000
    cache_before = _directory_size(settings.model_cache_root)
    started = time.monotonic()
    with GpuMemoryMonitor() as memory_monitor, normalized_audio(source) as normalized:
        transcription = transcription_adapter.transcribe(normalized)
        alignment = alignment_adapter.align(
            normalized,
            transcription.segments,
            transcription.language,
            audio_duration=duration,
        )
    return public_smoke_report(
        runtime=runtime_report(),
        transcription_fingerprint=transcription.model_fingerprint,
        result=alignment,
        cache_bytes_before=cache_before,
        cache_bytes_after=_directory_size(settings.model_cache_root),
        elapsed_seconds=time.monotonic() - started,
        max_observed_gpu_memory_mb=memory_monitor.maximum_mb,
    )


def public_smoke_report(
    *,
    runtime: dict[str, object],
    transcription_fingerprint: ModelFingerprint,
    result: AlignmentResult,
    cache_bytes_before: int,
    cache_bytes_after: int,
    elapsed_seconds: float,
    max_observed_gpu_memory_mb: int | None,
) -> dict[str, object]:
    return {
        "status": "complete",
        "runtime": runtime,
        "transcription_fingerprint": transcription_fingerprint.as_dict(),
        "alignment_fingerprint": result.model_fingerprint.as_dict(),
        "language": result.language,
        "segment_count": len(result.segments),
        "word_count": len(result.word_segments),
        "segments_with_word_timestamps": sum(
            any(word.start is not None and word.end is not None for word in segment.words)
            for segment in result.segments
        ),
        "cache_bytes_before": cache_bytes_before,
        "cache_bytes_after": cache_bytes_after,
        "elapsed_seconds": round(elapsed_seconds, 3),
        "max_observed_gpu_memory_mb": max_observed_gpu_memory_mb,
    }


def main() -> None:
    try:
        settings = Settings()  # type: ignore[call-arg]
        source = Path(
            os.environ.get(
                "ALIGNMENT_SMOKE_SOURCE",
                "/app/backend/tests/fixtures/complete.m4a",
            )
        )
        report = run_alignment_smoke(settings, source)
    except (WhisperXAdapterError, WhisperXAlignmentError) as error:
        print(json.dumps({"status": "failed", "error_code": error.code}, sort_keys=True))
        raise SystemExit(1) from error
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
