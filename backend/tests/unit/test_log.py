from __future__ import annotations

import json
import logging

from app.log import JsonFormatter


def test_json_log_contains_service_and_context() -> None:
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="worker_started",
        args=(),
        exc_info=None,
    )
    record.recording_id = "recording-1"

    payload = json.loads(JsonFormatter("worker").format(record))

    assert payload["level"] == "INFO"
    assert payload["service"] == "worker"
    assert payload["event"] == "worker_started"
    assert payload["recording_id"] == "recording-1"


def test_exception_formatter_does_not_emit_sensitive_message() -> None:
    import sys

    try:
        raise RuntimeError("private transcript /private/source token-secret")
    except RuntimeError:
        record = logging.LogRecord(
            "test", logging.ERROR, __file__, 1, "job_failed", (), sys.exc_info()
        )
    rendered = JsonFormatter("worker").format(record)
    assert "private" not in rendered and "token-secret" not in rendered
    assert json.loads(rendered)["exception_type"] == "RuntimeError"
