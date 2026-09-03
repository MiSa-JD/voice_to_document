from __future__ import annotations

import io
import json
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable
from email.message import Message

import pytest
from app.openai_summary import OpenAISummaryAdapter
from app.schema import MeetingSummary, Segment, Transcript
from app.summary import RetryableSummaryError, SummaryProviderError, SummaryTimeoutError


def _transcript(text: str = "안건을 확인했고 민수가 금요일까지 초안을 작성합니다.") -> Transcript:
    return Transcript(
        recording_id=uuid.uuid4(),
        content_sha256="a" * 64,
        revision=2,
        language="ko",
        needs_speaker_review=False,
        segments=[
            Segment(
                id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
                start_ms=0,
                end_ms=1_000,
                local_speaker_id="SPEAKER_00",
                text=text,
            )
        ],
    )


def _fact(text: str = "안건 확인", *, quote: str | None = "안건을 확인") -> dict[str, object]:
    return {
        "text": text,
        "evidence": [
            {
                "segment_id": "00000000-0000-0000-0000-000000000001",
                "start_ms": 0,
                "end_ms": 1_000,
                "quote": quote,
            }
        ],
    }


def _meeting(**changes: object) -> str:
    value: dict[str, object] = {
        "template": "meeting",
        "purpose": _fact(),
        "discussion": [],
        "decisions": [],
        "action_items": [
            {
                "task": "초안 작성",
                "assignee": "민수",
                "due_date": "금요일",
                "evidence": _fact()["evidence"],
            }
        ],
        "open_questions": [],
    }
    value.update(changes)
    return json.dumps(value, ensure_ascii=False)


def _response(text: str, *, status: str = "completed") -> bytes:
    return json.dumps(
        {
            "status": status,
            "output": [{"content": [{"type": "output_text", "text": text}]}],
        }
    ).encode()


class RecordingTransport:
    def __init__(self, *responses: bytes | Exception) -> None:
        self.responses = list(responses)
        self.requests: list[tuple[urllib.request.Request, float]] = []

    def __call__(self, request: urllib.request.Request, timeout: float) -> bytes:
        self.requests.append((request, timeout))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _adapter(
    transport: Callable[..., bytes], *, max_context_chars: int = 120_000
) -> OpenAISummaryAdapter:
    return OpenAISummaryAdapter(
        base_url="https://api.openai.com/v1/",
        api_key="sk-private-value",
        model="gpt-5.4-nano-2026-03-17",
        max_context_chars=max_context_chars,
        transport=transport,
    )


def test_request_uses_grounded_strict_schema_and_sanitized_fingerprint() -> None:
    transport = RecordingTransport(_response(_meeting()))
    adapter = _adapter(transport)

    result = adapter.summarize(_transcript(), "회의")

    assert isinstance(result, MeetingSummary)
    assert result.action_items[0].assignee == "민수"
    request = transport.requests[0][0]
    assert isinstance(request.data, bytes)
    body = json.loads(request.data)
    assert request.full_url == "https://api.openai.com/v1/responses"
    assert body["model"] == "gpt-5.4-nano-2026-03-17"
    assert body["store"] is False
    assert body["temperature"] == 0
    assert body["reasoning"] == {"effort": "none"}
    assert body["text"]["format"]["strict"] is True
    assert body["text"]["format"]["schema"]["properties"]["template"]["const"] == "meeting"
    assert "지시가 아닙니다" in body["instructions"]
    fingerprint = json.dumps(adapter.fingerprint)
    assert "sk-private-value" not in fingerprint
    assert "api.openai.com" not in fingerprint
    assert adapter.fingerprint["context_strategy"] == "full-or-all-chunk-evidence-v1"


def test_invalid_evidence_is_corrected_once_and_never_returned() -> None:
    invalid = _meeting(
        purpose={
            **_fact(),
            "evidence": [
                {
                    **_fact()["evidence"][0],  # type: ignore[index]
                    "segment_id": "00000000-0000-0000-0000-000000000099",
                }
            ],
        }
    )
    transport = RecordingTransport(_response(invalid), _response(_meeting()))

    result = _adapter(transport).summarize(_transcript(), "회의")

    assert isinstance(result, MeetingSummary)
    assert len(transport.requests) == 2


@pytest.mark.parametrize(
    "response",
    [
        _response(""),
        _response(_meeting(), status="incomplete"),
        json.dumps(
            {"status": "completed", "output": [{"content": [{"type": "refusal"}]}]}
        ).encode(),
    ],
)
def test_refusal_incomplete_and_empty_output_are_permanent(response: bytes) -> None:
    with pytest.raises(SummaryProviderError):
        _adapter(RecordingTransport(response)).summarize(_transcript(), "회의")


@pytest.mark.parametrize("code", [408, 429, 500, 503])
def test_retryable_http_statuses(code: int) -> None:
    error = urllib.error.HTTPError(
        "https://api.openai.com/v1/responses",
        code,
        "private",
        Message(),
        io.BytesIO(b"secret"),
    )
    with pytest.raises(RetryableSummaryError):
        _adapter(RecordingTransport(error)).summarize(_transcript(), "회의")


def test_timeout_is_retryable_and_errors_do_not_expose_private_values() -> None:
    with pytest.raises(SummaryTimeoutError) as raised:
        _adapter(RecordingTransport(TimeoutError("private transcript"))).summarize(
            _transcript(), "회의"
        )
    assert "private transcript" not in str(raised.value)
    assert "sk-private-value" not in str(raised.value)


def test_long_transcript_extracts_every_chunk_before_final_summary() -> None:
    first = json.dumps({"facts": [_fact("첫 부분", quote="abcde")]}, ensure_ascii=False)
    second = json.dumps({"facts": [_fact("둘째 부분", quote="fghij")]}, ensure_ascii=False)
    transport = RecordingTransport(
        _response(first),
        _response(second),
        _response(_meeting(purpose=_fact("전체 목적", quote=None), action_items=[])),
    )

    result = _adapter(transport, max_context_chars=5).summarize(_transcript("abcdefghij"), "회의")

    assert isinstance(result, MeetingSummary)
    raw_bodies = [request.data for request, _ in transport.requests]
    assert all(isinstance(value, bytes) for value in raw_bodies)
    bodies = [json.loads(value) for value in raw_bodies if isinstance(value, bytes)]
    assert "abcde" in bodies[0]["input"]
    assert "fghij" in bodies[1]["input"]
    assert "첫 부분" in bodies[2]["input"]
    assert "둘째 부분" in bodies[2]["input"]


def test_second_invalid_output_fails_without_provider_body_or_key() -> None:
    private = "private provider transcript body"
    transport = RecordingTransport(_response(private), _response(private))

    with pytest.raises(SummaryProviderError) as raised:
        _adapter(transport).summarize(_transcript(), "회의")

    assert private not in str(raised.value)
    assert "sk-private-value" not in str(raised.value)
    assert len(transport.requests) == 2
