from __future__ import annotations

import json
import socket
import uuid
from pathlib import Path

import pytest
from app.adapters import FakeAdapters, FakeFixtureNotFoundError

COMPLETE_HASH = "e202a0e5517a6c4311f67c61e199b26bc1757af4c6b3ec0962fa61b4ff1807fb"
REVIEW_HASH = "7f8f1230daba23a52a634709c92f22499d52069fbe5199d017bdcaf794f6ead3"


def test_fake_adapters_are_deterministic_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(socket, "socket", lambda *_args, **_kwargs: pytest.fail("network used"))
    adapters = FakeAdapters()
    recording_id = str(uuid.uuid4())

    first = adapters.transcribe(recording_id, COMPLETE_HASH, 1)
    second = adapters.transcribe(recording_id, COMPLETE_HASH, 1)

    assert first == second
    assert first.needs_speaker_review is False
    assert {segment.local_speaker_id for segment in first.segments} == {
        "SPEAKER_00",
        "SPEAKER_01",
    }
    assert adapters.classify(COMPLETE_HASH).category == "회의"
    assert adapters.summarize(COMPLETE_HASH).action_items[0].task == "초안 준비"


def test_review_fixture_includes_local_document_classification() -> None:
    adapters = FakeAdapters()
    transcript = adapters.transcribe(str(uuid.uuid4()), REVIEW_HASH, 1)

    assert transcript.needs_speaker_review is True
    assert adapters.classify(REVIEW_HASH).category == "기타"
    with pytest.raises(ValueError, match="no summary"):
        adapters.summarize(REVIEW_HASH)


def test_unknown_content_hash_is_rejected() -> None:
    with pytest.raises(FakeFixtureNotFoundError, match="no fake fixture"):
        FakeAdapters().transcribe(str(uuid.uuid4()), "0" * 64, 1)


def test_manifest_cannot_escape_fixture_root(tmp_path: Path) -> None:
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "fixtures": {"a" * 64: {"expected": "../outside.json"}},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="leaves fixture root"):
        FakeAdapters(tmp_path).transcribe(str(uuid.uuid4()), "a" * 64, 1)
