from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Any

import pytest
from app.config import Settings
from app.job_retries import recovery_handler
from app.long_transcript import LongTranscriptClassifier
from app.openai_classification import OpenAIClassificationAdapter
from app.openai_summary import OpenAISummaryAdapter
from app.pipeline import FakePipelineHandler
from app.real_pipeline import RealSpeechPipelineHandler
from app.summary import summary_settings_fingerprint
from app.worker import build_handler


@pytest.mark.parametrize(("speech_mode", "hf_token"), [("fake", ""), ("real", "test-token")])
def test_worker_stops_after_sigterm(
    settings_values: dict[str, Any], speech_mode: str, hf_token: str
) -> None:
    environment = os.environ.copy()
    environment.update({key: str(value) for key, value in settings_values.items()})
    environment["PYTHONPATH"] = "backend"
    environment["SPEECH_MODE"] = speech_mode
    environment["HF_TOKEN"] = hf_token
    process = subprocess.Popen(
        [str(Path(".venv/bin/python")), "-m", "app.worker"],
        cwd=Path.cwd(),
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    time.sleep(0.3)
    started = time.monotonic()

    process.terminate()
    stdout, stderr = process.communicate(timeout=3)

    assert process.returncode == 0
    assert time.monotonic() - started < 3
    events = [json.loads(line) for line in (stdout + stderr).splitlines() if line]
    assert [event["event"] for event in events] == [
        "worker_started",
        "worker_stop_requested",
        "worker_stopped",
    ]
    assert all(event["service"] == "worker" for event in events)


@pytest.mark.parametrize(
    ("speech_mode", "document_mode", "handler_type", "real_document"),
    [
        ("fake", "fake", FakePipelineHandler, False),
        ("real", "fake", RealSpeechPipelineHandler, False),
        ("fake", "real", FakePipelineHandler, True),
        ("real", "real", RealSpeechPipelineHandler, True),
    ],
)
def test_worker_builds_all_speech_and_document_mode_combinations(
    settings_values: dict[str, Any],
    speech_mode: str,
    document_mode: str,
    handler_type: type[FakePipelineHandler],
    real_document: bool,
) -> None:
    settings_values.update(
        {
            "SERVICE_NAME": "worker",
            "SUMMARY_REQUEST_TIMEOUT_SECONDS": 451,
            "CLASSIFICATION_CONTEXT_MAX_CHARS": 54321,
            "SUMMARY_CONTEXT_MAX_CHARS": 65432,
            "SPEECH_MODE": speech_mode,
            "DOCUMENT_MODE": document_mode,
            "HF_TOKEN": "test-token" if speech_mode == "real" else "",
            "LLM_PROVIDER": "openai_compatible" if real_document else "",
            "LLM_BASE_URL": "https://api.openai.com/v1" if real_document else "",
            "LLM_API_KEY": "test-key" if real_document else "",
            "LLM_MODEL": "test-snapshot" if real_document else "",
        }
    )

    settings = Settings(**settings_values)
    handler = build_handler(settings, logging.getLogger("test"))
    inspector = recovery_handler(settings)

    assert isinstance(handler, handler_type)
    assert isinstance(handler, FakePipelineHandler)
    assert isinstance(handler.classification_adapter, LongTranscriptClassifier)
    assert type(handler) is handler_type
    assert type(inspector) is FakePipelineHandler
    assert inspector.settings.effective_speech_mode == speech_mode
    assert inspector.settings.effective_document_mode == document_mode
    assert settings.llm_api_key is not None
    assert settings.llm_api_key.get_secret_value() == ("test-key" if real_document else "")
    assert inspector.settings.llm_api_key is not None
    assert inspector.settings.llm_api_key.get_secret_value() == ""
    assert handler.classification_adapter.max_context_chars == 54321
    assert (
        inspector.classification_adapter.fingerprint == handler.classification_adapter.fingerprint
    )
    assert inspector.summary_adapter.fingerprint == handler.summary_adapter.fingerprint
    for category in settings.categories:
        assert summary_settings_fingerprint(
            inspector.summary_adapter, category
        ) == summary_settings_fingerprint(handler.summary_adapter, category)
    assert (
        inspector.settings.speaker_finalization_settings_fingerprint
        == settings.speaker_finalization_settings_fingerprint
    )
    assert (
        isinstance(handler.classification_adapter.direct_adapter, OpenAIClassificationAdapter)
        is real_document
    )
    if real_document:
        assert isinstance(handler.summary_adapter, OpenAISummaryAdapter)
        assert handler.summary_adapter.timeout_seconds == 451
        assert handler.summary_adapter.max_context_chars == 65432
        assert handler.summary_adapter.api_key == "test-key"
        assert handler.summary_adapter.model == "test-snapshot"
        backend = handler.classification_adapter.direct_adapter
        assert isinstance(backend, OpenAIClassificationAdapter)
        assert backend.api_key == "test-key" and backend.model == "test-snapshot"
        assert backend.base_url == handler.summary_adapter.base_url == "https://api.openai.com/v1"
        assert isinstance(inspector.summary_adapter, OpenAISummaryAdapter)
        assert inspector.summary_adapter.api_key == ""
        assert isinstance(inspector.classification_adapter, LongTranscriptClassifier)
        inspection_backend = inspector.classification_adapter.direct_adapter
        assert isinstance(inspection_backend, OpenAIClassificationAdapter)
        assert inspection_backend.api_key == ""


def test_api_recovery_import_does_not_import_worker_or_speech_runtime() -> None:
    subprocess.run(
        [
            ".venv/bin/python",
            "-c",
            "import sys; import app.job_retries; "
            "assert not {'app.worker', 'app.real_pipeline', 'whisperx', 'torch'} "
            "& sys.modules.keys()",
        ],
        check=True,
    )
