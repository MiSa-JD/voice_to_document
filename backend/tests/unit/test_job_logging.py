from __future__ import annotations

import io
import json
import logging
from pathlib import Path

import pytest
from app.jobs import Job
from app.log import JsonFormatter
from app.repository import register_recording
from app.runtime import PermanentJobError, RetryableJobError, process_one_job


@pytest.mark.parametrize(
    ("error", "event", "code"),
    [
        (None, "job_succeeded", None),
        (
            RetryableJobError("SUMMARY_TIMEOUT", "private-input"),
            "job_retry_scheduled",
            "SUMMARY_TIMEOUT",
        ),
        (
            PermanentJobError("SUMMARY_INVALID_OUTPUT", "private-input"),
            "job_failed",
            "SUMMARY_INVALID_OUTPUT",
        ),
        (
            RuntimeError("private-input /private/path token-secret"),
            "job_failed",
            "UNEXPECTED_JOB_ERROR",
        ),
    ],
)
def test_lifecycle_context_duration_and_private_data(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error: Exception | None,
    event: str,
    code: str | None,
) -> None:
    database = tmp_path / "app.db"
    source = tmp_path / "source.m4a"
    source.write_bytes(b"audio")
    registration = register_recording(database, source, "d" * 64, 5, 1000)
    stream = io.StringIO()
    sink = logging.StreamHandler(stream)
    sink.setFormatter(JsonFormatter("worker"))
    logger = logging.Logger("lifecycle", logging.INFO)
    logger.addHandler(sink)
    times = iter([100.0, 100.125])
    monkeypatch.setattr("app.runtime.monotonic", lambda: next(times))

    def handler(job: Job) -> None:
        if error is not None:
            raise error

    assert process_one_job(database, handler, logger)
    output = stream.getvalue()
    assert (
        "private-input" not in output
        and "/private/path" not in output
        and "token-secret" not in output
    )
    start, end = [json.loads(line) for line in output.splitlines()]
    assert start["event"] == "job_started" and end["event"] == event
    for row in (start, end):
        assert row["job_id"] == registration.job_id
        assert row["recording_id"] == registration.recording_id
        assert row["stage"] == "transcribe" and row["attempt"] == 1
    assert end["duration_ms"] == 125
    assert end.get("error_code") == code
