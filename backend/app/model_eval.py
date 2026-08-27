from __future__ import annotations

import gc
import json
import logging
import os
import shutil
import subprocess
import tempfile
import time
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from importlib import import_module
from pathlib import Path
from typing import Any, cast

from app.config import Settings
from app.db import connect
from app.ingest import ingest_file
from app.model_runtime import runtime_report
from app.real_pipeline import RealSpeechPipelineHandler
from app.runtime import process_one_job
from app.schema import Transcript
from app.transcription_smoke import GpuMemoryMonitor

SAMPLE_FILES = {
    "single-speaker": "single-speaker.m4a",
    "multi-speaker": "multi-speaker.m4a",
    "silence": "silence.m4a",
}
DEFAULT_BATCH_SIZES = (4, 8, 16)
GPU_MEMORY_LIMIT_RATIO = 0.9
NEAR_FASTEST_RATIO = 1.1


class ModelEvaluationError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class SampleEvaluation:
    role: str
    duration_ms: int
    segment_count: int
    speaker_count: int
    assigned_segment_count: int
    overlap_segment_count: int
    unassigned_segment_count: int
    elapsed_seconds: float

    def public_report(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class BatchEvaluation:
    batch_size: int
    elapsed_seconds: float
    max_observed_gpu_memory_mb: int
    model_fingerprints: dict[str, dict[str, object]]
    samples: tuple[SampleEvaluation, ...]

    def public_report(self) -> dict[str, object]:
        return {
            "status": "complete",
            "batch_size": self.batch_size,
            "elapsed_seconds": round(self.elapsed_seconds, 3),
            "max_observed_gpu_memory_mb": self.max_observed_gpu_memory_mb,
            "model_fingerprints": self.model_fingerprints,
            "samples": [sample.public_report() for sample in self.samples],
        }


def run_model_evaluation(
    evaluation_root: Path,
    *,
    batch_sizes: Sequence[int] = DEFAULT_BATCH_SIZES,
) -> dict[str, object]:
    sources = evaluation_sources(evaluation_root)
    candidates = normalized_batch_sizes(batch_sizes)
    if not os.environ.get("HF_TOKEN", "").strip():
        raise ModelEvaluationError("MODEL_ACCESS_CONFIG_MISSING")
    runtime = runtime_report()
    if runtime.get("status") != "ready":
        raise ModelEvaluationError("GPU_RUNTIME_UNAVAILABLE")
    total_gpu_memory_mb = gpu_total_memory_mb()
    if total_gpu_memory_mb is None:
        raise ModelEvaluationError("GPU_MEMORY_UNAVAILABLE")

    completed: list[BatchEvaluation] = []
    reports: list[dict[str, object]] = []
    for batch_size in candidates:
        try:
            candidate = evaluate_batch(sources, batch_size)
        except ModelEvaluationError as error:
            if error.code != "MODEL_OOM":
                raise
            reports.append(
                {
                    "status": "failed",
                    "batch_size": batch_size,
                    "error_code": error.code,
                }
            )
            break
        completed.append(candidate)
        reports.append(candidate.public_report())
        release_gpu_memory()

    selected = select_batch_size(completed, total_gpu_memory_mb)
    return {
        "status": "complete",
        "runtime": runtime,
        "gpu_total_memory_mb": total_gpu_memory_mb,
        "gpu_memory_limit_percent": round(GPU_MEMORY_LIMIT_RATIO * 100),
        "near_fastest_percent": round((NEAR_FASTEST_RATIO - 1) * 100),
        "selected_batch_size": selected,
        "candidates": reports,
    }


def evaluation_sources(root: Path) -> dict[str, Path]:
    try:
        resolved = root.resolve(strict=True)
    except OSError as error:
        raise ModelEvaluationError("EVALUATION_INPUT_MISSING") from error
    if not resolved.is_dir():
        raise ModelEvaluationError("EVALUATION_INPUT_MISSING")
    sources: dict[str, Path] = {}
    try:
        for role, name in SAMPLE_FILES.items():
            source = (resolved / name).resolve(strict=True)
            if not source.is_relative_to(resolved) or not source.is_file():
                raise ModelEvaluationError("EVALUATION_INPUT_MISSING")
            sources[role] = source
    except OSError as error:
        raise ModelEvaluationError("EVALUATION_INPUT_MISSING") from error
    if len(sources) != len(SAMPLE_FILES):
        raise ModelEvaluationError("EVALUATION_INPUT_MISSING")
    return sources


def normalized_batch_sizes(values: Sequence[int]) -> tuple[int, ...]:
    candidates = tuple(dict.fromkeys(values))
    if not candidates or any(value <= 0 for value in candidates):
        raise ModelEvaluationError("INVALID_BATCH_SIZES")
    return tuple(sorted(candidates))


def evaluate_batch(sources: Mapping[str, Path], batch_size: int) -> BatchEvaluation:
    with tempfile.TemporaryDirectory(prefix="voice-to-document-model-eval-") as temp_value:
        root = Path(temp_value)
        directories = {
            name: root / name for name in ("inbox", "transcripts", "speakers", "documents", "app")
        }
        for directory in directories.values():
            directory.mkdir()
        settings = evaluation_settings(directories, batch_size)
        handler = RealSpeechPipelineHandler(
            settings,
            logging.getLogger("model-eval"),
            continue_to_documents=False,
        )
        started = time.monotonic()
        samples: list[SampleEvaluation] = []
        fingerprints: dict[str, dict[str, object]] | None = None
        with GpuMemoryMonitor() as memory_monitor:
            for role in SAMPLE_FILES:
                source = sources[role]
                private_copy = directories["inbox"] / SAMPLE_FILES[role]
                shutil.copyfile(source, private_copy)
                sample_started = time.monotonic()
                registration = ingest_file(settings.database_path, private_copy)
                if not registration.created:
                    raise ModelEvaluationError("DUPLICATE_EVALUATION_INPUT")
                if not process_one_job(
                    settings.database_path, handler, logging.getLogger("model-eval")
                ):
                    raise ModelEvaluationError("EVALUATION_JOB_MISSING")
                sample, sample_fingerprints = inspect_sample(
                    settings,
                    registration.recording_id,
                    role,
                    time.monotonic() - sample_started,
                )
                samples.append(sample)
                if fingerprints is None:
                    fingerprints = sample_fingerprints
                elif fingerprints != sample_fingerprints:
                    raise ModelEvaluationError("MODEL_FINGERPRINT_MISMATCH")
        if memory_monitor.maximum_mb is None:
            raise ModelEvaluationError("GPU_MEMORY_UNAVAILABLE")
        if fingerprints is None:
            raise ModelEvaluationError("EVALUATION_INPUT_MISSING")
        return BatchEvaluation(
            batch_size=batch_size,
            elapsed_seconds=round(time.monotonic() - started, 3),
            max_observed_gpu_memory_mb=memory_monitor.maximum_mb,
            model_fingerprints=fingerprints,
            samples=tuple(samples),
        )


def evaluation_settings(directories: Mapping[str, Path], batch_size: int) -> Settings:
    values: dict[str, Any] = {
        "RECORDING_INPUT_DIR": directories["inbox"],
        "TRANSCRIPT_ROOT": directories["transcripts"],
        "SPEAKER_ROOT": directories["speakers"],
        "SUMMARY_ROOT": directories["documents"],
        "APP_DATA_DIR": directories["app"],
        "SERVICE_NAME": "worker",
        "SPEECH_MODE": "real",
        "DOCUMENT_MODE": "fake",
        "WHISPER_BATCH_SIZE": batch_size,
        "MODEL_CACHE_ROOT": os.environ.get("MODEL_CACHE_ROOT", "/models"),
        "HF_TOKEN": os.environ.get("HF_TOKEN", ""),
    }
    return Settings(**values)


def inspect_sample(
    settings: Settings,
    recording_id: str,
    role: str,
    elapsed_seconds: float,
) -> tuple[SampleEvaluation, dict[str, dict[str, object]]]:
    with connect(settings.database_path) as connection:
        recording = connection.execute(
            "SELECT duration_ms, status FROM recordings WHERE id = ?",
            (recording_id,),
        ).fetchone()
        job = connection.execute(
            "SELECT status, error_code FROM jobs WHERE recording_id = ?",
            (recording_id,),
        ).fetchone()
        artifact = connection.execute(
            """
            SELECT relative_path FROM artifacts
            WHERE recording_id = ? AND kind = 'transcript_json'
            """,
            (recording_id,),
        ).fetchone()
    if job is None or job["status"] != "succeeded":
        raise ModelEvaluationError(str(job["error_code"] if job is not None else "JOB_FAILED"))
    if recording is None or recording["status"] != "SPEAKER_REVIEW" or artifact is None:
        raise ModelEvaluationError("EVALUATION_RESULT_INCOMPLETE")

    artifact_path = (settings.transcript_root / str(artifact["relative_path"])).resolve()
    if not artifact_path.is_relative_to(settings.transcript_root.resolve()):
        raise ModelEvaluationError("INVALID_ARTIFACT_PATH")
    try:
        transcript = Transcript.model_validate_json(artifact_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ModelEvaluationError("INVALID_TRANSCRIPT_ARTIFACT") from error
    sample = summarize_transcript(
        role,
        int(recording["duration_ms"]),
        transcript,
        elapsed_seconds,
    )
    if transcript.model_fingerprints is None:
        raise ModelEvaluationError("MODEL_FINGERPRINT_MISSING")
    raw_fingerprints = transcript.model_fingerprints.model_dump(mode="json")
    fingerprints = {
        name: cast(dict[str, object], value) for name, value in raw_fingerprints.items()
    }
    return sample, fingerprints


def summarize_transcript(
    role: str,
    duration_ms: int,
    transcript: Transcript,
    elapsed_seconds: float,
) -> SampleEvaluation:
    if role not in SAMPLE_FILES or duration_ms <= 0 or not transcript.segments:
        raise ModelEvaluationError("EVALUATION_INVARIANT_FAILED")
    ordered = sorted(
        transcript.segments,
        key=lambda segment: (segment.start_ms, segment.end_ms, str(segment.id)),
    )
    if ordered != transcript.segments or any(
        segment.start_ms < 0 or segment.end_ms <= segment.start_ms or segment.end_ms > duration_ms
        for segment in transcript.segments
    ):
        raise ModelEvaluationError("EVALUATION_INVARIANT_FAILED")
    speaker_ids = {
        speaker_id
        for segment in transcript.segments
        for speaker_id in (
            ([segment.local_speaker_id] if segment.local_speaker_id is not None else [])
            + segment.overlapping_speaker_ids
        )
    }
    minimum_speakers = 2 if role == "multi-speaker" else 1
    if len(speaker_ids) < minimum_speakers:
        raise ModelEvaluationError("SPEAKER_COUNT_MISMATCH")
    return SampleEvaluation(
        role=role,
        duration_ms=duration_ms,
        segment_count=len(transcript.segments),
        speaker_count=len(speaker_ids),
        assigned_segment_count=sum(
            segment.assignment_status == "assigned" for segment in transcript.segments
        ),
        overlap_segment_count=sum(
            segment.assignment_status == "overlap" for segment in transcript.segments
        ),
        unassigned_segment_count=sum(
            segment.assignment_status == "unassigned" for segment in transcript.segments
        ),
        elapsed_seconds=round(elapsed_seconds, 3),
    )


def select_batch_size(candidates: Sequence[BatchEvaluation], total_gpu_memory_mb: int) -> int:
    limit = total_gpu_memory_mb * GPU_MEMORY_LIMIT_RATIO
    eligible = [
        candidate for candidate in candidates if candidate.max_observed_gpu_memory_mb <= limit
    ]
    if not eligible:
        raise ModelEvaluationError("NO_SAFE_BATCH_SIZE")
    fastest = min(candidate.elapsed_seconds for candidate in eligible)
    near_fastest = [
        candidate
        for candidate in eligible
        if candidate.elapsed_seconds <= fastest * NEAR_FASTEST_RATIO
    ]
    return min(candidate.batch_size for candidate in near_fastest)


def gpu_total_memory_mb() -> int | None:
    try:
        completed = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=memory.total",
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
    return min(values) if values else None


def release_gpu_memory() -> None:
    gc.collect()
    try:
        torch = cast(Any, import_module("torch"))
        torch.cuda.empty_cache()
    except Exception:
        return


def parse_batch_sizes(value: str) -> tuple[int, ...]:
    try:
        return normalized_batch_sizes(tuple(int(item.strip()) for item in value.split(",")))
    except ValueError as error:
        raise ModelEvaluationError("INVALID_BATCH_SIZES") from error


def main() -> None:
    try:
        report = run_model_evaluation(
            Path(os.environ.get("MODEL_EVAL_ROOT", "/evaluation")),
            batch_sizes=parse_batch_sizes(os.environ.get("MODEL_EVAL_BATCH_SIZES", "4,8,16")),
        )
    except ModelEvaluationError as error:
        print(json.dumps({"status": "failed", "error_code": error.code}, sort_keys=True))
        raise SystemExit(1) from None
    except Exception:
        print(json.dumps({"status": "failed", "error_code": "EVALUATION_FAILED"}, sort_keys=True))
        raise SystemExit(1) from None
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
