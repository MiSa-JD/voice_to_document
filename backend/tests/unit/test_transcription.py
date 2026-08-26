from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import cast

import pytest
from app.transcription import (
    WhisperXAdapter,
    WhisperXAdapterError,
    WhisperXConfig,
    WhisperXErrorCode,
    WhisperXModel,
)
from pydantic import SecretStr


class FakeModel:
    def __init__(self, result: object, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls: list[tuple[object, int]] = []

    def transcribe(self, audio: object, *, batch_size: int) -> object:
        self.calls.append((audio, batch_size))
        if self.error is not None:
            raise self.error
        return self.result


class FakeRuntime:
    def __init__(
        self,
        model: FakeModel,
        *,
        load_error: Exception | None = None,
        audio_error: Exception | None = None,
    ) -> None:
        self.model = model
        self.load_error = load_error
        self.audio_error = audio_error
        self.load_model_calls: list[dict[str, object]] = []
        self.load_audio_calls: list[str] = []

    def load_model(
        self,
        whisper_arch: str,
        device: str,
        *,
        compute_type: str,
        language: str | None,
        download_root: str,
        use_auth_token: str | None,
    ) -> WhisperXModel:
        self.load_model_calls.append(
            {
                "whisper_arch": whisper_arch,
                "device": device,
                "compute_type": compute_type,
                "language": language,
                "download_root": download_root,
                "use_auth_token": use_auth_token,
            }
        )
        if self.load_error is not None:
            raise self.load_error
        return cast(WhisperXModel, self.model)

    def load_audio(self, file: str) -> object:
        self.load_audio_calls.append(file)
        if self.audio_error is not None:
            raise self.audio_error
        return "decoded-audio"


def valid_result() -> dict[str, object]:
    return {
        "language": "ko",
        "segments": [
            {"start": 0, "end": 1.25, "text": "비밀 전문"},
            {"start": 1.25, "end": 2, "text": "두 번째 문장"},
        ],
    }


def adapter_for(
    tmp_path: Path,
    runtime: FakeRuntime,
    *,
    language: str | None = None,
) -> WhisperXAdapter:
    return WhisperXAdapter(
        WhisperXConfig(language=language, model_cache_root=tmp_path),
        hf_token=SecretStr("hf_private_test_value"),
        runtime_loader=lambda: runtime,
        version_getter=lambda package: "3.8.6" if package == "whisperx" else "unexpected",
    )


def test_passes_default_model_settings_and_normalizes_result(tmp_path: Path) -> None:
    model = FakeModel(valid_result())
    runtime = FakeRuntime(model)
    adapter = adapter_for(tmp_path, runtime)
    source = tmp_path / "normalized.wav"

    result = adapter.transcribe(source)

    assert runtime.load_model_calls == [
        {
            "whisper_arch": "large-v3",
            "device": "cuda",
            "compute_type": "float16",
            "language": None,
            "download_root": str(tmp_path),
            "use_auth_token": "hf_private_test_value",
        }
    ]
    assert runtime.load_audio_calls == [str(source)]
    assert model.calls == [("decoded-audio", 4)]
    assert result.language == "ko"
    assert [(segment.start, segment.end, segment.text) for segment in result.segments] == [
        (0.0, 1.25, "비밀 전문"),
        (1.25, 2.0, "두 번째 문장"),
    ]


def test_fixed_language_is_passed_to_model_and_reported(tmp_path: Path) -> None:
    runtime = FakeRuntime(FakeModel(valid_result()))

    result = adapter_for(tmp_path, runtime, language=" en ").transcribe(tmp_path / "audio.wav")

    assert runtime.load_model_calls[0]["language"] == "en"
    assert result.language == "en"
    assert result.model_fingerprint.language == "en"


def test_model_is_lazily_loaded_once_and_reused(tmp_path: Path) -> None:
    model = FakeModel(valid_result())
    runtime = FakeRuntime(model)
    adapter = adapter_for(tmp_path, runtime)

    assert runtime.load_model_calls == []
    first = adapter.transcribe(tmp_path / "first.wav")
    second = adapter.transcribe(tmp_path / "second.wav")

    assert len(runtime.load_model_calls) == 1
    assert len(model.calls) == 2
    assert first.model_fingerprint == second.model_fingerprint
    assert first.model_fingerprint.as_dict() == {
        "whisperx_version": "3.8.6",
        "model": "large-v3",
        "device": "cuda",
        "compute_type": "float16",
        "batch_size": 4,
        "language": None,
    }


def test_empty_segment_list_is_valid(tmp_path: Path) -> None:
    runtime = FakeRuntime(FakeModel({"language": "ko", "segments": []}))

    result = adapter_for(tmp_path, runtime).transcribe(tmp_path / "silence.wav")

    assert result.language == "ko"
    assert result.segments == ()


@pytest.mark.parametrize(
    "result",
    [
        {},
        {"language": "", "segments": []},
        {"language": 7, "segments": []},
        {"language": "ko", "segments": "invalid"},
        {"language": "ko", "segments": [{}]},
        {"language": "ko", "segments": [{"start": -1, "end": 2, "text": "text"}]},
        {"language": "ko", "segments": [{"start": 2, "end": 1, "text": "text"}]},
        {"language": "ko", "segments": [{"start": 0, "end": 1, "text": None}]},
    ],
)
def test_rejects_invalid_model_response(tmp_path: Path, result: object) -> None:
    adapter = adapter_for(tmp_path, FakeRuntime(FakeModel(result)))

    with pytest.raises(WhisperXAdapterError) as error:
        adapter.transcribe(tmp_path / "audio.wav")

    assert error.value.code == WhisperXErrorCode.INVALID_RESPONSE


@pytest.mark.parametrize(
    ("runtime", "expected_code"),
    [
        (
            FakeRuntime(FakeModel(valid_result()), load_error=RuntimeError("load exploded")),
            WhisperXErrorCode.MODEL_LOAD_FAILED,
        ),
        (
            FakeRuntime(FakeModel(valid_result()), load_error=RuntimeError("CUDA out of memory")),
            WhisperXErrorCode.MODEL_OOM,
        ),
        (
            FakeRuntime(FakeModel(valid_result(), error=RuntimeError("inference exploded"))),
            WhisperXErrorCode.TRANSCRIPTION_FAILED,
        ),
        (
            FakeRuntime(FakeModel(valid_result(), error=RuntimeError("CUDA out of memory"))),
            WhisperXErrorCode.MODEL_OOM,
        ),
        (
            FakeRuntime(FakeModel(valid_result()), audio_error=RuntimeError("decode exploded")),
            WhisperXErrorCode.TRANSCRIPTION_FAILED,
        ),
    ],
)
def test_classifies_adapter_failures(
    tmp_path: Path,
    runtime: FakeRuntime,
    expected_code: WhisperXErrorCode,
) -> None:
    adapter = adapter_for(tmp_path, runtime)

    with pytest.raises(WhisperXAdapterError) as error:
        adapter.transcribe(tmp_path / "private-source.wav")

    assert error.value.code == expected_code
    assert "private-source.wav" not in str(error.value)
    assert "exploded" not in str(error.value)


def test_fingerprint_and_logs_do_not_expose_secrets_transcript_or_path(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    runtime = FakeRuntime(FakeModel(valid_result()))
    adapter = adapter_for(tmp_path, runtime)
    private_path = tmp_path / "private-source.wav"

    with caplog.at_level(logging.DEBUG):
        result = adapter.transcribe(private_path)
    public_json = json.dumps(result.model_fingerprint.as_dict(), sort_keys=True)

    exposed = public_json + caplog.text
    assert "hf_private_test_value" not in exposed
    assert "비밀 전문" not in exposed
    assert str(private_path) not in exposed
