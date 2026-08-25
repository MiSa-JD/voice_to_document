from __future__ import annotations

import json
import subprocess
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


@dataclass(frozen=True)
class MediaInfo:
    duration_ms: int
    audio_codec: str | None
    recorded_at: str | None


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
