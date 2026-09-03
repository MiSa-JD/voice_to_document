from __future__ import annotations

import json
import logging
import shutil
from contextlib import suppress
from pathlib import Path
from typing import Any

from app.api import create_app
from app.config import Settings
from app.db import connect
from app.ingest import ingest_file
from app.pipeline import FakePipelineHandler
from app.runtime import process_one_job
from app.state import enqueue_job
from fastapi.testclient import TestClient


def _completed_client(
    settings_values: dict[str, Any],
) -> tuple[TestClient, str]:
    settings = Settings(**settings_values)
    source = settings.recording_input_dir / "complete.m4a"
    shutil.copyfile(Path(__file__).parents[1] / "fixtures" / "complete.m4a", source)
    result = ingest_file(settings.database_path, source)
    handler = FakePipelineHandler(settings, logging.getLogger("test"))
    while process_one_job(settings.database_path, handler, logging.getLogger("test")):
        pass
    return TestClient(create_app(settings)), result.recording_id


def test_empty_recording_list(settings_values: dict[str, Any]) -> None:
    response = TestClient(create_app(Settings(**settings_values))).get("/api/recordings")

    assert response.status_code == 200
    assert response.json()["items"] == []
    assert response.json()["total"] == 0
    assert all(count == 0 for count in response.json()["status_counts"].values())


def test_completed_recording_list_and_detail(settings_values: dict[str, Any]) -> None:
    client, recording_id = _completed_client(settings_values)

    listing = client.get("/api/recordings", params={"status": "COMPLETED", "category": "회의"})
    detail = client.get(f"/api/recordings/{recording_id}")

    assert listing.status_code == 200
    assert listing.json()["total"] == 1
    assert listing.json()["items"][0]["id"] == recording_id
    assert listing.json()["status_counts"]["COMPLETED"] == 1
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["recording"]["category"] == "회의"
    assert payload["recording"]["automatic_category"] == "회의"
    assert payload["recording"]["category_source"] == "auto"
    assert payload["allowed_categories"] == ["강의", "일상 대화", "회의", "게임 목록", "기타"]
    assert [segment["local_speaker_id"] for segment in payload["segments"]] == [
        "SPEAKER_00",
        "SPEAKER_01",
    ]
    assert [segment["assignment_status"] for segment in payload["segments"]] == [
        "assigned",
        "assigned",
    ]
    assert all(segment["overlapping_speaker_ids"] == [] for segment in payload["segments"])
    assert [speaker["local_speaker_id"] for speaker in payload["speakers"]] == [
        "SPEAKER_00",
        "SPEAKER_01",
    ]
    assert [speaker["segment_count"] for speaker in payload["speakers"]] == [1, 1]
    assert [speaker["duration_ms"] for speaker in payload["speakers"]] == [900, 900]
    assert all(speaker["speaker_source"] == "unresolved" for speaker in payload["speakers"])
    assert all(
        speaker["match"]["decision"] == "insufficient_clips" for speaker in payload["speakers"]
    )
    assert all(
        speaker["representative_clip_artifact_id"] is None for speaker in payload["speakers"]
    )
    assert {artifact["kind"] for artifact in payload["artifacts"]} == {
        "recording_audio",
        "summary_json",
        "summary_markdown",
        "transcript_json",
        "transcript_markdown",
    }
    assert {job["status"] for job in payload["jobs"]} == {"succeeded"}
    assert len(payload["jobs"]) == 4
    assert payload["summary"]["template"] == "meeting"
    assert "source_path" not in detail.text
    assert "relative_path" not in detail.text


def test_recording_api_uses_common_errors(settings_values: dict[str, Any]) -> None:
    client = TestClient(create_app(Settings(**settings_values)))

    missing = client.get("/api/recordings/not-found")
    category = client.get("/api/recordings", params={"category": "알 수 없음"})
    status = client.get("/api/recordings", params={"status": "UNKNOWN"})

    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "RECORDING_NOT_FOUND"
    assert category.status_code == 422
    assert category.json()["error"]["code"] == "INVALID_CATEGORY"
    assert status.status_code == 422
    assert status.json()["error"]["code"] == "INVALID_REQUEST"


def test_category_update_is_atomic_and_rerenders_applied_category(
    settings_values: dict[str, Any],
) -> None:
    settings = Settings(**settings_values)
    client, recording_id = _completed_client(settings_values)
    handler = FakePipelineHandler(settings, logging.getLogger("test"))
    enqueue_job(settings.database_path, recording_id, "summarize", 1, "test-summary")
    assert process_one_job(settings.database_path, handler, logging.getLogger("test"))
    assert client.get(f"/api/recordings/{recording_id}").json()["summary"] is not None

    changed = client.patch(
        f"/api/recordings/{recording_id}/category",
        json={"category": "강의", "expected_revision": 1},
    )

    assert changed.status_code == 200
    assert changed.json() == {
        "recording_id": recording_id,
        "category": "강의",
        "category_source": "manual",
        "revision": 2,
        "render_job": {
            "id": changed.json()["render_job"]["id"],
            "kind": "render",
            "status": "queued",
            "input_revision": 2,
        },
    }
    with connect(settings.database_path) as connection:
        recording = connection.execute(
            """
            SELECT category, automatic_category, category_source, revision
            FROM recordings WHERE id = ?
            """,
            (recording_id,),
        ).fetchone()
        audit = connection.execute(
            "SELECT details_json FROM audit_events WHERE event_type = 'recording_category_updated'"
        ).fetchone()
    assert dict(recording) == {
        "category": "강의",
        "automatic_category": "회의",
        "category_source": "manual",
        "revision": 2,
    }
    assert json.loads(audit["details_json"]) == {
        "after": "강의",
        "before": "회의",
        "revision": 2,
    }
    assert client.get(f"/api/recordings/{recording_id}").json()["summary"] is None

    assert process_one_job(settings.database_path, handler, logging.getLogger("test"))
    with connect(settings.database_path) as connection:
        queued_summary = connection.execute(
            """
            SELECT input_revision FROM jobs
            WHERE recording_id = ? AND kind = 'summarize' AND status = 'queued'
            """,
            (recording_id,),
        ).fetchone()
    assert queued_summary["input_revision"] == 2
    detail = client.get(f"/api/recordings/{recording_id}").json()
    artifact = next(
        item
        for item in detail["artifacts"]
        if item["kind"] == "transcript_json" and item["revision"] == 2
    )
    assert artifact["revision"] == detail["recording"]["revision"] == 2
    with connect(settings.database_path) as connection:
        path = connection.execute(
            """
            SELECT relative_path FROM artifacts
            WHERE recording_id = ? AND kind = 'transcript_json' AND revision = 2
            """,
            (recording_id,),
        ).fetchone()["relative_path"]
    transcript = json.loads((settings.transcript_root / path).read_text())
    markdown = next(settings.document_root.glob("*.md")).read_text()
    assert transcript["classification"]["category"] == "강의"
    assert transcript["classification_source"] == "manual"
    assert "Revision: 2" in markdown
    assert "Category: 강의" in markdown
    assert "Category Source: manual" in markdown


def test_category_update_rejects_invalid_state_and_conflicts(
    settings_values: dict[str, Any],
) -> None:
    settings = Settings(**settings_values)
    client, recording_id = _completed_client(settings_values)

    cases = [
        ({"category": "알 수 없음", "expected_revision": 1}, 422, "INVALID_CATEGORY"),
        ({"category": "회의", "expected_revision": 1}, 422, "CATEGORY_UNCHANGED"),
        ({"category": "강의", "expected_revision": 2}, 409, "REVISION_CONFLICT"),
    ]
    for request, status, code in cases:
        response = client.patch(f"/api/recordings/{recording_id}/category", json=request)
        assert response.status_code == status
        assert response.json()["error"]["code"] == code

    missing = client.patch(
        "/api/recordings/missing/category",
        json={"category": "강의", "expected_revision": 1},
    )
    assert missing.status_code == 404

    with connect(settings.database_path) as connection:
        connection.execute("UPDATE recordings SET category = NULL WHERE id = ?", (recording_id,))
    unclassified = client.patch(
        f"/api/recordings/{recording_id}/category",
        json={"category": "강의", "expected_revision": 1},
    )
    assert unclassified.status_code == 422
    assert unclassified.json()["error"]["code"] == "CATEGORY_NOT_CLASSIFIED"


def test_category_update_rejects_each_active_related_job(
    settings_values: dict[str, Any],
) -> None:
    settings = Settings(**settings_values)
    for kind, expected_code in (
        ("classify", "CLASSIFICATION_IN_PROGRESS"),
        ("render", "RENDER_IN_PROGRESS"),
        ("summarize", "SUMMARY_IN_PROGRESS"),
    ):
        client, recording_id = _completed_client(settings_values)
        with connect(settings.database_path) as connection:
            connection.execute(
                """
                INSERT INTO jobs(
                    id, recording_id, kind, status, attempts, available_at, created_at,
                    updated_at, input_revision, settings_fingerprint
                ) VALUES (?, ?, ?, 'queued', 0, 'now', 'now', 'now', 1, ?)
                """,
                (f"active-{kind}", recording_id, kind, f"test-{kind}"),
            )
        response = client.patch(
            f"/api/recordings/{recording_id}/category",
            json={"category": "강의", "expected_revision": 1},
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == expected_code
        with connect(settings.database_path) as connection:
            connection.execute(
                "UPDATE jobs SET status = 'failed' WHERE id = ?", (f"active-{kind}",)
            )


def test_category_update_rolls_back_when_audit_insert_fails(
    settings_values: dict[str, Any],
) -> None:
    settings = Settings(**settings_values)
    client, recording_id = _completed_client(settings_values)
    with connect(settings.database_path) as connection:
        connection.execute(
            """
            CREATE TRIGGER fail_category_audit BEFORE INSERT ON audit_events
            WHEN NEW.event_type = 'recording_category_updated'
            BEGIN SELECT RAISE(FAIL, 'injected audit failure'); END
            """
        )
    with suppress(Exception):
        client.patch(
            f"/api/recordings/{recording_id}/category",
            json={"category": "강의", "expected_revision": 1},
        )
    with connect(settings.database_path) as connection:
        recording = connection.execute(
            "SELECT category, category_source, revision FROM recordings WHERE id = ?",
            (recording_id,),
        ).fetchone()
        render_count = connection.execute(
            "SELECT COUNT(*) FROM jobs WHERE recording_id = ? AND kind = 'render'",
            (recording_id,),
        ).fetchone()[0]
    assert dict(recording) == {"category": "회의", "category_source": "auto", "revision": 1}
    assert render_count == 0
