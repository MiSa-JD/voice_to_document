from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from pathlib import Path

from app.config import Settings
from app.media import normalized_audio
from app.model_runtime import runtime_report
from app.transcription import (
    TranscriptionResult,
    WhisperXAdapter,
    WhisperXAdapterError,
    WhisperXConfig,
)


class GpuMemoryMonitor:
    def __init__(self) -> None:
        self.maximum_mb: int | None = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def __enter__(self) -> GpuMemoryMonitor:
        self._sample()
        self._thread.start()
        return self

    def __exit__(self, *_args: object) -> None:
        self._stop.set()
        self._thread.join(timeout=3)
        self._sample()

    def _run(self) -> None:
        while not self._stop.wait(0.25):
            self._sample()

    def _sample(self) -> None:
        current = _gpu_memory_mb()
        if current is not None:
            self.maximum_mb = max(self.maximum_mb or 0, current)


def run_transcription_smoke(settings: Settings, source: Path) -> dict[str, object]:
    adapter = WhisperXAdapter(
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
    cache_before = _directory_size(settings.model_cache_root)
    started = time.monotonic()
    with GpuMemoryMonitor() as memory_monitor, normalized_audio(source) as normalized:
        result = adapter.transcribe(normalized)
    elapsed_seconds = time.monotonic() - started
    return public_smoke_report(
        runtime=runtime_report(),
        result=result,
        cache_bytes_before=cache_before,
        cache_bytes_after=_directory_size(settings.model_cache_root),
        elapsed_seconds=elapsed_seconds,
        max_observed_gpu_memory_mb=memory_monitor.maximum_mb,
    )


def public_smoke_report(
    *,
    runtime: dict[str, object],
    result: TranscriptionResult,
    cache_bytes_before: int,
    cache_bytes_after: int,
    elapsed_seconds: float,
    max_observed_gpu_memory_mb: int | None,
) -> dict[str, object]:
    return {
        "status": "complete",
        "runtime": runtime,
        "model_fingerprint": result.model_fingerprint.as_dict(),
        "language": result.language,
        "segment_count": len(result.segments),
        "cache_bytes_before": cache_bytes_before,
        "cache_bytes_after": cache_bytes_after,
        "elapsed_seconds": round(elapsed_seconds, 3),
        "max_observed_gpu_memory_mb": max_observed_gpu_memory_mb,
    }


def _directory_size(root: Path) -> int:
    total = 0
    for path in root.rglob("*"):
        try:
            if path.is_file():
                total += path.stat().st_size
        except OSError:
            continue
    return total


def _gpu_memory_mb() -> int | None:
    try:
        completed = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=memory.used",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=2,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return None
    try:
        values = [int(line.strip()) for line in completed.stdout.splitlines() if line.strip()]
    except ValueError:
        return None
    return max(values) if values else None


def main() -> None:
    try:
        settings = Settings()  # type: ignore[call-arg]
        source = Path(
            os.environ.get(
                "TRANSCRIPTION_SMOKE_SOURCE",
                "/app/backend/tests/fixtures/complete.m4a",
            )
        )
        report = run_transcription_smoke(settings, source)
    except WhisperXAdapterError as error:
        print(json.dumps({"status": "failed", "error_code": error.code}, sort_keys=True))
        raise SystemExit(1) from error
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
