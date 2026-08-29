from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

from app.api import create_app
from app.config import Settings
from app.ingest import ingest_file
from app.pipeline import FakePipelineHandler
from app.runtime import process_one_job
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
    assert [segment["local_speaker_id"] for segment in payload["segments"]] == [
        "SPEAKER_00",
        "SPEAKER_01",
    ]
    assert [segment["assignment_status"] for segment in payload["segments"]] == [
        "assigned",
        "assigned",
    ]
    assert all(segment["overlapping_speaker_ids"] == [] for segment in payload["segments"])
    assert {artifact["kind"] for artifact in payload["artifacts"]} == {
        "recording_audio",
        "transcript_json",
        "transcript_markdown",
    }
    assert {job["status"] for job in payload["jobs"]} == {"succeeded"}
    assert len(payload["jobs"]) == 2
    assert payload["summary"] is None
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
