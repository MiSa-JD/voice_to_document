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
from app.long_transcript import LongTranscriptClassifier
from app.openai_classification import OpenAIClassificationAdapter
from app.pipeline import FakePipelineHandler
from app.real_pipeline import RealSpeechPipelineHandler
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
            "SPEECH_MODE": speech_mode,
            "DOCUMENT_MODE": document_mode,
            "HF_TOKEN": "test-token" if speech_mode == "real" else "",
            "LLM_PROVIDER": "openai_compatible" if real_document else "",
            "LLM_BASE_URL": "https://api.openai.com/v1" if real_document else "",
            "LLM_API_KEY": "test-key" if real_document else "",
            "LLM_MODEL": "test-snapshot" if real_document else "",
        }
    )

    handler = build_handler(Settings(**settings_values), logging.getLogger("test"))

    assert isinstance(handler, handler_type)
    assert isinstance(handler, FakePipelineHandler)
    assert isinstance(handler.classification_adapter, LongTranscriptClassifier)
    assert (
        isinstance(handler.classification_adapter.direct_adapter, OpenAIClassificationAdapter)
        is real_document
    )
