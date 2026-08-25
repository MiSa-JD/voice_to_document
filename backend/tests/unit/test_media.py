from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from app.media import MediaErrorCode, MediaProbeError, probe_media

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
