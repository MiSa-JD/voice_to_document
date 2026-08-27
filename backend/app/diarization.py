from __future__ import annotations

import math
import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from enum import StrEnum
from importlib import import_module, metadata
from pathlib import Path
from typing import Protocol, cast

from pydantic import SecretStr

from app.alignment import AlignedSegment
from app.speech_failures import is_model_access_denied, is_model_download_failure
from app.transcription import _is_out_of_memory


class DiarizationErrorCode(StrEnum):
    MODEL_OOM = "MODEL_OOM"
    MODEL_ACCESS_DENIED = "MODEL_ACCESS_DENIED"
    MODEL_DOWNLOAD_FAILED = "MODEL_DOWNLOAD_FAILED"
    MODEL_LOAD_FAILED = "MODEL_LOAD_FAILED"
    DIARIZATION_FAILED = "DIARIZATION_FAILED"
    INVALID_RESPONSE = "INVALID_RESPONSE"


class WhisperXDiarizationError(RuntimeError):
    def __init__(self, code: DiarizationErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


class AssignmentStatus(StrEnum):
    ASSIGNED = "assigned"
    OVERLAP = "overlap"
    UNASSIGNED = "unassigned"


@dataclass(frozen=True)
class DiarizationConfig:
    model: str = "pyannote/speaker-diarization-community-1"
    device: str = "cuda"
    model_cache_root: Path = Path("/models")
    min_speakers: int | None = None
    max_speakers: int | None = None

    def __post_init__(self) -> None:
        if not self.model.strip():
            raise ValueError("model must not be empty")
        if not self.device.strip():
            raise ValueError("device must not be empty")
        for name in ("min_speakers", "max_speakers"):
            value = getattr(self, name)
            if value is not None and value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if (
            self.min_speakers is not None
            and self.max_speakers is not None
            and self.min_speakers > self.max_speakers
        ):
            raise ValueError("min_speakers must not exceed max_speakers")
        if not self.model_cache_root.is_absolute():
            raise ValueError("model_cache_root must be an absolute path")
        try:
            resolved_cache = self.model_cache_root.resolve(strict=True)
        except FileNotFoundError as error:
            raise ValueError("model_cache_root does not exist") from error
        if not resolved_cache.is_dir():
            raise ValueError("model_cache_root must be a directory")
        if not os.access(resolved_cache, os.W_OK | os.X_OK):
            raise ValueError("model_cache_root must be writable")
        object.__setattr__(self, "model_cache_root", resolved_cache)


@dataclass(frozen=True)
class DiarizationTurn:
    start: float
    end: float
    speaker_id: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class SegmentSpeakerAssignment:
    segment_index: int
    local_speaker_id: str | None
    status: AssignmentStatus
    overlapping_speaker_ids: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "segment_index": self.segment_index,
            "local_speaker_id": self.local_speaker_id,
            "status": self.status,
            "overlapping_speaker_ids": list(self.overlapping_speaker_ids),
        }


@dataclass(frozen=True)
class DiarizationFingerprint:
    whisperx_version: str
    pyannote_audio_version: str
    model: str
    device: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class DiarizationResult:
    turns: tuple[DiarizationTurn, ...]
    assignments: tuple[SegmentSpeakerAssignment, ...]
    speaker_ids: tuple[str, ...]
    model_fingerprint: DiarizationFingerprint


class WhisperXDiarizationModel(Protocol):
    def __call__(
        self,
        audio: str,
        *,
        num_speakers: int | None = None,
        min_speakers: int | None = None,
        max_speakers: int | None = None,
        return_embeddings: bool = False,
    ) -> object: ...


class WhisperXDiarizationPipelineFactory(Protocol):
    def __call__(
        self,
        model_name: str,
        token: str | None,
        device: str,
        cache_dir: str,
    ) -> WhisperXDiarizationModel: ...


class WhisperXDiarizationRuntime(Protocol):
    DiarizationPipeline: WhisperXDiarizationPipelineFactory


def _load_whisperx_diarization_runtime() -> WhisperXDiarizationRuntime:
    return cast(
        WhisperXDiarizationRuntime,
        cast(object, import_module("whisperx.diarize")),
    )


class WhisperXDiarizationAdapter:
    def __init__(
        self,
        config: DiarizationConfig,
        *,
        hf_token: SecretStr | None = None,
        runtime_loader: Callable[[], WhisperXDiarizationRuntime] = (
            _load_whisperx_diarization_runtime
        ),
        version_getter: Callable[[str], str] = metadata.version,
    ) -> None:
        self._config = config
        self._hf_token = hf_token
        self._runtime_loader = runtime_loader
        self._version_getter = version_getter
        self._pipeline: WhisperXDiarizationModel | None = None
        self._whisperx_version: str | None = None
        self._pyannote_audio_version: str | None = None

    def diarize(
        self,
        normalized_wav: Path,
        segments: Sequence[AlignedSegment],
        *,
        audio_duration: float,
    ) -> DiarizationResult:
        duration = _positive_finite(audio_duration)
        if duration is None:
            raise _invalid_response()
        pipeline = self._get_pipeline()
        try:
            raw_result = pipeline(
                str(normalized_wav),
                min_speakers=self._config.min_speakers,
                max_speakers=self._config.max_speakers,
                return_embeddings=False,
            )
        except Exception as error:
            if _is_out_of_memory(error):
                raise WhisperXDiarizationError(
                    DiarizationErrorCode.MODEL_OOM,
                    "WhisperX ran out of memory during diarization",
                ) from error
            if is_model_access_denied(error):
                raise WhisperXDiarizationError(
                    DiarizationErrorCode.MODEL_ACCESS_DENIED,
                    "The diarization model could not be accessed with the configured token",
                ) from error
            raise WhisperXDiarizationError(
                DiarizationErrorCode.DIARIZATION_FAILED,
                "WhisperX diarization could not be completed",
            ) from error

        turns = _normalize_turns(raw_result, duration)
        assignments = tuple(
            _assign_segment(index, segment, turns) for index, segment in enumerate(segments)
        )
        return DiarizationResult(
            turns=turns,
            assignments=assignments,
            speaker_ids=tuple(dict.fromkeys(turn.speaker_id for turn in turns)),
            model_fingerprint=self._fingerprint(),
        )

    def _get_pipeline(self) -> WhisperXDiarizationModel:
        if self._pipeline is not None:
            return self._pipeline
        try:
            runtime = self._runtime_loader()
            whisperx_version = self._version_getter("whisperx")
            pyannote_audio_version = self._version_getter("pyannote.audio")
            if not whisperx_version.strip() or not pyannote_audio_version.strip():
                raise ValueError("speech package version is empty")
            pipeline = runtime.DiarizationPipeline(
                self._config.model,
                (self._hf_token.get_secret_value() if self._hf_token is not None else None),
                self._config.device,
                str(self._config.model_cache_root),
            )
        except Exception as error:
            if _is_out_of_memory(error):
                raise WhisperXDiarizationError(
                    DiarizationErrorCode.MODEL_OOM,
                    "WhisperX ran out of memory while loading the diarization model",
                ) from error
            if is_model_access_denied(error):
                raise WhisperXDiarizationError(
                    DiarizationErrorCode.MODEL_ACCESS_DENIED,
                    "The diarization model could not be accessed with the configured token",
                ) from error
            if is_model_download_failure(error):
                raise WhisperXDiarizationError(
                    DiarizationErrorCode.MODEL_DOWNLOAD_FAILED,
                    "The diarization model could not be downloaded",
                ) from error
            raise WhisperXDiarizationError(
                DiarizationErrorCode.MODEL_LOAD_FAILED,
                "WhisperX diarization model could not be loaded",
            ) from error
        self._pipeline = pipeline
        self._whisperx_version = whisperx_version
        self._pyannote_audio_version = pyannote_audio_version
        return pipeline

    def _fingerprint(self) -> DiarizationFingerprint:
        assert self._whisperx_version is not None
        assert self._pyannote_audio_version is not None
        return DiarizationFingerprint(
            whisperx_version=self._whisperx_version,
            pyannote_audio_version=self._pyannote_audio_version,
            model=self._config.model,
            device=self._config.device,
        )


def _normalize_turns(raw_result: object, audio_duration: float) -> tuple[DiarizationTurn, ...]:
    records = _records(raw_result)
    raw_turns: list[tuple[float, float, str]] = []
    for record in records:
        start = _finite_number(record.get("start"))
        end = _finite_number(record.get("end"))
        speaker = record.get("speaker")
        if (
            start is None
            or end is None
            or end <= start
            or not isinstance(speaker, str)
            or not speaker.strip()
        ):
            raise _invalid_response()
        bounded_start = min(max(start, 0.0), audio_duration)
        bounded_end = min(max(end, bounded_start), audio_duration)
        if bounded_end > bounded_start:
            raw_turns.append((bounded_start, bounded_end, speaker.strip()))

    raw_turns.sort(key=lambda item: (item[0], item[1], item[2]))
    speaker_map: dict[str, str] = {}
    turns: list[DiarizationTurn] = []
    for start, end, raw_speaker in raw_turns:
        speaker_id = speaker_map.setdefault(raw_speaker, f"SPEAKER_{len(speaker_map):02d}")
        turns.append(DiarizationTurn(start=start, end=end, speaker_id=speaker_id))
    return tuple(turns)


def _records(raw_result: object) -> Sequence[Mapping[object, object]]:
    if isinstance(raw_result, list):
        records: object = raw_result
    else:
        to_dict = getattr(raw_result, "to_dict", None)
        if not callable(to_dict):
            raise _invalid_response()
        try:
            records = cast(Callable[..., object], to_dict)(orient="records")
        except Exception as error:
            raise _invalid_response() from error
    if not isinstance(records, list) or not all(isinstance(item, Mapping) for item in records):
        raise _invalid_response()
    return cast(Sequence[Mapping[object, object]], records)


def _assign_segment(
    index: int,
    segment: AlignedSegment,
    turns: Sequence[DiarizationTurn],
) -> SegmentSpeakerAssignment:
    intersections: list[tuple[DiarizationTurn, float, float, float]] = []
    for turn in turns:
        start = max(segment.start, turn.start)
        end = min(segment.end, turn.end)
        if end > start:
            intersections.append((turn, start, end, end - start))
    if not intersections:
        return SegmentSpeakerAssignment(
            segment_index=index,
            local_speaker_id=None,
            status=AssignmentStatus.UNASSIGNED,
        )

    totals: dict[str, float] = {}
    first_starts: dict[str, float] = {}
    for turn, start, _, duration in intersections:
        totals[turn.speaker_id] = totals.get(turn.speaker_id, 0.0) + duration
        first_starts[turn.speaker_id] = min(
            first_starts.get(turn.speaker_id, start),
            start,
        )
    primary = min(
        totals,
        key=lambda speaker_id: (-totals[speaker_id], first_starts[speaker_id], speaker_id),
    )
    overlapping: set[str] = set()
    for left_index, (left, left_start, left_end, _) in enumerate(intersections):
        for right, right_start, right_end, _ in intersections[left_index + 1 :]:
            if left.speaker_id == right.speaker_id:
                continue
            if min(left_end, right_end) > max(left_start, right_start):
                overlapping.update((left.speaker_id, right.speaker_id))

    overlap_ids = tuple(sorted(overlapping))
    return SegmentSpeakerAssignment(
        segment_index=index,
        local_speaker_id=primary,
        status=(AssignmentStatus.OVERLAP if overlap_ids else AssignmentStatus.ASSIGNED),
        overlapping_speaker_ids=overlap_ids,
    )


def _finite_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _positive_finite(value: object) -> float | None:
    number = _finite_number(value)
    return number if number is not None and number > 0 else None


def _invalid_response() -> WhisperXDiarizationError:
    return WhisperXDiarizationError(
        DiarizationErrorCode.INVALID_RESPONSE,
        "WhisperX returned an invalid diarization response",
    )
