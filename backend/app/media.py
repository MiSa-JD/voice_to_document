from __future__ import annotations

import errno
import json
import shutil
import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any


class MediaErrorCode(StrEnum):
    FFPROBE_NOT_FOUND = "FFPROBE_NOT_FOUND"
    FFPROBE_TIMEOUT = "FFPROBE_TIMEOUT"
    MEDIA_CORRUPT = "MEDIA_CORRUPT"
    MEDIA_INVALID_RESPONSE = "MEDIA_INVALID_RESPONSE"
    MEDIA_NO_AUDIO = "MEDIA_NO_AUDIO"
    MEDIA_INVALID_DURATION = "MEDIA_INVALID_DURATION"


class MediaProbeError(RuntimeError):
    def __init__(self, code: MediaErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


class AudioNormalizationErrorCode(StrEnum):
    FFMPEG_NOT_FOUND = "FFMPEG_NOT_FOUND"
    FFMPEG_TIMEOUT = "FFMPEG_TIMEOUT"
    AUDIO_STREAM_INVALID = "AUDIO_STREAM_INVALID"
    DISK_FULL = "DISK_FULL"
    NORMALIZATION_FAILED = "NORMALIZATION_FAILED"


class AudioNormalizationError(RuntimeError):
    def __init__(self, code: AudioNormalizationErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class MediaInfo:
    duration_ms: int
    audio_codec: str | None
    recorded_at: str | None


@contextmanager
def normalized_audio(
    source: Path,
    *,
    work_root: Path | None = None,
    timeout_seconds: float = 300,
    executable: str = "ffmpeg",
) -> Iterator[Path]:
    """Yield a temporary mono 16 kHz PCM WAV without modifying the source."""
    work_dir: Path | None = None
    try:
        try:
            work_dir = Path(
                tempfile.mkdtemp(
                    prefix="voice-to-document-audio-",
                    dir=work_root,
                )
            )
        except OSError as error:
            raise _normalization_os_error(error) from error

        output = work_dir / "normalized.wav"
        command = [
            executable,
            "-nostdin",
            "-v",
            "error",
            "-y",
            "-i",
            str(source),
            "-map",
            "0:a:0",
            "-vn",
            "-map_metadata",
            "-1",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            str(output),
        ]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
        except FileNotFoundError as error:
            raise AudioNormalizationError(
                AudioNormalizationErrorCode.FFMPEG_NOT_FOUND,
                "ffmpeg executable is unavailable",
            ) from error
        except subprocess.TimeoutExpired as error:
            raise AudioNormalizationError(
                AudioNormalizationErrorCode.FFMPEG_TIMEOUT,
                "audio normalization timed out",
            ) from error
        except OSError as error:
            raise _normalization_os_error(error) from error

        if result.returncode != 0:
            raise _normalization_process_error(result.stderr)
        try:
            complete = output.is_file() and output.stat().st_size > 0
        except OSError as error:
            raise _normalization_os_error(error) from error
        if not complete:
            raise AudioNormalizationError(
                AudioNormalizationErrorCode.NORMALIZATION_FAILED,
                "ffmpeg did not produce a complete normalized audio file",
            )
        yield output
    finally:
        if work_dir is not None:
            shutil.rmtree(work_dir, ignore_errors=True)


def _normalization_os_error(error: OSError) -> AudioNormalizationError:
    if error.errno == errno.ENOSPC:
        return AudioNormalizationError(
            AudioNormalizationErrorCode.DISK_FULL,
            "insufficient disk space for audio normalization",
        )
    return AudioNormalizationError(
        AudioNormalizationErrorCode.NORMALIZATION_FAILED,
        "audio normalization could not be completed",
    )


def _normalization_process_error(stderr: str | None) -> AudioNormalizationError:
    detail = (stderr or "").casefold()
    if "no space left on device" in detail:
        return AudioNormalizationError(
            AudioNormalizationErrorCode.DISK_FULL,
            "insufficient disk space for audio normalization",
        )
    if (
        "matches no streams" in detail
        or "does not contain any stream" in detail
        or "cannot find a matching stream" in detail
    ):
        return AudioNormalizationError(
            AudioNormalizationErrorCode.AUDIO_STREAM_INVALID,
            "media does not contain a usable audio stream",
        )
    return AudioNormalizationError(
        AudioNormalizationErrorCode.NORMALIZATION_FAILED,
        "ffmpeg could not normalize the audio",
    )


def probe_media(
    path: Path,
    timeout_seconds: float = 15,
    executable: str = "ffprobe",
) -> MediaInfo:
    command = [
        executable,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except FileNotFoundError as error:
        raise MediaProbeError(
            MediaErrorCode.FFPROBE_NOT_FOUND,
            "ffprobe executable is unavailable",
        ) from error
    except subprocess.TimeoutExpired as error:
        raise MediaProbeError(
            MediaErrorCode.FFPROBE_TIMEOUT,
            "media inspection timed out",
        ) from error

    if result.returncode != 0:
        raise MediaProbeError(
            MediaErrorCode.MEDIA_CORRUPT,
            "media container could not be read",
        )
    try:
        payload: dict[str, Any] = json.loads(result.stdout)
    except (json.JSONDecodeError, TypeError) as error:
        raise MediaProbeError(
            MediaErrorCode.MEDIA_INVALID_RESPONSE,
            "ffprobe returned an invalid response",
        ) from error

    streams = payload.get("streams")
    if not isinstance(streams, list):
        streams = []
    audio_streams: list[dict[str, Any]] = [
        stream
        for stream in streams
        if isinstance(stream, dict) and stream.get("codec_type") == "audio"
    ]
    if not audio_streams:
        raise MediaProbeError(MediaErrorCode.MEDIA_NO_AUDIO, "media has no audio stream")

    raw_format = payload.get("format")
    format_data: dict[str, Any] = raw_format if isinstance(raw_format, dict) else {}
    duration = _positive_float(format_data.get("duration"))
    if duration is None:
        duration = next(
            (
                value
                for stream in audio_streams
                if (value := _positive_float(stream.get("duration"))) is not None
            ),
            None,
        )
    if duration is None:
        raise MediaProbeError(
            MediaErrorCode.MEDIA_INVALID_DURATION,
            "media duration must be greater than zero",
        )

    raw_tags = format_data.get("tags")
    tags: dict[str, Any] = raw_tags if isinstance(raw_tags, dict) else {}
    return MediaInfo(
        duration_ms=round(duration * 1000),
        audio_codec=_optional_string(audio_streams[0].get("codec_name")),
        recorded_at=_optional_string(tags.get("creation_time")),
    )


def _positive_float(value: object) -> float | None:
    try:
        number = float(str(value))
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _optional_string(value: object) -> str | None:
    return str(value) if value not in (None, "") else None
