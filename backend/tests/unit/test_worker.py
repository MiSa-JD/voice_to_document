from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

import pytest


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
