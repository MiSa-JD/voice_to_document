from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

import pytest
from app.api import create_app
from app.config import Settings
from app.db import connect
from app.ingest import ingest_file
from app.pipeline import FakePipelineHandler
from app.runtime import process_one_job
from fastapi.testclient import TestClient


def _completed(settings_values: dict[str, Any]) -> tuple[Settings, TestClient, str]:
    settings = Settings(**settings_values)
    source = settings.recording_input_dir / "complete.m4a"
    shutil.copyfile(Path(__file__).parents[1] / "fixtures" / "complete.m4a", source)
    recording_id = ingest_file(settings.database_path, source).recording_id
    handler = FakePipelineHandler(settings, logging.getLogger("test"))
    while process_one_job(settings.database_path, handler, logging.getLogger("test")):
        pass
    return settings, TestClient(create_app(settings)), recording_id


def _finish(settings: Settings) -> None:
    handler = FakePipelineHandler(settings, logging.getLogger("test"))
    while process_one_job(settings.database_path, handler, logging.getLogger("test")):
        pass


@pytest.mark.parametrize("scope", ["recording", "segment"])
def test_speaker_assignment_hides_stale_summary_and_regenerates_once(
    settings_values: dict[str, Any], scope: str
) -> None:
    settings, client, recording_id = _completed(settings_values)
    detail = client.get(f"/api/recordings/{recording_id}").json()
    person = client.post("/api/persons", json={"display_name": "검토자"}).json()
    if scope == "recording":
        changed = client.put(
            f"/api/recordings/{recording_id}/speakers/SPEAKER_00",
            json={"person_id": person["id"], "expected_revision": 1},
        )
    else:
        changed = client.patch(
            "/api/segments/speakers",
            json={
                "recording_id": recording_id,
                "segment_ids": [detail["segments"][0]["id"]],
                "person_id": person["id"],
                "expected_revision": 1,
            },
        )
    assert changed.status_code == 200
    stale = client.get(f"/api/recordings/{recording_id}").json()
    assert stale["recording"]["revision"] == 2
    assert stale["summary_status"] == "stale"
    assert stale["summary"] is None

    _finish(settings)

    latest = client.get(f"/api/recordings/{recording_id}").json()
    assert latest["summary_status"] == "succeeded"
    assert latest["summary"] is not None
    with connect(settings.database_path) as connection:
        count = connection.execute(
            """
            SELECT COUNT(*) FROM jobs
            WHERE recording_id = ? AND kind = 'summarize' AND input_revision = 2
            """,
            (recording_id,),
        ).fetchone()[0]
    assert count == 1


def test_person_name_change_regenerates_each_affected_summary_once(
    settings_values: dict[str, Any],
) -> None:
    settings, client, recording_id = _completed(settings_values)
    person = client.post("/api/persons", json={"display_name": "이전 이름"}).json()
    client.put(
        f"/api/recordings/{recording_id}/speakers/SPEAKER_00",
        json={"person_id": person["id"], "expected_revision": 1},
    )
    _finish(settings)

    changed = client.patch(
        f"/api/persons/{person['id']}",
        json={"display_name": "새 이름", "expected_revision": 1},
    )

    assert changed.status_code == 200
    stale = client.get(f"/api/recordings/{recording_id}").json()
    assert stale["recording"]["revision"] == 3
    assert stale["summary_status"] == "stale"
    assert stale["summary"] is None
    _finish(settings)
    latest = client.get(f"/api/recordings/{recording_id}").json()
    assert latest["summary_status"] == "succeeded"
    assert latest["recording"]["revision"] == 3


@pytest.mark.parametrize(
    ("category", "expected_summary"),
    [("일상 대화", False), ("강의", True)],
)
def test_category_edit_preserves_manual_policy_and_auto_policy(
    settings_values: dict[str, Any], category: str, expected_summary: bool
) -> None:
    values = {**settings_values, "AUTO_SUMMARY_CATEGORIES": "강의"}
    settings, client, recording_id = _completed(values)
    before = client.get(f"/api/recordings/{recording_id}").json()
    assert before["summary_status"] == "not_requested"

    changed = client.patch(
        f"/api/recordings/{recording_id}/category",
        json={"category": category, "expected_revision": 1},
    )

    assert changed.status_code == 200
    _finish(settings)
    latest = client.get(f"/api/recordings/{recording_id}").json()
    assert (latest["summary"] is not None) is expected_summary
    assert latest["summary_policy"] == ("automatic" if expected_summary else "manual")
    with connect(settings.database_path) as connection:
        count = connection.execute(
            """
            SELECT COUNT(*) FROM jobs
            WHERE recording_id = ? AND kind = 'summarize' AND input_revision = 2
            """,
            (recording_id,),
        ).fetchone()[0]
    assert count == int(expected_summary)
