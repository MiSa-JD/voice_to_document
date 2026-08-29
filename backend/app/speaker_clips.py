from __future__ import annotations

import errno
import math
import sqlite3
import subprocess
import tempfile
import uuid
import wave
from dataclasses import dataclass
from pathlib import Path

from app.artifacts import write_artifact
from app.db import connect, migrate_database, utc_now

MIN_SEGMENT_MS = 2_000
MIN_CENTER_GAP_MS = 10_000
MAX_CLIP_MS = 8_000
MAX_CLIPS = 3
MAX_SILENCE_RATIO = 0.40
SILENCE_AMPLITUDE = 500
ANALYSIS_WINDOW_MS = 20


class SpeakerClipError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ClipCandidate:
    segment_id: str
    local_speaker_id: str
    start_ms: int
    end_ms: int

    @property
    def center_ms(self) -> int:
        return (self.start_ms + self.end_ms) // 2


@dataclass(frozen=True)
class GeneratedClip:
    segment_id: str
    local_speaker_id: str
    artifact_id: str
    clip_index: int
    start_ms: int
    end_ms: int
    silence_ratio: float


def select_clip_candidates(rows: list[sqlite3.Row]) -> dict[str, list[ClipCandidate]]:
    candidates: dict[str, list[ClipCandidate]] = {}
    ordered = sorted(
        rows,
        key=lambda row: (int(row["start_ms"]), int(row["end_ms"]), str(row["id"])),
    )
    for row in ordered:
        speaker_id = row["local_speaker_id"]
        start_ms = int(row["start_ms"])
        end_ms = int(row["end_ms"])
        if (
            row["assignment_status"] != "assigned"
            or speaker_id is None
            or end_ms - start_ms < MIN_SEGMENT_MS
        ):
            continue
        candidate = ClipCandidate(str(row["id"]), str(speaker_id), start_ms, end_ms)
        selected = candidates.setdefault(candidate.local_speaker_id, [])
        if len(selected) >= MAX_CLIPS:
            continue
        if all(abs(candidate.center_ms - item.center_ms) >= MIN_CENTER_GAP_MS for item in selected):
            selected.append(candidate)
    return candidates


def clip_bounds(candidate: ClipCandidate) -> tuple[int, int]:
    duration_ms = min(candidate.end_ms - candidate.start_ms, MAX_CLIP_MS)
    start_ms = max(candidate.start_ms, candidate.center_ms - duration_ms // 2)
    end_ms = min(candidate.end_ms, start_ms + duration_ms)
    start_ms = max(candidate.start_ms, end_ms - duration_ms)
    return start_ms, end_ms


def generate_speaker_clips(
    database_path: Path,
    speaker_root: Path,
    recording_id: str,
    source: Path,
    revision: int,
    *,
    executable: str = "ffmpeg",
    timeout_seconds: float = 60,
) -> list[GeneratedClip]:
    migrate_database(database_path)
    with connect(database_path) as connection:
        rows = connection.execute(
            """
            SELECT id, start_ms, end_ms, local_speaker_id, assignment_status
            FROM segments WHERE recording_id = ? ORDER BY start_ms, end_ms, id
            """,
            (recording_id,),
        ).fetchall()
        speaker_rows = connection.execute(
            """
            SELECT local_speaker_id FROM recording_speakers
            WHERE recording_id = ? ORDER BY local_speaker_id
            """,
            (recording_id,),
        ).fetchall()
    candidates = select_clip_candidates(list(rows))
    generated: list[GeneratedClip] = []
    statuses: dict[str, tuple[str, str | None]] = {}

    for speaker_row in speaker_rows:
        speaker_id = str(speaker_row["local_speaker_id"])
        accepted: list[GeneratedClip] = []
        try:
            for candidate in candidates.get(speaker_id, []):
                start_ms, end_ms = clip_bounds(candidate)
                content, silence_ratio = _render_clip(
                    source,
                    start_ms,
                    end_ms,
                    executable=executable,
                    timeout_seconds=timeout_seconds,
                )
                if silence_ratio > MAX_SILENCE_RATIO:
                    continue
                clip_index = len(accepted)
                kind = f"speaker_clip:{speaker_id}:{clip_index}"
                relative_path = Path(recording_id) / speaker_id / f"{clip_index}.wav"
                artifact = write_artifact(
                    database_path,
                    speaker_root,
                    recording_id,
                    kind,
                    relative_path,
                    content,
                    revision,
                )
                accepted.append(
                    GeneratedClip(
                        segment_id=candidate.segment_id,
                        local_speaker_id=speaker_id,
                        artifact_id=artifact.artifact_id,
                        clip_index=clip_index,
                        start_ms=start_ms,
                        end_ms=end_ms,
                        silence_ratio=silence_ratio,
                    )
                )
            statuses[speaker_id] = ("ready" if len(accepted) >= 2 else "insufficient", None)
            generated.extend(accepted)
        except SpeakerClipError as error:
            statuses[speaker_id] = ("failed", error.code)

    _register_clips(database_path, recording_id, revision, generated, statuses)
    return generated


def _render_clip(
    source: Path,
    start_ms: int,
    end_ms: int,
    *,
    executable: str,
    timeout_seconds: float,
) -> tuple[bytes, float]:
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temporary:
            temporary_path = Path(temporary.name)
        command = [
            executable,
            "-nostdin",
            "-v",
            "error",
            "-y",
            "-ss",
            f"{start_ms / 1000:.3f}",
            "-i",
            str(source),
            "-t",
            f"{(end_ms - start_ms) / 1000:.3f}",
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
            str(temporary_path),
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
            raise SpeakerClipError(
                "SPEAKER_CLIP_FFMPEG_NOT_FOUND", "ffmpeg is unavailable"
            ) from error
        except subprocess.TimeoutExpired as error:
            raise SpeakerClipError("SPEAKER_CLIP_TIMEOUT", "clip generation timed out") from error
        except OSError as error:
            code = (
                "SPEAKER_CLIP_DISK_FULL" if error.errno == errno.ENOSPC else "SPEAKER_CLIP_IO_ERROR"
            )
            raise SpeakerClipError(code, "clip generation could not start") from error
        if result.returncode != 0:
            code = (
                "SPEAKER_CLIP_DISK_FULL"
                if "no space left on device" in (result.stderr or "").casefold()
                else "SPEAKER_CLIP_FFMPEG_FAILED"
            )
            raise SpeakerClipError(code, "ffmpeg could not generate a clip")
        content = temporary_path.read_bytes()
        if not content:
            raise SpeakerClipError("SPEAKER_CLIP_FFMPEG_FAILED", "ffmpeg produced an empty clip")
        return content, wav_silence_ratio(temporary_path)
    except SpeakerClipError:
        raise
    except OSError as error:
        code = "SPEAKER_CLIP_DISK_FULL" if error.errno == errno.ENOSPC else "SPEAKER_CLIP_IO_ERROR"
        raise SpeakerClipError(code, "clip output could not be read") from error
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def wav_silence_ratio(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as audio:
            if (
                audio.getnchannels() != 1
                or audio.getsampwidth() != 2
                or audio.getframerate() != 16000
            ):
                raise SpeakerClipError("SPEAKER_CLIP_INVALID_WAV", "clip format is invalid")
            window_frames = max(1, audio.getframerate() * ANALYSIS_WINDOW_MS // 1000)
            silent = 0
            total = 0
            while frames := audio.readframes(window_frames):
                samples = memoryview(frames).cast("h")
                if not samples:
                    continue
                rms = math.sqrt(sum(int(value) ** 2 for value in samples) / len(samples))
                silent += int(rms <= SILENCE_AMPLITUDE)
                total += 1
    except (EOFError, wave.Error) as error:
        raise SpeakerClipError("SPEAKER_CLIP_INVALID_WAV", "clip format is invalid") from error
    if total == 0:
        raise SpeakerClipError("SPEAKER_CLIP_INVALID_WAV", "clip contains no samples")
    return silent / total


def _register_clips(
    database_path: Path,
    recording_id: str,
    revision: int,
    clips: list[GeneratedClip],
    statuses: dict[str, tuple[str, str | None]],
) -> None:
    timestamp = utc_now()
    with connect(database_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "DELETE FROM speaker_clips WHERE recording_id = ? AND revision = ?",
            (recording_id, revision),
        )
        connection.executemany(
            """
            INSERT INTO speaker_clips(
                id, recording_id, local_speaker_id, segment_id, artifact_id, revision,
                clip_index, start_ms, end_ms, silence_ratio, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    str(
                        uuid.uuid5(
                            uuid.UUID(recording_id),
                            f"speaker-clip:{clip.local_speaker_id}:{revision}:{clip.clip_index}",
                        )
                    ),
                    recording_id,
                    clip.local_speaker_id,
                    clip.segment_id,
                    clip.artifact_id,
                    revision,
                    clip.clip_index,
                    clip.start_ms,
                    clip.end_ms,
                    clip.silence_ratio,
                    timestamp,
                )
                for clip in clips
            ],
        )
        connection.executemany(
            """
            UPDATE recording_speakers
            SET clip_status = ?, clip_error_code = ?, updated_at = ?
            WHERE recording_id = ? AND local_speaker_id = ?
            """,
            [
                (status, error_code, timestamp, recording_id, speaker_id)
                for speaker_id, (status, error_code) in statuses.items()
            ],
        )
        connection.commit()
