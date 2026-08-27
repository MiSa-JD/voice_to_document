from __future__ import annotations

import math
import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from enum import StrEnum
from importlib import import_module, metadata
from pathlib import Path
from typing import Protocol, cast

from app.speech_failures import is_model_access_denied, is_model_download_failure
from app.transcription import TranscriptionSegment, _is_out_of_memory


class AlignmentErrorCode(StrEnum):
    MODEL_OOM = "MODEL_OOM"
    MODEL_ACCESS_DENIED = "MODEL_ACCESS_DENIED"
    MODEL_DOWNLOAD_FAILED = "MODEL_DOWNLOAD_FAILED"
    MODEL_LOAD_FAILED = "MODEL_LOAD_FAILED"
    ALIGNMENT_FAILED = "ALIGNMENT_FAILED"
    UNSUPPORTED_LANGUAGE = "UNSUPPORTED_LANGUAGE"
    INVALID_RESPONSE = "INVALID_RESPONSE"


class WhisperXAlignmentError(RuntimeError):
    def __init__(self, code: AlignmentErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class AlignmentConfig:
    device: str = "cuda"
    model_cache_root: Path = Path("/models")
    interpolate_method: str = "nearest"

    def __post_init__(self) -> None:
        if not self.device.strip():
            raise ValueError("device must not be empty")
        if not self.interpolate_method.strip():
            raise ValueError("interpolate_method must not be empty")
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
class AlignedWord:
    word: str
    start: float | None = None
    end: float | None = None
    score: float | None = None

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class AlignedSegment:
    start: float
    end: float
    text: str
    words: tuple[AlignedWord, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "start": self.start,
            "end": self.end,
            "text": self.text,
            "words": [word.as_dict() for word in self.words],
        }


@dataclass(frozen=True)
class AlignmentFingerprint:
    whisperx_version: str
    device: str
    interpolate_method: str
    language: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class AlignmentResult:
    language: str
    segments: tuple[AlignedSegment, ...]
    word_segments: tuple[AlignedWord, ...]
    model_fingerprint: AlignmentFingerprint


class WhisperXAlignmentRuntime(Protocol):
    def load_align_model(
        self,
        language_code: str,
        device: str,
        *,
        model_name: str | None = None,
        model_dir: str | None = None,
    ) -> tuple[object, object]: ...

    def align(
        self,
        transcript: list[dict[str, object]],
        model: object,
        align_model_metadata: object,
        audio: object,
        device: str,
        *,
        interpolate_method: str = "nearest",
        return_char_alignments: bool = False,
        print_progress: bool = False,
    ) -> object: ...

    def load_audio(self, file: str) -> object: ...


def _load_whisperx_alignment_runtime() -> WhisperXAlignmentRuntime:
    return cast(WhisperXAlignmentRuntime, cast(object, import_module("whisperx")))


class WhisperXAlignmentAdapter:
    def __init__(
        self,
        config: AlignmentConfig,
        *,
        runtime_loader: Callable[[], WhisperXAlignmentRuntime] = (_load_whisperx_alignment_runtime),
        version_getter: Callable[[str], str] = metadata.version,
    ) -> None:
        self._config = config
        self._runtime_loader = runtime_loader
        self._version_getter = version_getter
        self._runtime: WhisperXAlignmentRuntime | None = None
        self._align_models: dict[str, tuple[object, object]] = {}
        self._whisperx_version: str | None = None

    def align(
        self,
        normalized_wav: Path,
        segments: Sequence[TranscriptionSegment],
        language: str,
        *,
        audio_duration: float,
    ) -> AlignmentResult:
        normalized_language = language.strip().lower()
        if not normalized_language:
            raise WhisperXAlignmentError(
                AlignmentErrorCode.INVALID_RESPONSE,
                "Language code must not be empty for alignment",
            )
        duration = _positive_finite(audio_duration)
        if duration is None:
            raise WhisperXAlignmentError(
                AlignmentErrorCode.INVALID_RESPONSE,
                "Audio duration must be a positive finite number",
            )

        transcript = [
            {"start": segment.start, "end": segment.end, "text": segment.text}
            for segment in segments
        ]
        align_model, align_metadata = self._get_align_model(normalized_language)
        assert self._runtime is not None
        try:
            audio = self._runtime.load_audio(str(normalized_wav))
            raw_result = self._runtime.align(
                transcript,
                align_model,
                align_metadata,
                audio,
                self._config.device,
                interpolate_method=self._config.interpolate_method,
                return_char_alignments=False,
                print_progress=False,
            )
        except Exception as error:
            if _is_out_of_memory(error):
                raise WhisperXAlignmentError(
                    AlignmentErrorCode.MODEL_OOM,
                    "WhisperX ran out of memory during alignment",
                ) from error
            raise WhisperXAlignmentError(
                AlignmentErrorCode.ALIGNMENT_FAILED,
                "WhisperX alignment could not be completed",
            ) from error

        aligned_segments = _normalize_alignment_result(raw_result, segments, duration)
        return AlignmentResult(
            language=normalized_language,
            segments=aligned_segments,
            word_segments=tuple(word for segment in aligned_segments for word in segment.words),
            model_fingerprint=self._fingerprint(normalized_language),
        )

    def _get_align_model(self, language: str) -> tuple[object, object]:
        cached = self._align_models.get(language)
        if cached is not None:
            return cached
        runtime = self._ensure_runtime()
        try:
            model = runtime.load_align_model(
                language_code=language,
                device=self._config.device,
                model_dir=str(self._config.model_cache_root),
            )
        except Exception as error:
            if _is_out_of_memory(error):
                raise WhisperXAlignmentError(
                    AlignmentErrorCode.MODEL_OOM,
                    "WhisperX ran out of memory while loading the alignment model",
                ) from error
            if _is_unsupported_language(error):
                raise WhisperXAlignmentError(
                    AlignmentErrorCode.UNSUPPORTED_LANGUAGE,
                    "WhisperX has no alignment model for the detected language",
                ) from error
            if is_model_access_denied(error):
                raise WhisperXAlignmentError(
                    AlignmentErrorCode.MODEL_ACCESS_DENIED,
                    "The alignment model could not be accessed",
                ) from error
            if is_model_download_failure(error):
                raise WhisperXAlignmentError(
                    AlignmentErrorCode.MODEL_DOWNLOAD_FAILED,
                    "The alignment model could not be downloaded",
                ) from error
            raise WhisperXAlignmentError(
                AlignmentErrorCode.MODEL_LOAD_FAILED,
                "WhisperX alignment model could not be loaded",
            ) from error
        self._align_models[language] = model
        return model

    def _ensure_runtime(self) -> WhisperXAlignmentRuntime:
        if self._runtime is not None:
            return self._runtime
        try:
            runtime = self._runtime_loader()
            version = self._version_getter("whisperx")
            if not version.strip():
                raise ValueError("WhisperX package version is empty")
        except Exception as error:
            if _is_out_of_memory(error):
                raise WhisperXAlignmentError(
                    AlignmentErrorCode.MODEL_OOM,
                    "WhisperX ran out of memory while initializing alignment",
                ) from error
            raise WhisperXAlignmentError(
                AlignmentErrorCode.MODEL_LOAD_FAILED,
                "WhisperX alignment runtime could not be loaded",
            ) from error
        self._runtime = runtime
        self._whisperx_version = version
        return runtime

    def _fingerprint(self, language: str) -> AlignmentFingerprint:
        if self._whisperx_version is None:
            self._ensure_runtime()
        assert self._whisperx_version is not None
        return AlignmentFingerprint(
            whisperx_version=self._whisperx_version,
            device=self._config.device,
            interpolate_method=self._config.interpolate_method,
            language=language,
        )


def _normalize_alignment_result(
    raw_result: object,
    fallback_segments: Sequence[TranscriptionSegment],
    audio_duration: float,
) -> tuple[AlignedSegment, ...]:
    if not isinstance(raw_result, Mapping):
        raise _invalid_response()
    raw_segments = raw_result.get("segments")
    if not isinstance(raw_segments, list):
        raise _invalid_response()

    normalized: list[AlignedSegment] = []
    if len(raw_segments) <= len(fallback_segments):
        for index, fallback in enumerate(fallback_segments):
            raw_segment: object = raw_segments[index] if index < len(raw_segments) else {}
            normalized.append(_normalize_segment(raw_segment, fallback, audio_duration))
        return tuple(normalized)

    for raw_segment in raw_segments:
        normalized.append(_normalize_segment(raw_segment, None, audio_duration))
    return tuple(normalized)


def _normalize_segment(
    raw_segment: object,
    fallback: TranscriptionSegment | None,
    audio_duration: float,
) -> AlignedSegment:
    if not isinstance(raw_segment, Mapping):
        raise _invalid_response()
    start, end = _segment_bounds(raw_segment, fallback, audio_duration)
    raw_text = raw_segment.get("text")
    if isinstance(raw_text, str):
        text = raw_text
    elif fallback is not None:
        text = fallback.text
    else:
        raise _invalid_response()
    raw_words = raw_segment.get("words", [])
    if not isinstance(raw_words, list):
        raise _invalid_response()
    words = tuple(_normalize_word(word, audio_duration) for word in raw_words)
    return AlignedSegment(start=start, end=end, text=text, words=words)


def _segment_bounds(
    raw_segment: Mapping[object, object],
    fallback: TranscriptionSegment | None,
    audio_duration: float,
) -> tuple[float, float]:
    start = _finite_number(raw_segment.get("start"))
    end = _finite_number(raw_segment.get("end"))
    if start is None or end is None or end < start:
        if fallback is None:
            raise _invalid_response()
        start, end = fallback.start, fallback.end
    return _clamp_bounds(start, end, audio_duration)


def _normalize_word(raw_word: object, audio_duration: float) -> AlignedWord:
    if not isinstance(raw_word, Mapping):
        raise _invalid_response()
    word = raw_word.get("word")
    if not isinstance(word, str) or not word:
        raise _invalid_response()
    start = _finite_number(raw_word.get("start"))
    end = _finite_number(raw_word.get("end"))
    if start is None or end is None or end < start:
        start, end = None, None
    else:
        start, end = _clamp_bounds(start, end, audio_duration)
    score = _finite_number(raw_word.get("score"))
    if score is not None:
        score = min(max(score, 0.0), 1.0)
    return AlignedWord(word=word, start=start, end=end, score=score)


def _clamp_bounds(start: float, end: float, audio_duration: float) -> tuple[float, float]:
    bounded_start = min(max(start, 0.0), audio_duration)
    bounded_end = min(max(end, bounded_start), audio_duration)
    return bounded_start, bounded_end


def _finite_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _positive_finite(value: object) -> float | None:
    number = _finite_number(value)
    return number if number is not None and number > 0 else None


def _is_unsupported_language(error: BaseException) -> bool:
    message = str(error).casefold()
    return (
        "unsupported language" in message
        or "no alignment model" in message
        or "language is not supported" in message
    )


def _invalid_response() -> WhisperXAlignmentError:
    return WhisperXAlignmentError(
        AlignmentErrorCode.INVALID_RESPONSE,
        "WhisperX returned an invalid alignment response",
    )
