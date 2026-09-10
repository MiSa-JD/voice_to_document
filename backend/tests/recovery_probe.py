"""Isolated fake worker SIGKILL/restart probe, also run inside Compose."""

from __future__ import annotations

import json
import logging
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from app.config import Settings
from app.db import connect
from app.ingest import ingest_file
from app.pipeline import FakePipelineHandler
from app.worker import run


class CrashAfterTranscript(FakePipelineHandler):
    def _generate_speaker_clips(self, recording_id: str, source: Path, revision: int) -> None:
        os.kill(os.getpid(), signal.SIGKILL)


def probe() -> None:
    with tempfile.TemporaryDirectory(prefix="worker-recovery-") as directory:
        root = Path(directory)
        values = {
            name: str(root / name.lower())
            for name in (
                "RECORDING_INPUT_DIR",
                "TRANSCRIPT_ROOT",
                "SPEAKER_ROOT",
                "DOCUMENT_ROOT",
                "APP_DATA_DIR",
                "MODEL_CACHE_ROOT",
            )
        }
        for value in values.values():
            Path(value).mkdir()
        environment = {
            **os.environ,
            **values,
            "SPEECH_MODE": "fake",
            "DOCUMENT_MODE": "fake",
            "SUMMARY_ROOT": values["DOCUMENT_ROOT"],
            "SCAN_INTERVAL_SECONDS": "1",
        }
        settings = Settings.model_validate(
            {**values, "SPEECH_MODE": "fake", "DOCUMENT_MODE": "fake"}
        )
        source = settings.recording_input_dir / "complete.m4a"
        shutil.copyfile(Path(__file__).parent / "fixtures/complete.m4a", source)
        recording_id = ingest_file(settings.database_path, source).recording_id
        command = [sys.executable, str(Path(__file__).resolve()), "crash"]
        crashed = subprocess.run(command, env=environment, capture_output=True, timeout=30)
        assert crashed.returncode == -signal.SIGKILL
        with connect(settings.database_path) as connection:
            job = connection.execute("SELECT * FROM jobs WHERE status = 'running'").fetchone()
            assert job is not None and job["attempts"] == 1
            checkpoint = connection.execute(
                "SELECT content_sha256 FROM artifacts WHERE kind = 'transcript_json'"
            ).fetchone()
            assert checkpoint is not None
        process = subprocess.Popen(
            [sys.executable, "-m", "app.worker"],
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                with connect(settings.database_path) as connection:
                    row = connection.execute(
                        "SELECT status FROM recordings WHERE id = ?", (recording_id,)
                    ).fetchone()
                if row["status"] == "COMPLETED":
                    break
                assert process.poll() is None
                time.sleep(0.1)
            else:
                raise AssertionError("recovery timed out")
            with connect(settings.database_path) as connection:
                row = connection.execute(
                    "SELECT status, attempts FROM jobs WHERE id = ?", (job["id"],)
                ).fetchone()
                assert tuple(row) == ("succeeded", 2)
                assert connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 4
                assert (
                    connection.execute(
                        "SELECT COUNT(*) FROM audit_events WHERE event_type = 'job_recovered'"
                    ).fetchone()[0]
                    == 1
                )
            print(json.dumps({"recovery_probe": "passed", "jobs": 4, "attempts": 2}))
        finally:
            process.terminate()
            process.wait(timeout=10)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "crash":
        config = Settings()  # type: ignore[call-arg]
        raise SystemExit(run(config, CrashAfterTranscript(config, logging.getLogger("worker"))))
    probe()
