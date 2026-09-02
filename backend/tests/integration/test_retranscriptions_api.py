from __future__ import annotations

import logging
import shutil
import uuid
from pathlib import Path
from typing import Any

from app.adapters import FakeAdapters
from app.api import create_app
from app.config import Settings
from app.db import connect, utc_now
from app.ingest import ingest_file
from app.pipeline import FakePipelineHandler
from app.runtime import process_one_job
from app.schema import Transcript
from fastapi.testclient import TestClient


def _completed(settings: Settings) -> tuple[TestClient, str]:
    source = settings.recording_input_dir / "complete.m4a"
    shutil.copyfile(Path(__file__).parents[1] / "fixtures" / "complete.m4a", source)
    recording_id = ingest_file(settings.database_path, source).recording_id
    handler = FakePipelineHandler(settings, logging.getLogger("test"))
    while process_one_job(settings.database_path, handler, logging.getLogger("test")):
        pass
    return TestClient(create_app(settings)), recording_id


def _request(revision: int = 1) -> dict[str, object]:
    return {
        "expected_revision": revision,
        "language": "en",
        "content_description": "private description",
        "terms": ["private-term"],
        "confirm_impact": True,
    }


def test_retranscription_validates_conflict_duplicate_and_does_not_echo_hints(
    settings_values: dict[str, Any],
) -> None:
    settings = Settings(**settings_values)
    client, recording_id = _completed(settings)

    invalid_language = client.post(
        f"/api/recordings/{recording_id}/retranscriptions",
        json={**_request(), "language": "fr"},
    )
    unconfirmed = client.post(
        f"/api/recordings/{recording_id}/retranscriptions",
        json={**_request(), "confirm_impact": False},
    )
    conflict = client.post(
        f"/api/recordings/{recording_id}/retranscriptions",
        json=_request(9),
    )
    accepted = client.post(f"/api/recordings/{recording_id}/retranscriptions", json=_request())
    duplicate = client.post(f"/api/recordings/{recording_id}/retranscriptions", json=_request())

    assert invalid_language.status_code == 422
    assert unconfirmed.status_code == 422
    assert conflict.status_code == 409
    assert accepted.status_code == 202
    assert accepted.json()["target_revision"] == 2
    assert accepted.json()["job"]["kind"] == "transcribe"
    assert "private description" not in accepted.text
    assert "private-term" not in accepted.text
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "RETRANSCRIPTION_IN_PROGRESS"


def test_fake_retranscription_swaps_atomically_preserves_history_and_clears_hints(
    settings_values: dict[str, Any],
) -> None:
    settings = Settings(**settings_values)
    client, recording_id = _completed(settings)
    person = client.post("/api/persons", json={"display_name": "검토자"}).json()
    with connect(settings.database_path) as connection:
        connection.execute(
            """
            INSERT INTO speaker_match_rejections(
                id, recording_id, local_speaker_id, person_id, model_fingerprint, created_at
            ) VALUES (?, ?, 'SPEAKER_00', ?, 'model:v1', ?)
            """,
            (str(uuid.uuid4()), recording_id, person["id"], utc_now()),
        )
    accepted = client.post(f"/api/recordings/{recording_id}/retranscriptions", json=_request())
    handler = FakePipelineHandler(settings, logging.getLogger("test"))

    assert process_one_job(settings.database_path, handler, logging.getLogger("test"))

    latest = client.get(f"/api/recordings/{recording_id}/retranscriptions/latest")
    assert latest.status_code == 200
    payload = latest.json()
    assert payload["status"] == "succeeded"
    assert payload["previous_language"] == "ko"
    assert payload["new_language"] == "en"
    assert payload["new_segment_count"] == 2
    assert payload["unresolved_speaker_count"] == 2
    assert payload["history_location"] == "app_data/history"
    assert "private" not in latest.text
    assert handler.adapters.last_transcription_options == {
        "language": "en",
        "initial_prompt": "private description\n전문용어: private-term",
    }
    with connect(settings.database_path) as connection:
        recording = connection.execute(
            "SELECT revision, category, needs_speaker_review FROM recordings WHERE id = ?",
            (recording_id,),
        ).fetchone()
        request_row = connection.execute(
            "SELECT content_hint, terms_json FROM retranscription_requests WHERE id = ?",
            (accepted.json()["request_id"],),
        ).fetchone()
        artifact_revisions = {
            row["revision"]
            for row in connection.execute(
                """
                SELECT revision FROM artifacts
                WHERE recording_id = ? AND kind = 'transcript_json'
                """,
                (recording_id,),
            ).fetchall()
        }
        rejection_count = connection.execute(
            "SELECT COUNT(*) FROM speaker_match_rejections WHERE recording_id = ?",
            (recording_id,),
        ).fetchone()[0]
    assert dict(recording) == {"revision": 2, "category": None, "needs_speaker_review": 1}
    assert dict(request_row) == {"content_hint": None, "terms_json": None}
    assert artifact_revisions == {1, 2}
    assert rejection_count == 1
    history = settings.app_data_dir / "history" / recording_id / "1"
    assert (history / "transcript_json.json").is_file()
    assert (history / "transcript_markdown.md").is_file()


def test_manual_category_survives_retranscription_and_automatic_reclassification(
    settings_values: dict[str, Any],
) -> None:
    settings = Settings(**settings_values)
    client, recording_id = _completed(settings)
    handler = FakePipelineHandler(settings, logging.getLogger("test"))
    changed = client.patch(
        f"/api/recordings/{recording_id}/category",
        json={"category": "강의", "expected_revision": 1},
    )
    assert changed.status_code == 200
    assert process_one_job(settings.database_path, handler, logging.getLogger("test"))

    accepted = client.post(
        f"/api/recordings/{recording_id}/retranscriptions",
        json=_request(2),
    )
    assert accepted.status_code == 202
    while process_one_job(settings.database_path, handler, logging.getLogger("test")):
        pass

    detail = client.get(f"/api/recordings/{recording_id}").json()
    assert detail["recording"]["revision"] == 3
    assert detail["recording"]["category"] == "강의"
    assert detail["recording"]["automatic_category"] == "회의"
    assert detail["recording"]["category_source"] == "manual"
    with connect(settings.database_path) as connection:
        path = connection.execute(
            """
            SELECT relative_path FROM artifacts
            WHERE recording_id = ? AND kind = 'transcript_json' AND revision = 3
            """,
            (recording_id,),
        ).fetchone()["relative_path"]
    transcript = Transcript.model_validate_json((settings.transcript_root / path).read_bytes())
    assert transcript.classification_source == "manual"
    assert transcript.classification is not None
    assert transcript.classification.category == "강의"
    assert transcript.classification.confidence is None


class FailingAdapters(FakeAdapters):
    def transcribe(
        self,
        recording_id: str,
        content_sha256: str,
        revision: int,
        *,
        language: str | None = None,
        initial_prompt: str | None = None,
    ) -> Transcript:
        raise ValueError("injected failure")


def test_failed_retranscription_keeps_current_result_and_clears_hints(
    settings_values: dict[str, Any],
) -> None:
    settings = Settings(**settings_values)
    client, recording_id = _completed(settings)
    with connect(settings.database_path) as connection:
        before_segments = connection.execute(
            "SELECT id, text FROM segments WHERE recording_id = ? ORDER BY id",
            (recording_id,),
        ).fetchall()
    accepted = client.post(f"/api/recordings/{recording_id}/retranscriptions", json=_request())
    handler = FakePipelineHandler(settings, logging.getLogger("test"), adapters=FailingAdapters())

    assert process_one_job(settings.database_path, handler, logging.getLogger("test"))

    with connect(settings.database_path) as connection:
        recording = connection.execute(
            "SELECT revision, status FROM recordings WHERE id = ?", (recording_id,)
        ).fetchone()
        after_segments = connection.execute(
            "SELECT id, text FROM segments WHERE recording_id = ? ORDER BY id",
            (recording_id,),
        ).fetchall()
        request_row = connection.execute(
            "SELECT content_hint, terms_json FROM retranscription_requests WHERE id = ?",
            (accepted.json()["request_id"],),
        ).fetchone()
    assert dict(recording) == {"revision": 1, "status": "COMPLETED"}
    assert [tuple(row) for row in after_segments] == [tuple(row) for row in before_segments]
    assert dict(request_row) == {"content_hint": None, "terms_json": None}
