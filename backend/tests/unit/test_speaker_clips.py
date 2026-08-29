from __future__ import annotations

import shutil
import subprocess
import uuid
import wave
from pathlib import Path

import pytest
from app.db import connect, migrate_database
from app.speaker_clips import (
    ClipCandidate,
    clip_bounds,
    generate_speaker_clips,
    select_clip_candidates,
    wav_silence_ratio,
)


def _row(
    segment_id: str,
    start_ms: int,
    end_ms: int,
    speaker_id: str | None = "SPEAKER_00",
    status: str = "assigned",
) -> dict[str, object]:
    return {
        "id": segment_id,
        "start_ms": start_ms,
        "end_ms": end_ms,
        "local_speaker_id": speaker_id,
        "assignment_status": status,
    }


def test_candidate_selection_is_deterministic_and_filters_invalid_segments() -> None:
    rows = [
        _row("late", 30_000, 34_000),
        _row("short", 9_000, 10_999),
        _row("overlap", 12_000, 15_000, status="overlap"),
        _row("near", 8_000, 12_000),
        _row("first", 0, 4_000),
        _row("third", 20_000, 24_000),
        _row("unassigned", 40_000, 44_000, None, "unassigned"),
    ]

    selected = select_clip_candidates(rows)  # type: ignore[arg-type]

    assert [item.segment_id for item in selected["SPEAKER_00"]] == ["first", "third", "late"]


def test_clip_bounds_are_centered_and_limited_to_eight_seconds() -> None:
    candidate = ClipCandidate("segment", "SPEAKER_00", 1_000, 13_000)

    assert clip_bounds(candidate) == (3_000, 11_000)


def test_wav_silence_ratio_uses_fixed_windows(tmp_path: Path) -> None:
    path = tmp_path / "clip.wav"
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16_000)
        audio.writeframes((0).to_bytes(2, "little", signed=True) * 16_000)
        audio.writeframes((4_000).to_bytes(2, "little", signed=True) * 16_000)

    assert wav_silence_ratio(path) == pytest.approx(0.5)


def test_generation_registers_only_non_silent_clips_and_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "app.db"
    speaker_root = tmp_path / "speakers"
    speaker_root.mkdir()
    recording_id = str(uuid.uuid4())
    source = tmp_path / "source.m4a"
    source.write_bytes(b"source")
    _seed_recording(database_path, recording_id)

    calls = 0

    def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        output = Path(command[-1])
        amplitude = 0 if calls == 1 else 4_000
        calls += 1
        with wave.open(str(output), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(16_000)
            audio.writeframes(amplitude.to_bytes(2, "little", signed=True) * 32_000)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("app.speaker_clips.subprocess.run", fake_run)

    first = generate_speaker_clips(database_path, speaker_root, recording_id, source, 1)
    second = generate_speaker_clips(database_path, speaker_root, recording_id, source, 1)

    assert len(first) == 2
    assert len(second) == 3
    with connect(database_path) as connection:
        clip_count = connection.execute("SELECT COUNT(*) FROM speaker_clips").fetchone()[0]
        artifact_count = connection.execute(
            "SELECT COUNT(*) FROM artifacts WHERE kind LIKE 'speaker_clip:%'"
        ).fetchone()[0]
        speaker = connection.execute(
            "SELECT clip_status, clip_error_code FROM recording_speakers"
        ).fetchone()
    assert clip_count == 3
    assert artifact_count == 3
    assert dict(speaker) == {"clip_status": "ready", "clip_error_code": None}


def test_ffmpeg_failure_records_safe_failure_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "app.db"
    speaker_root = tmp_path / "speakers"
    speaker_root.mkdir()
    recording_id = str(uuid.uuid4())
    source = tmp_path / "source.m4a"
    source.write_bytes(b"source")
    _seed_recording(database_path, recording_id)

    def fail_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 1, "", "private source detail")

    monkeypatch.setattr("app.speaker_clips.subprocess.run", fail_run)

    assert generate_speaker_clips(database_path, speaker_root, recording_id, source, 1) == []
    with connect(database_path) as connection:
        speaker = connection.execute(
            "SELECT clip_status, clip_error_code FROM recording_speakers"
        ).fetchone()
    assert dict(speaker) == {
        "clip_status": "failed",
        "clip_error_code": "SPEAKER_CLIP_FFMPEG_FAILED",
    }


def test_real_ffmpeg_generates_mono_16khz_pcm_fixture(tmp_path: Path) -> None:
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg is unavailable")
    database_path = tmp_path / "app.db"
    speaker_root = tmp_path / "speakers"
    speaker_root.mkdir()
    recording_id = str(uuid.uuid4())
    source = tmp_path / "source.wav"
    with wave.open(str(source), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16_000)
        audio.writeframes((4_000).to_bytes(2, "little", signed=True) * 16_000 * 30)
    _seed_recording(database_path, recording_id)

    clips = generate_speaker_clips(database_path, speaker_root, recording_id, source, 1)

    assert len(clips) == 3
    for clip in clips:
        path = speaker_root / recording_id / "SPEAKER_00" / f"{clip.clip_index}.wav"
        with wave.open(str(path), "rb") as audio:
            assert (audio.getnchannels(), audio.getframerate(), audio.getsampwidth()) == (
                1,
                16_000,
                2,
            )


def _seed_recording(database_path: Path, recording_id: str) -> None:
    migrate_database(database_path)
    with connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO recordings(
                id, content_sha256, source_path, original_name, size_bytes, duration_ms,
                status, created_at, updated_at
            ) VALUES (
                ?, ?, '/private/source', 'source.m4a', 1, 40000,
                'SPEAKER_REVIEW', 'now', 'now'
            )
            """,
            (recording_id, recording_id.replace("-", "") * 2),
        )
        connection.execute(
            """
            INSERT INTO recording_speakers(
                recording_id, local_speaker_id, speaker_source, revision,
                created_at, updated_at
            ) VALUES (?, 'SPEAKER_00', 'unresolved', 1, 'now', 'now')
            """,
            (recording_id,),
        )
        connection.executemany(
            """
            INSERT INTO segments(
                id, recording_id, start_ms, end_ms, text, local_speaker_id,
                assignment_status, revision
            ) VALUES (?, ?, ?, ?, 'text', 'SPEAKER_00', 'assigned', 1)
            """,
            [
                ("segment-1", recording_id, 0, 4_000),
                ("segment-2", recording_id, 12_000, 16_000),
                ("segment-3", recording_id, 24_000, 28_000),
            ],
        )
