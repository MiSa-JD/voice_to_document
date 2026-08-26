from __future__ import annotations

import math
import os
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from enum import StrEnum
from importlib import import_module, metadata
from pathlib import Path
from typing import Protocol, cast

from pydantic import SecretStr

from app.speech_failures import is_model_access_denied, is_model_download_failure


class WhisperXErrorCode(StrEnum):
    MODEL_OOM = "MODEL_OOM"
    MODEL_ACCESS_DENIED = "MODEL_ACCESS_DENIED"
    MODEL_DOWNLOAD_FAILED = "MODEL_DOWNLOAD_FAILED"
    MODEL_LOAD_FAILED = "MODEL_LOAD_FAILED"
    TRANSCRIPTION_FAILED = "TRANSCRIPTION_FAILED"
    INVALID_RESPONSE = "INVALID_RESPONSE"


class WhisperXAdapterError(RuntimeError):
    def __init__(self, code: WhisperXErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class WhisperXConfig:
    model: str = "large-v3"
    device: str = "cuda"
    compute_type: str = "float16"
    language: str | None = None
    batch_size: int = 4
    model_cache_root: Path = Path("/models")

    def __post_init__(self) -> None:
        for name in ("model", "device", "compute_type"):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} must not be empty")
        if self.language is not None:
            normalized_language = self.language.strip() or None
            object.__setattr__(self, "language", normalized_language)
        if self.batch_size <= 0:
            raise ValueError("batch_size must be a positive integer")
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
class TranscriptionSegment:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class ModelFingerprint:
    whisperx_version: str
    model: str
    device: str
    compute_type: str
    batch_size: int
    language: str | None

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class TranscriptionResult:
    language: str
    segments: tuple[TranscriptionSegment, ...]
    model_fingerprint: ModelFingerprint


class WhisperXModel(Protocol):
    def transcribe(self, audio: object, *, batch_size: int) -> object: ...


class WhisperXRuntime(Protocol):
    def load_model(
        self,
        whisper_arch: str,
        device: str,
        *,
        compute_type: str,
        language: str | None,
        download_root: str,
        use_auth_token: str | None,
    ) -> WhisperXModel: ...

    def load_audio(self, file: str) -> object: ...


def _load_whisperx_runtime() -> WhisperXRuntime:
    return cast(WhisperXRuntime, cast(object, import_module("whisperx")))


class WhisperXAdapter:
    def __init__(
        self,
        config: WhisperXConfig,
        *,
        hf_token: SecretStr | None = None,
        runtime_loader: Callable[[], WhisperXRuntime] = _load_whisperx_runtime,
        version_getter: Callable[[str], str] = metadata.version,
    ) -> None:
        self._config = config
        self._hf_token = hf_token
        self._runtime_loader = runtime_loader
        self._version_getter = version_getter
        self._runtime: WhisperXRuntime | None = None
        self._model: WhisperXModel | None = None
        self._whisperx_version: str | None = None

    def transcribe(self, normalized_wav: Path) -> TranscriptionResult:
        model = self._get_model()
        assert self._runtime is not None
        try:
            audio = self._runtime.load_audio(str(normalized_wav))
            raw_result = model.transcribe(audio, batch_size=self._config.batch_size)
        except Exception as error:
            if _is_out_of_memory(error):
                raise WhisperXAdapterError(
                    WhisperXErrorCode.MODEL_OOM,
                    "WhisperX ran out of memory during transcription",
                ) from error
            raise WhisperXAdapterError(
                WhisperXErrorCode.TRANSCRIPTION_FAILED,
                "WhisperX transcription could not be completed",
            ) from error

        language, segments = _normalize_result(raw_result, self._config.language)
        return TranscriptionResult(
            language=language,
            segments=segments,
            model_fingerprint=self._fingerprint(),
        )

    def _get_model(self) -> WhisperXModel:
        if self._model is not None:
            return self._model
        try:
            runtime = self._runtime_loader()
            whisperx_version = self._version_getter("whisperx")
            if not whisperx_version.strip():
                raise ValueError("WhisperX package version is empty")
            model = runtime.load_model(
                self._config.model,
                self._config.device,
                compute_type=self._config.compute_type,
                language=self._config.language,
                download_root=str(self._config.model_cache_root),
                use_auth_token=(
                    self._hf_token.get_secret_value() if self._hf_token is not None else None
                ),
            )
        except Exception as error:
            if _is_out_of_memory(error):
                raise WhisperXAdapterError(
                    WhisperXErrorCode.MODEL_OOM,
                    "WhisperX ran out of memory while loading the model",
                ) from error
            if is_model_access_denied(error):
                raise WhisperXAdapterError(
                    WhisperXErrorCode.MODEL_ACCESS_DENIED,
                    "The WhisperX model could not be accessed with the configured token",
                ) from error
            if is_model_download_failure(error):
                raise WhisperXAdapterError(
                    WhisperXErrorCode.MODEL_DOWNLOAD_FAILED,
                    "The WhisperX model could not be downloaded",
                ) from error
            raise WhisperXAdapterError(
                WhisperXErrorCode.MODEL_LOAD_FAILED,
                "WhisperX model could not be loaded",
            ) from error
        self._runtime = runtime
        self._model = model
        self._whisperx_version = whisperx_version
        return model

    def _fingerprint(self) -> ModelFingerprint:
        assert self._whisperx_version is not None
        return ModelFingerprint(
            whisperx_version=self._whisperx_version,
            model=self._config.model,
            device=self._config.device,
            compute_type=self._config.compute_type,
            batch_size=self._config.batch_size,
            language=self._config.language,
        )


def _normalize_result(
    raw_result: object,
    configured_language: str | None,
) -> tuple[str, tuple[TranscriptionSegment, ...]]:
    if not isinstance(raw_result, Mapping):
        raise _invalid_response()
    raw_language = raw_result.get("language")
    if not isinstance(raw_language, str) or not raw_language.strip():
        raise _invalid_response()
    raw_segments = raw_result.get("segments")
    if not isinstance(raw_segments, list):
        raise _invalid_response()

    segments: list[TranscriptionSegment] = []
    for raw_segment in raw_segments:
        if not isinstance(raw_segment, Mapping):
            raise _invalid_response()
        start = _finite_number(raw_segment.get("start"))
        end = _finite_number(raw_segment.get("end"))
        text = raw_segment.get("text")
        if start is None or end is None or start < 0 or end < start or not isinstance(text, str):
            raise _invalid_response()
        segments.append(TranscriptionSegment(start=start, end=end, text=text))
    return configured_language or raw_language.strip(), tuple(segments)


def _finite_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _invalid_response() -> WhisperXAdapterError:
    return WhisperXAdapterError(
        WhisperXErrorCode.INVALID_RESPONSE,
        "WhisperX returned an invalid transcription response",
    )


def _is_out_of_memory(error: BaseException) -> bool:
    current: BaseException | None = error
    visited: set[int] = set()
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        name = type(current).__name__.casefold()
        message = str(current).casefold()
        if isinstance(current, MemoryError) or "outofmemory" in name or "out of memory" in message:
            return True
        current = current.__cause__ or current.__context__
    return False
