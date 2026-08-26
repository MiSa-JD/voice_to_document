from __future__ import annotations

import errno
import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from app.media import (
    AudioNormalizationError,
    AudioNormalizationErrorCode,
    MediaErrorCode,
    MediaProbeError,
    normalized_audio,
    probe_media,
)

FIXTURES = Path(__file__).parents[1] / "fixtures"


def test_valid_fixture_with_unicode_and_spaces(tmp_path: Path) -> None:
    target = tmp_path / "한글 녹음 파일.m4a"
    shutil.copyfile(FIXTURES / "complete.m4a", target)

    info = probe_media(target)

    assert info.duration_ms == 2000
    assert info.audio_codec == "aac"


def test_corrupt_fixture_has_specific_error() -> None:
    with pytest.raises(MediaProbeError) as error:
        probe_media(FIXTURES / "corrupt.m4a")

    assert error.value.code == MediaErrorCode.MEDIA_CORRUPT
    assert "corrupt.m4a" not in str(error.value)


def test_missing_ffprobe_has_specific_error(tmp_path: Path) -> None:
    with pytest.raises(MediaProbeError) as error:
        probe_media(tmp_path / "audio.m4a", executable="missing-ffprobe-for-test")

    assert error.value.code == MediaErrorCode.FFPROBE_NOT_FOUND


def test_timeout_has_specific_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def timeout(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired("ffprobe", 1)

    monkeypatch.setattr(subprocess, "run", timeout)

    with pytest.raises(MediaProbeError) as error:
        probe_media(tmp_path / "audio.m4a", timeout_seconds=1)

    assert error.value.code == MediaErrorCode.FFPROBE_TIMEOUT


def test_normalizes_real_fixture_to_mono_pcm_16khz_and_preserves_source(
    tmp_path: Path,
) -> None:
    source = tmp_path / "공백 있는 원본 녹음.m4a"
    shutil.copyfile(FIXTURES / "complete.m4a", source)
    original = source.read_bytes()

    with normalized_audio(source, work_root=tmp_path) as normalized:
        assert normalized.parent.parent == tmp_path
        assert normalized != source
        assert normalized.is_file()
        completed = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=codec_name,sample_rate,channels,sample_fmt",
                "-of",
                "json",
                str(normalized),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        stream = json.loads(completed.stdout)["streams"][0]
        work_dir = normalized.parent

        assert stream == {
            "codec_name": "pcm_s16le",
            "sample_fmt": "s16",
            "sample_rate": "16000",
            "channels": 1,
        }
        assert source.read_bytes() == original

    assert not work_dir.exists()
    assert source.read_bytes() == original


def test_normalizer_uses_argument_array_and_first_audio_stream(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, Any] = {}

    def fake_run(arguments: list[str], **kwargs: object) -> SimpleNamespace:
        captured["arguments"] = arguments
        captured.update(kwargs)
        Path(arguments[-1]).write_bytes(b"wav")
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with normalized_audio(tmp_path / "source file.m4a", work_root=tmp_path) as output:
        assert output.read_bytes() == b"wav"

    arguments = captured["arguments"]
    assert isinstance(arguments, list)
    assert arguments[arguments.index("-map") + 1] == "0:a:0"
    assert "-vn" in arguments
    assert arguments[arguments.index("-map_metadata") + 1] == "-1"
    assert arguments[arguments.index("-ac") + 1] == "1"
    assert arguments[arguments.index("-ar") + 1] == "16000"
    assert arguments[arguments.index("-c:a") + 1] == "pcm_s16le"
    assert "shell" not in captured


@pytest.mark.parametrize(
    ("failure", "expected_code"),
    [
        (FileNotFoundError(), AudioNormalizationErrorCode.FFMPEG_NOT_FOUND),
        (subprocess.TimeoutExpired("ffmpeg", 1), AudioNormalizationErrorCode.FFMPEG_TIMEOUT),
        (OSError(errno.ENOSPC, "disk full"), AudioNormalizationErrorCode.DISK_FULL),
    ],
)
def test_normalizer_classifies_execution_failures_and_cleans_workspace(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    failure: BaseException,
    expected_code: AudioNormalizationErrorCode,
) -> None:
    def fail(*_args: object, **_kwargs: object) -> None:
        raise failure

    monkeypatch.setattr(subprocess, "run", fail)

    with (
        pytest.raises(AudioNormalizationError) as error,
        normalized_audio(tmp_path / "private source.m4a", work_root=tmp_path),
    ):
        pytest.fail("normalization must not yield")

    assert error.value.code == expected_code
    assert "private source.m4a" not in str(error.value)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    ("stderr", "expected_code"),
    [
        (
            "Stream map '0:a:0' matches no streams. /secret/private.m4a",
            AudioNormalizationErrorCode.AUDIO_STREAM_INVALID,
        ),
        ("No space left on device: /secret/output.wav", AudioNormalizationErrorCode.DISK_FULL),
        (
            "decoder exploded at /secret/private.m4a",
            AudioNormalizationErrorCode.NORMALIZATION_FAILED,
        ),
    ],
)
def test_normalizer_classifies_ffmpeg_failures_without_leaking_stderr(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    stderr: str,
    expected_code: AudioNormalizationErrorCode,
) -> None:
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=1, stderr=stderr),
    )

    with (
        pytest.raises(AudioNormalizationError) as error,
        normalized_audio(tmp_path / "source.m4a", work_root=tmp_path),
    ):
        pytest.fail("normalization must not yield")

    assert error.value.code == expected_code
    assert "/secret" not in str(error.value)
    assert "decoder exploded" not in str(error.value)
    assert list(tmp_path.iterdir()) == []


def test_normalizer_rejects_incomplete_output_and_cleans_workspace(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stderr=""),
    )

    with (
        pytest.raises(AudioNormalizationError) as error,
        normalized_audio(tmp_path / "source.m4a", work_root=tmp_path),
    ):
        pytest.fail("normalization must not yield")

    assert error.value.code == AudioNormalizationErrorCode.NORMALIZATION_FAILED
    assert list(tmp_path.iterdir()) == []


def test_normalizer_cleans_workspace_when_caller_raises(tmp_path: Path) -> None:
    with (
        pytest.raises(RuntimeError, match="caller failed"),
        normalized_audio(FIXTURES / "complete.m4a", work_root=tmp_path) as normalized,
    ):
        work_dir = normalized.parent
        raise RuntimeError("caller failed")

    assert not work_dir.exists()
