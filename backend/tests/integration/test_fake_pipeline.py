from __future__ import annotations

import json
import logging
import shutil
import urllib.request
from pathlib import Path
from typing import Any

from app.api import create_app
from app.config import Settings
from app.db import connect
from app.ingest import ingest_file
from app.openai_classification import OpenAIClassificationAdapter
from app.pipeline import FakePipelineHandler
from app.runtime import process_one_job
from app.state import enqueue_job
from fastapi.testclient import TestClient


def _openai_response() -> bytes:
    classification = json.dumps(
        {
            "schema_version": 1,
            "category": "회의",
            "confidence": 0.95,
            "reason": "안건과 결정이 포함되어 있습니다.",
        },
        ensure_ascii=False,
    )
    return json.dumps(
        {
            "status": "completed",
            "output": [{"content": [{"type": "output_text", "text": classification}]}],
        }
    ).encode()


def test_fake_speech_with_openai_document_writes_json_and_markdown(
    settings_values: dict[str, Any],
) -> None:
    settings = Settings(**settings_values)
    source = settings.recording_input_dir / "complete.m4a"
    shutil.copyfile(Path(__file__).parents[1] / "fixtures" / "complete.m4a", source)
    recording_id = ingest_file(settings.database_path, source).recording_id
    requests: list[urllib.request.Request] = []

    def transport(request: urllib.request.Request, _timeout: float) -> bytes:
        requests.append(request)
        return _openai_response()

    handler = FakePipelineHandler(
        settings,
        logging.getLogger("test"),
        classification_adapter=OpenAIClassificationAdapter(
            base_url="https://api.openai.com/v1",
            api_key="test-key",
            model="test-snapshot",
            transport=transport,
        ),
    )

    while process_one_job(settings.database_path, handler, logging.getLogger("test")):
        pass

    with connect(settings.database_path) as connection:
        recording = connection.execute(
            "SELECT status, category FROM recordings WHERE id = ?", (recording_id,)
        ).fetchone()
        artifacts = connection.execute(
            "SELECT kind, relative_path FROM artifacts WHERE recording_id = ?", (recording_id,)
        ).fetchall()
    assert dict(recording) == {"status": "COMPLETED", "category": "회의"}
    assert len(requests) == 1
    assert {row["kind"] for row in artifacts} == {
        "recording_audio",
        "transcript_json",
        "transcript_markdown",
    }
    json_path = next(row["relative_path"] for row in artifacts if row["kind"] == "transcript_json")
    markdown_path = next(
        row["relative_path"] for row in artifacts if row["kind"] == "transcript_markdown"
    )
    payload = json.loads((settings.transcript_root / json_path).read_text())
    assert payload["classification_fingerprint"]["provider"] == "openai_compatible"
    assert "Category: 회의" in (settings.document_root / markdown_path).read_text()


def test_complete_fixture_reaches_completed_with_revision_matched_artifacts(
    tmp_path: Path,
    settings_values: dict[str, Any],
) -> None:
    settings = Settings(**settings_values)
    source = Path(settings.recording_input_dir) / "complete.m4a"
    shutil.copyfile(Path(__file__).parents[1] / "fixtures" / "complete.m4a", source)
    result = ingest_file(settings.database_path, source)
    handler = FakePipelineHandler(settings, logging.getLogger("test"))

    while process_one_job(settings.database_path, handler, logging.getLogger("test")):
        pass

    with connect(settings.database_path) as connection:
        recording = connection.execute(
            "SELECT status, category FROM recordings WHERE id = ?", (result.recording_id,)
        ).fetchone()
        jobs = connection.execute("SELECT kind, status FROM jobs ORDER BY created_at").fetchall()
        artifacts = connection.execute(
            "SELECT kind, relative_path, schema_version, revision FROM artifacts ORDER BY kind"
        ).fetchall()
    assert dict(recording) == {"status": "COMPLETED", "category": "회의"}
    assert [dict(job) for job in jobs] == [
        {"kind": "transcribe", "status": "succeeded"},
        {"kind": "finalize_speakers", "status": "succeeded"},
        {"kind": "classify", "status": "succeeded"},
    ]
    assert [row["kind"] for row in artifacts] == [
        "recording_audio",
        "transcript_json",
        "transcript_markdown",
    ]
    assert {row["revision"] for row in artifacts} == {1}
    assert {row["schema_version"] for row in artifacts} == {1, 2}
    json_artifact = next(row for row in artifacts if row["kind"] == "transcript_json")
    markdown_artifact = next(row for row in artifacts if row["kind"] == "transcript_markdown")
    transcript_json = settings.transcript_root / json_artifact["relative_path"]
    transcript_markdown = settings.document_root / markdown_artifact["relative_path"]
    json_text = transcript_json.read_text()
    assert '"classification"' in json_text
    assert '"classification_fingerprint"' in json_text
    assert "Revision: 1" in transcript_markdown.read_text()
    assert "SPEAKER_00" in transcript_markdown.read_text()

    assert not process_one_job(settings.database_path, handler, logging.getLogger("test"))
    with connect(settings.database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0] == 3


def test_review_fixture_keeps_flag_but_generates_temporary_speaker_markdown(
    tmp_path: Path,
    settings_values: dict[str, Any],
) -> None:
    settings = Settings(**settings_values)
    source = Path(settings.recording_input_dir) / "speaker-review.m4a"
    shutil.copyfile(Path(__file__).parents[1] / "fixtures" / "speaker-review.m4a", source)
    result = ingest_file(settings.database_path, source)
    handler = FakePipelineHandler(settings, logging.getLogger("test"))

    while process_one_job(settings.database_path, handler, logging.getLogger("test")):
        pass

    with connect(settings.database_path) as connection:
        recording = connection.execute(
            "SELECT status, needs_speaker_review FROM recordings WHERE id = ?",
            (result.recording_id,),
        ).fetchone()
        jobs = connection.execute("SELECT kind, status FROM jobs ORDER BY created_at").fetchall()
        artifact = connection.execute(
            "SELECT relative_path FROM artifacts WHERE kind = 'transcript_markdown'"
        ).fetchone()
    assert dict(recording) == {"status": "COMPLETED", "needs_speaker_review": 1}
    assert [dict(row) for row in jobs] == [
        {"kind": "transcribe", "status": "succeeded"},
        {"kind": "finalize_speakers", "status": "succeeded"},
        {"kind": "classify", "status": "succeeded"},
    ]
    markdown = (settings.document_root / artifact["relative_path"]).read_text()
    assert "SPEAKER_00" in markdown
    assert "SPEAKER_01" in markdown


def test_renderer_failure_preserves_json_without_markdown_registration(
    settings_values: dict[str, Any],
) -> None:
    settings = Settings(**settings_values)
    source = settings.recording_input_dir / "complete.m4a"
    shutil.copyfile(Path(__file__).parents[1] / "fixtures" / "complete.m4a", source)
    result = ingest_file(settings.database_path, source)

    def fail_renderer(_transcript: object) -> bytes:
        raise RuntimeError("injected renderer failure")

    handler = FakePipelineHandler(
        settings,
        logging.getLogger("test"),
        markdown_renderer=fail_renderer,
    )
    while process_one_job(settings.database_path, handler, logging.getLogger("test")):
        pass

    with connect(settings.database_path) as connection:
        recording = connection.execute(
            "SELECT status, last_error_code FROM recordings WHERE id = ?", (result.recording_id,)
        ).fetchone()
        artifacts = connection.execute(
            "SELECT kind, relative_path FROM artifacts WHERE recording_id = ?",
            (result.recording_id,),
        ).fetchall()
    assert dict(recording) == {
        "status": "FAILED",
        "last_error_code": "TRANSCRIPT_RENDER_ERROR",
    }
    assert [row["kind"] for row in artifacts] == ["recording_audio", "transcript_json"]
    assert not list(settings.document_root.rglob("*.md"))
    transcript_artifact = next(row for row in artifacts if row["kind"] == "transcript_json")
    payload = (settings.transcript_root / transcript_artifact["relative_path"]).read_text(
        encoding="utf-8"
    )
    assert '"classification"' in payload


def test_duplicate_input_and_handler_restart_keep_one_artifact_per_kind(
    settings_values: dict[str, Any],
) -> None:
    settings = Settings(**settings_values)
    source = settings.recording_input_dir / "first.m4a"
    duplicate = settings.recording_input_dir / "duplicate.m4a"
    fixture = Path(__file__).parents[1] / "fixtures" / "complete.m4a"
    shutil.copyfile(fixture, source)
    registration = ingest_file(settings.database_path, source)
    first_handler = FakePipelineHandler(settings, logging.getLogger("test"))
    while process_one_job(settings.database_path, first_handler, logging.getLogger("test")):
        pass

    shutil.copyfile(fixture, duplicate)
    duplicate_registration = ingest_file(settings.database_path, duplicate)
    restarted_handler = FakePipelineHandler(settings, logging.getLogger("test"))
    assert not process_one_job(settings.database_path, restarted_handler, logging.getLogger("test"))

    assert duplicate_registration.recording_id == registration.recording_id
    assert duplicate_registration.created is False
    with connect(settings.database_path) as connection:
        rows = connection.execute(
            """
            SELECT kind, revision, COUNT(*) AS count FROM artifacts
            GROUP BY kind, revision ORDER BY kind
            """
        ).fetchall()
    assert [dict(row) for row in rows] == [
        {"kind": "recording_audio", "revision": 1, "count": 1},
        {"kind": "transcript_json", "revision": 1, "count": 1},
        {"kind": "transcript_markdown", "revision": 1, "count": 1},
    ]


def test_unknown_private_hash_uses_local_fallback_without_external_provider(
    settings_values: dict[str, Any],
) -> None:
    settings = Settings(**settings_values)
    handler = FakePipelineHandler(settings, logging.getLogger("test"))
    response = handler._fake_classification_response("f" * 64)

    assert response == {
        "schema_version": 1,
        "category": settings.categories[-1],
        "confidence": 0.0,
        "reason": "local deterministic fallback",
    }


def test_speaker_edit_rerenders_without_retranscription_and_refreshes_summary(
    settings_values: dict[str, Any],
) -> None:
    settings = Settings(**settings_values)
    source = settings.recording_input_dir / "complete.m4a"
    shutil.copyfile(Path(__file__).parents[1] / "fixtures" / "complete.m4a", source)
    recording_id = ingest_file(settings.database_path, source).recording_id
    handler = FakePipelineHandler(settings, logging.getLogger("test"))
    while process_one_job(settings.database_path, handler, logging.getLogger("test")):
        pass
    enqueue_job(settings.database_path, recording_id, "summarize", 1, "test-summary")
    assert process_one_job(settings.database_path, handler, logging.getLogger("test"))

    client = TestClient(create_app(settings))
    person = client.post("/api/persons", json={"display_name": "검토자"}).json()
    changed = client.put(
        f"/api/recordings/{recording_id}/speakers/SPEAKER_00",
        json={"person_id": person["id"], "expected_revision": 1},
    )
    assert changed.status_code == 200
    assert changed.json()["render_job"]["input_revision"] == 2
    assert client.get(f"/api/recordings/{recording_id}").json()["summary"] is None

    blocked = client.patch(
        f"/api/persons/{person['id']}",
        json={"display_name": "다른 이름", "expected_revision": 1},
    )
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "RENDER_IN_PROGRESS"

    assert process_one_job(settings.database_path, handler, logging.getLogger("test"))
    with connect(settings.database_path) as connection:
        kinds = [
            row["kind"]
            for row in connection.execute(
                "SELECT kind FROM jobs WHERE recording_id = ? ORDER BY created_at, id",
                (recording_id,),
            ).fetchall()
        ]
        artifacts = connection.execute(
            "SELECT kind, revision FROM artifacts WHERE recording_id = ?",
            (recording_id,),
        ).fetchall()
    assert kinds.count("transcribe") == 1
    assert kinds.count("render") == 1
    assert kinds.count("summarize") == 2
    assert {row["revision"] for row in artifacts if row["kind"].startswith("transcript_")} == {
        1,
        2,
    }
    assert "검토자" in next(settings.document_root.glob("*.md")).read_text()

    assert process_one_job(settings.database_path, handler, logging.getLogger("test"))
    assert process_one_job(settings.database_path, handler, logging.getLogger("test"))
    assert client.get(f"/api/recordings/{recording_id}").json()["summary"] is not None
