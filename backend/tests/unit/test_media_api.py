from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import pytest
from app.api import create_app
from app.artifacts import write_artifact
from app.config import Settings
from app.db import connect, utc_now
from app.repository import register_recording
from fastapi.testclient import TestClient


def _client_with_audio(settings_values: dict[str, Any]) -> tuple[TestClient, Settings, str, bytes]:
    settings = Settings(**settings_values)
    source = settings.recording_input_dir / "private-original.m4a"
    content = b"0123456789"
    source.write_bytes(content)
    register_recording(
        settings.database_path,
        source,
        "a" * 64,
        len(content),
        1000,
        recording_root=settings.recording_input_dir,
    )
    with connect(settings.database_path) as connection:
        artifact_id = str(
            connection.execute(
                "SELECT id FROM artifacts WHERE kind = 'recording_audio'"
            ).fetchone()["id"]
        )
    return TestClient(create_app(settings)), settings, artifact_id, content


def test_full_media_response_has_audio_headers(settings_values: dict[str, Any]) -> None:
    client, _settings, artifact_id, content = _client_with_audio(settings_values)

    response = client.get(f"/api/media/{artifact_id}")

    assert response.status_code == 200
    assert response.content == content
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-length"] == str(len(content))
    assert response.headers["content-type"] == "audio/mp4"
    assert "private-original" not in response.text


@pytest.mark.parametrize(
    ("range_value", "expected", "content_range"),
    [
        ("bytes=2-5", b"2345", "bytes 2-5/10"),
        ("bytes=7-", b"789", "bytes 7-9/10"),
        ("bytes=-3", b"789", "bytes 7-9/10"),
        ("bytes=8-99", b"89", "bytes 8-9/10"),
    ],
)
def test_single_ranges_return_partial_content(
    settings_values: dict[str, Any],
    range_value: str,
    expected: bytes,
    content_range: str,
) -> None:
    client, _settings, artifact_id, _content = _client_with_audio(settings_values)

    response = client.get(f"/api/media/{artifact_id}", headers={"Range": range_value})

    assert response.status_code == 206
    assert response.content == expected
    assert response.headers["content-range"] == content_range
    assert response.headers["content-length"] == str(len(expected))


@pytest.mark.parametrize(
    "range_value",
    ["items=0-1", "bytes=", "bytes=a-b", "bytes=5-4", "bytes=20-", "bytes=0-1,3-4", "bytes=-0"],
)
def test_invalid_or_unsatisfiable_ranges_return_416(
    settings_values: dict[str, Any], range_value: str
) -> None:
    client, _settings, artifact_id, _content = _client_with_audio(settings_values)

    response = client.get(f"/api/media/{artifact_id}", headers={"Range": range_value})

    assert response.status_code == 416
    assert response.headers["content-range"] == "bytes */10"
    assert response.headers["accept-ranges"] == "bytes"
    assert response.json()["error"]["code"] == "RANGE_NOT_SATISFIABLE"


def test_registered_speaker_clip_is_streamable(settings_values: dict[str, Any]) -> None:
    client, settings, recording_artifact_id, _content = _client_with_audio(settings_values)
    with connect(settings.database_path) as connection:
        recording_id = str(
            connection.execute(
                "SELECT recording_id FROM artifacts WHERE id = ?", (recording_artifact_id,)
            ).fetchone()["recording_id"]
        )
        connection.execute(
            """
            INSERT INTO recording_speakers(
                recording_id, local_speaker_id, speaker_source, revision,
                created_at, updated_at
            ) VALUES (?, 'SPEAKER_00', 'unresolved', 1, ?, ?)
            """,
            (recording_id, utc_now(), utc_now()),
        )
        connection.execute(
            """
            INSERT INTO segments(
                id, recording_id, start_ms, end_ms, text, local_speaker_id,
                assignment_status, revision
            ) VALUES ('segment', ?, 0, 2000, 'text', 'SPEAKER_00', 'assigned', 1)
            """,
            (recording_id,),
        )
    artifact = write_artifact(
        settings.database_path,
        settings.speaker_root,
        recording_id,
        "speaker_clip:SPEAKER_00:0",
        Path(recording_id) / "SPEAKER_00" / "0.wav",
        b"wave-bytes",
        1,
    )
    with connect(settings.database_path) as connection:
        connection.execute(
            """
            INSERT INTO speaker_clips(
                id, recording_id, local_speaker_id, segment_id, artifact_id, revision,
                clip_index, start_ms, end_ms, silence_ratio, created_at
            ) VALUES (?, ?, 'SPEAKER_00', 'segment', ?, 1, 0, 0, 2000, 0.1, ?)
            """,
            (str(uuid.uuid4()), recording_id, artifact.artifact_id, utc_now()),
        )

    response = client.get(f"/api/media/{artifact.artifact_id}")

    assert response.status_code == 200
    assert response.content == b"wave-bytes"
    assert response.headers["content-type"] == "audio/wav"


def test_unregistered_artifact_and_missing_file_return_404(settings_values: dict[str, Any]) -> None:
    client, settings, recording_artifact_id, _content = _client_with_audio(settings_values)
    with connect(settings.database_path) as connection:
        row = connection.execute(
            "SELECT recording_id FROM artifacts WHERE id = ?", (recording_artifact_id,)
        ).fetchone()
    artifact = write_artifact(
        settings.database_path,
        settings.transcript_root,
        str(row["recording_id"]),
        "transcript_json",
        Path("transcript.json"),
        b"private",
        1,
    )

    denied = client.get(f"/api/media/{artifact.artifact_id}")
    (settings.recording_input_dir / "private-original.m4a").unlink()
    missing = client.get(f"/api/media/{recording_artifact_id}")

    assert denied.status_code == 404
    assert missing.status_code == 404


def test_traversal_and_symlink_escape_are_hidden(
    settings_values: dict[str, Any], tmp_path: Path
) -> None:
    client, settings, artifact_id, _content = _client_with_audio(settings_values)
    secret = tmp_path / "private-secret.m4a"
    secret.write_bytes(b"secret")
    link = settings.recording_input_dir / "escape.m4a"
    link.symlink_to(secret)
    with connect(settings.database_path) as connection:
        connection.execute(
            "UPDATE artifacts SET relative_path = '../private-secret.m4a' WHERE id = ?",
            (artifact_id,),
        )
    traversal = client.get(f"/api/media/{artifact_id}")
    with connect(settings.database_path) as connection:
        connection.execute(
            "UPDATE artifacts SET relative_path = 'escape.m4a' WHERE id = ?",
            (artifact_id,),
        )
    symlink = client.get(f"/api/media/{artifact_id}")

    assert traversal.status_code == 404
    assert symlink.status_code == 404
    assert "private-secret" not in traversal.text + symlink.text
