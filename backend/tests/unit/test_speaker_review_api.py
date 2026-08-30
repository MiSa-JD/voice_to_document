from __future__ import annotations

import json
import uuid
from typing import Any, cast

from app.api import create_app
from app.config import Settings
from app.db import connect, utc_now
from app.repository import register_recording
from fastapi.testclient import TestClient


def _seed_recording(settings: Settings, suffix: str = "one") -> tuple[str, list[str]]:
    source = settings.recording_input_dir / f"{suffix}.m4a"
    source.write_bytes(suffix.encode())
    result = register_recording(
        settings.database_path,
        source,
        (suffix.encode().hex() + "0" * 64)[:64],
        source.stat().st_size,
        10_000,
        recording_root=settings.recording_input_dir,
    )
    segment_ids = [str(uuid.uuid4()) for _ in range(3)]
    timestamp = utc_now()
    with connect(settings.database_path) as connection:
        connection.executemany(
            """
            INSERT INTO recording_speakers(
                recording_id, local_speaker_id, speaker_source, speaker_score,
                revision, created_at, updated_at
            ) VALUES (?, ?, 'auto', 0.9, 1, ?, ?)
            """,
            [
                (result.recording_id, "SPEAKER_00", timestamp, timestamp),
                (result.recording_id, "SPEAKER_01", timestamp, timestamp),
            ],
        )
        connection.executemany(
            """
            INSERT INTO segments(
                id, recording_id, start_ms, end_ms, text, local_speaker_id,
                assignment_status, overlapping_speaker_ids_json,
                speaker_source, speaker_score, revision
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'auto', 0.8, 1)
            """,
            [
                (
                    segment_ids[0],
                    result.recording_id,
                    0,
                    2000,
                    "private transcript alpha",
                    "SPEAKER_00",
                    "assigned",
                    "[]",
                ),
                (
                    segment_ids[1],
                    result.recording_id,
                    3000,
                    5000,
                    "private transcript beta",
                    "SPEAKER_00",
                    "overlap",
                    '["SPEAKER_00", "SPEAKER_01"]',
                ),
                (
                    segment_ids[2],
                    result.recording_id,
                    6000,
                    8000,
                    "private transcript gamma",
                    "SPEAKER_01",
                    "assigned",
                    "[]",
                ),
            ],
        )
    return result.recording_id, segment_ids


def _client(settings_values: dict[str, Any]) -> tuple[TestClient, Settings]:
    settings = Settings(**settings_values)
    return TestClient(create_app(settings)), settings


def _create_person(client: TestClient, name: str = "홍길동") -> dict[str, Any]:
    response = client.post("/api/persons", json={"display_name": name})
    assert response.status_code == 201
    return cast(dict[str, Any], response.json())


def test_person_create_list_duplicate_names_and_trim(settings_values: dict[str, Any]) -> None:
    client, _settings = _client(settings_values)

    first = _create_person(client, "  같은 이름  ")
    second = _create_person(client, "같은 이름")
    listing = client.get("/api/persons")

    assert first["display_name"] == "같은 이름"
    assert second["display_name"] == "같은 이름"
    assert first["id"] != second["id"]
    assert listing.status_code == 200
    assert listing.json()["total"] == 2
    assert {item["id"] for item in listing.json()["items"]} == {first["id"], second["id"]}


def test_person_name_validation_and_revision_conflict(settings_values: dict[str, Any]) -> None:
    client, _settings = _client(settings_values)
    person = _create_person(client)

    blank = client.post("/api/persons", json={"display_name": "   "})
    too_long = client.post("/api/persons", json={"display_name": "가" * 101})
    updated = client.patch(
        f"/api/persons/{person['id']}",
        json={"display_name": " 새 이름 ", "expected_revision": 1},
    )
    conflict = client.patch(
        f"/api/persons/{person['id']}",
        json={"display_name": "충돌", "expected_revision": 1},
    )
    missing = client.patch(
        "/api/persons/missing",
        json={"display_name": "없음", "expected_revision": 1},
    )

    assert blank.status_code == 422
    assert too_long.status_code == 422
    assert updated.json()["display_name"] == "새 이름"
    assert updated.json()["revision"] == 2
    assert conflict.status_code == 409
    assert conflict.json()["error"] == {
        "code": "REVISION_CONFLICT",
        "message": "다른 변경이 먼저 저장되었습니다.",
        "details": {"current_revision": 2},
    }
    assert missing.status_code == 404


def test_recording_speaker_assignment_updates_primary_segments_only(
    settings_values: dict[str, Any],
) -> None:
    client, settings = _client(settings_values)
    recording_id, segment_ids = _seed_recording(settings)
    person = _create_person(client)

    response = client.put(
        f"/api/recordings/{recording_id}/speakers/SPEAKER_00",
        json={"person_id": person["id"], "expected_revision": 1},
    )

    assert response.status_code == 200
    payload = response.json()
    assert {
        key: payload[key]
        for key in (
            "recording_id",
            "recording_revision",
            "person_id",
            "speaker_name",
            "updated_segment_count",
        )
    } == {
        "recording_id": recording_id,
        "recording_revision": 2,
        "person_id": person["id"],
        "speaker_name": "홍길동",
        "updated_segment_count": 2,
    }
    assert payload["render_job"] == {
        "id": payload["render_job"]["id"],
        "kind": "render",
        "status": "queued",
        "input_revision": 2,
    }
    with connect(settings.database_path) as connection:
        recording = connection.execute(
            "SELECT revision FROM recordings WHERE id = ?", (recording_id,)
        ).fetchone()
        speaker = connection.execute(
            """
            SELECT person_id, speaker_source, speaker_score, revision
            FROM recording_speakers
            WHERE recording_id = ? AND local_speaker_id = 'SPEAKER_00'
            """,
            (recording_id,),
        ).fetchone()
        segments = connection.execute(
            """
            SELECT id, local_speaker_id, assignment_status, overlapping_speaker_ids_json,
                   person_id, speaker_source, speaker_score, revision
            FROM segments WHERE recording_id = ? ORDER BY start_ms
            """,
            (recording_id,),
        ).fetchall()
    assert recording["revision"] == 2
    assert dict(speaker) == {
        "person_id": person["id"],
        "speaker_source": "manual",
        "speaker_score": None,
        "revision": 2,
    }
    assert [row["person_id"] for row in segments] == [person["id"], person["id"], None]
    assert [row["speaker_source"] for row in segments] == ["manual", "manual", "auto"]
    assert segments[1]["assignment_status"] == "overlap"
    assert json.loads(segments[1]["overlapping_speaker_ids_json"]) == [
        "SPEAKER_00",
        "SPEAKER_01",
    ]
    assert [row["id"] for row in segments] == segment_ids


def test_explicit_unknown_is_manual_and_clears_score(settings_values: dict[str, Any]) -> None:
    client, settings = _client(settings_values)
    recording_id, _segment_ids = _seed_recording(settings)

    response = client.put(
        f"/api/recordings/{recording_id}/speakers/SPEAKER_01",
        json={"person_id": None, "expected_revision": 1},
    )

    assert response.status_code == 200
    with connect(settings.database_path) as connection:
        speaker = connection.execute(
            """
            SELECT person_id, speaker_source, speaker_score FROM recording_speakers
            WHERE recording_id = ? AND local_speaker_id = 'SPEAKER_01'
            """,
            (recording_id,),
        ).fetchone()
        segment = connection.execute(
            """
            SELECT person_id, speaker_source, speaker_score FROM segments
            WHERE recording_id = ? AND local_speaker_id = 'SPEAKER_01'
            """,
            (recording_id,),
        ).fetchone()
    expected = {"person_id": None, "speaker_source": "manual", "speaker_score": None}
    assert dict(speaker) == expected
    assert dict(segment) == expected


def test_individual_segment_assignment_preserves_diarization_fields(
    settings_values: dict[str, Any],
) -> None:
    client, settings = _client(settings_values)
    recording_id, segment_ids = _seed_recording(settings)
    person = _create_person(client)

    response = client.patch(
        f"/api/segments/{segment_ids[1]}/speaker",
        json={"person_id": person["id"], "expected_revision": 1},
    )

    assert response.status_code == 200
    assert response.json()["recording_revision"] == 2
    with connect(settings.database_path) as connection:
        row = connection.execute(
            """
            SELECT local_speaker_id, assignment_status, overlapping_speaker_ids_json,
                   person_id, speaker_source, speaker_score, revision
            FROM segments WHERE id = ?
            """,
            (segment_ids[1],),
        ).fetchone()
        speaker = connection.execute(
            """
            SELECT person_id, speaker_source FROM recording_speakers
            WHERE recording_id = ? AND local_speaker_id = 'SPEAKER_00'
            """,
            (recording_id,),
        ).fetchone()
    assert row["local_speaker_id"] == "SPEAKER_00"
    assert row["assignment_status"] == "overlap"
    assert json.loads(row["overlapping_speaker_ids_json"]) == ["SPEAKER_00", "SPEAKER_01"]
    assert (row["person_id"], row["speaker_source"], row["speaker_score"], row["revision"]) == (
        person["id"],
        "manual",
        None,
        2,
    )
    assert dict(speaker) == {"person_id": None, "speaker_source": "auto"}


def test_batch_assignment_updates_once_and_rejects_duplicates_or_mixed_recordings(
    settings_values: dict[str, Any],
) -> None:
    client, settings = _client(settings_values)
    recording_id, segment_ids = _seed_recording(settings, "first")
    other_recording_id, other_segments = _seed_recording(settings, "second")
    person = _create_person(client)

    duplicate = client.patch(
        "/api/segments/speakers",
        json={
            "recording_id": recording_id,
            "segment_ids": [segment_ids[0], segment_ids[0]],
            "person_id": person["id"],
            "expected_revision": 1,
        },
    )
    too_many = client.patch(
        "/api/segments/speakers",
        json={
            "recording_id": recording_id,
            "segment_ids": [str(index) for index in range(501)],
            "person_id": person["id"],
            "expected_revision": 1,
        },
    )
    mixed = client.patch(
        "/api/segments/speakers",
        json={
            "recording_id": recording_id,
            "segment_ids": [segment_ids[0], other_segments[0]],
            "person_id": person["id"],
            "expected_revision": 1,
        },
    )
    applied = client.patch(
        "/api/segments/speakers",
        json={
            "recording_id": recording_id,
            "segment_ids": segment_ids[:2],
            "person_id": person["id"],
            "expected_revision": 1,
        },
    )

    assert duplicate.status_code == 422
    assert too_many.status_code == 422
    assert mixed.status_code == 422
    assert mixed.json()["error"]["code"] == "SEGMENTS_RECORDING_MISMATCH"
    assert applied.status_code == 200
    assert applied.json()["recording_revision"] == 2
    assert applied.json()["updated_segment_count"] == 2
    with connect(settings.database_path) as connection:
        revisions = {
            row["id"]: row["revision"]
            for row in connection.execute(
                "SELECT id, revision FROM recordings WHERE id IN (?, ?)",
                (recording_id, other_recording_id),
            ).fetchall()
        }
    assert revisions == {recording_id: 2, other_recording_id: 1}


def test_revision_and_missing_targets_do_not_mutate(settings_values: dict[str, Any]) -> None:
    client, settings = _client(settings_values)
    recording_id, segment_ids = _seed_recording(settings)

    conflict = client.patch(
        f"/api/segments/{segment_ids[0]}/speaker",
        json={"person_id": None, "expected_revision": 9},
    )
    missing_person = client.patch(
        f"/api/segments/{segment_ids[0]}/speaker",
        json={"person_id": "missing", "expected_revision": 1},
    )
    missing_speaker = client.put(
        f"/api/recordings/{recording_id}/speakers/SPEAKER_99",
        json={"person_id": None, "expected_revision": 1},
    )
    missing_segment = client.patch(
        "/api/segments/missing/speaker",
        json={"person_id": None, "expected_revision": 1},
    )

    assert conflict.status_code == 409
    assert missing_person.status_code == 404
    assert missing_speaker.status_code == 404
    assert missing_segment.status_code == 404
    with connect(settings.database_path) as connection:
        revision = connection.execute(
            "SELECT revision FROM recordings WHERE id = ?", (recording_id,)
        ).fetchone()["revision"]
        event_count = connection.execute(
            "SELECT COUNT(*) FROM audit_events WHERE recording_id = ?", (recording_id,)
        ).fetchone()[0]
    assert revision == 1
    assert event_count == 0


def test_audit_failure_rolls_back_batch_transaction(settings_values: dict[str, Any]) -> None:
    _client_value, settings = _client(settings_values)
    recording_id, segment_ids = _seed_recording(settings)
    with connect(settings.database_path) as connection:
        connection.execute(
            """
            CREATE TRIGGER fail_speaker_audit
            BEFORE INSERT ON audit_events
            WHEN NEW.event_type = 'segments_speaker_assigned'
            BEGIN SELECT RAISE(ABORT, 'injected audit failure'); END
            """
        )
    client = TestClient(create_app(settings), raise_server_exceptions=False)

    response = client.patch(
        "/api/segments/speakers",
        json={
            "recording_id": recording_id,
            "segment_ids": segment_ids[:2],
            "person_id": None,
            "expected_revision": 1,
        },
    )

    assert response.status_code == 500
    with connect(settings.database_path) as connection:
        revision = connection.execute(
            "SELECT revision FROM recordings WHERE id = ?", (recording_id,)
        ).fetchone()["revision"]
        sources = connection.execute(
            "SELECT DISTINCT speaker_source FROM segments WHERE recording_id = ?",
            (recording_id,),
        ).fetchall()
    assert revision == 1
    assert [row["speaker_source"] for row in sources] == ["auto"]


def test_person_rename_is_immediately_visible_and_audit_omits_transcript(
    settings_values: dict[str, Any],
) -> None:
    client, settings = _client(settings_values)
    recording_id, segment_ids = _seed_recording(settings)
    person = _create_person(client, "이전 이름")
    assigned = client.patch(
        f"/api/segments/{segment_ids[0]}/speaker",
        json={"person_id": person["id"], "expected_revision": 1},
    )
    assert assigned.status_code == 200
    with connect(settings.database_path) as connection:
        connection.execute(
            "UPDATE jobs SET status = 'succeeded' WHERE id = ?",
            (assigned.json()["render_job"]["id"],),
        )
    renamed = client.patch(
        f"/api/persons/{person['id']}",
        json={"display_name": "최신 이름", "expected_revision": 1},
    )
    assert renamed.status_code == 200
    assert renamed.json()["affected_recordings"][0]["recording_revision"] == 3

    detail = client.get(f"/api/recordings/{recording_id}")

    segment = next(item for item in detail.json()["segments"] if item["id"] == segment_ids[0])
    assert segment["speaker_name"] == "최신 이름"
    assert segment["speaker_source"] == "manual"
    assert segment["speaker_score"] is None
    with connect(settings.database_path) as connection:
        events = connection.execute(
            "SELECT event_type, details_json FROM audit_events ORDER BY created_at, id"
        ).fetchall()
    audit_text = "\n".join(str(row["details_json"]) for row in events)
    assert {row["event_type"] for row in events} == {
        "person_created",
        "person_updated",
        "segment_speaker_assigned",
    }
    assert "private transcript" not in audit_text
    assert "최신 이름" not in audit_text
