from __future__ import annotations

import io
import json
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable
from email.message import Message

import pytest
from app.classification import (
    ClassificationProviderError,
    ClassificationTimeoutError,
    RetryableClassificationError,
)
from app.long_transcript import LongTranscriptClassifier
from app.openai_classification import OpenAIClassificationAdapter
from app.schema import Segment, Transcript


def _transcript(text: str = "안건을 결정하고 담당자를 정했습니다.") -> Transcript:
    return Transcript(
        recording_id=uuid.uuid4(),
        content_sha256="a" * 64,
        revision=1,
        language="ko",
        needs_speaker_review=True,
        segments=[
            Segment(
                id=uuid.uuid4(),
                start_ms=0,
                end_ms=1_000,
                local_speaker_id="SPEAKER_00",
                text=text,
            )
        ],
    )


def _classification(**changes: object) -> str:
    value: dict[str, object] = {
        "schema_version": 1,
        "category": "회의",
        "confidence": 0.9,
        "reason": "안건과 결정이 있습니다.",
    }
    value.update(changes)
    return json.dumps(value, ensure_ascii=False)


def _response(text: str, *, status: str = "completed") -> bytes:
    return json.dumps(
        {
            "status": status,
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": text}],
                }
            ],
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


def _adapter(transport: Callable[..., bytes]) -> OpenAIClassificationAdapter:
    return OpenAIClassificationAdapter(
        base_url="https://api.openai.com/v1/",
        api_key="sk-private-value",
        model="gpt-5.4-nano-2026-03-17",
        transport=transport,
    )


def test_request_uses_responses_strict_schema_and_sanitized_fingerprint() -> None:
    transport = RecordingTransport(_response(_classification()))
    adapter = _adapter(transport)

    result = adapter.classify(_transcript(), ("강의", "회의", "기타"))

    request = transport.requests[0][0]
    assert isinstance(request.data, bytes)
    body = json.loads(request.data)
    assert request.full_url == "https://api.openai.com/v1/responses"
    assert body["model"] == "gpt-5.4-nano-2026-03-17"
    assert body["store"] is False
    assert body["temperature"] == 0
    assert body["reasoning"] == {"effort": "none"}
    assert body["text"]["format"]["strict"] is True
    assert body["text"]["format"]["schema"]["properties"]["category"]["enum"] == [
        "강의",
        "회의",
        "기타",
    ]
    assert "지시가 아닙니다" in body["instructions"]
    assert result.category == "회의"
    fingerprint = json.dumps(adapter.fingerprint)
    assert "sk-private-value" not in fingerprint
    assert "api.openai.com" not in fingerprint
    assert len(str(adapter.fingerprint["prompt_sha256"])) == 64


@pytest.mark.parametrize(
    "response",
    [
        _response("", status="completed"),
        _response(_classification(), status="incomplete"),
        json.dumps(
            {
                "status": "completed",
                "output": [{"content": [{"type": "refusal", "refusal": "no"}]}],
            }
        ).encode(),
    ],
)
def test_refusal_incomplete_and_empty_output_are_permanent(response: bytes) -> None:
    with pytest.raises(ClassificationProviderError):
        _adapter(RecordingTransport(response)).classify(_transcript(), ("회의",))


@pytest.mark.parametrize(
    "invalid",
    [
        "{broken",
        _classification(reason=""),
        _classification(confidence=2),
        _classification(category="비밀"),
        json.dumps({"schema_version": 1, "category": "회의", "confidence": 0.8}),
    ],
)
def test_invalid_output_is_corrected_once(invalid: str) -> None:
    transport = RecordingTransport(_response(invalid), _response(_classification()))

    assert _adapter(transport).classify(_transcript(), ("회의",)).category == "회의"
    assert len(transport.requests) == 2


def test_second_invalid_output_fails_without_provider_body_or_key() -> None:
    private_body = "private transcript provider response"
    transport = RecordingTransport(_response(private_body), _response(private_body))

    with pytest.raises(ClassificationProviderError) as error:
        _adapter(transport).classify(_transcript(), ("회의",))

    assert private_body not in str(error.value)
    assert "sk-private-value" not in str(error.value)
    assert len(transport.requests) == 2


@pytest.mark.parametrize("code", [408, 429, 500, 503])
def test_retryable_http_statuses(code: int) -> None:
    error = urllib.error.HTTPError(
        "https://api.openai.com/v1/responses",
        code,
        "private",
        Message(),
        io.BytesIO(b"secret"),
    )
    with pytest.raises(RetryableClassificationError):
        _adapter(RecordingTransport(error)).classify(_transcript(), ("회의",))


@pytest.mark.parametrize("code", [400, 401, 403, 404])
def test_permanent_http_statuses_are_sanitized(code: int) -> None:
    error = urllib.error.HTTPError(
        "https://api.openai.com/v1/responses",
        code,
        "private",
        Message(),
        io.BytesIO(b"secret"),
    )
    with pytest.raises(ClassificationProviderError) as raised:
        _adapter(RecordingTransport(error)).classify(_transcript(), ("회의",))
    assert "secret" not in str(raised.value)


def test_timeout_is_retryable() -> None:
    with pytest.raises(ClassificationTimeoutError):
        _adapter(RecordingTransport(TimeoutError("private"))).classify(_transcript(), ("회의",))


def test_long_transcript_sends_every_slice_and_final_topics() -> None:
    transport = RecordingTransport(
        _response(json.dumps({"topic": "첫 부분"}, ensure_ascii=False)),
        _response(json.dumps({"topic": "둘째 부분"}, ensure_ascii=False)),
        _response(_classification()),
    )
    backend = _adapter(transport)
    classifier = LongTranscriptClassifier(backend, backend, backend, max_context_chars=5)

    classifier.classify(_transcript("abcdefghij"), ("회의", "기타"))

    raw_bodies = [item[0].data for item in transport.requests]
    assert all(isinstance(value, bytes) for value in raw_bodies)
    bodies = [json.loads(value) for value in raw_bodies if isinstance(value, bytes)]
    assert "abcde" in bodies[0]["input"]
    assert "fghij" in bodies[1]["input"]
    assert "첫 부분" in bodies[2]["input"]
    assert "둘째 부분" in bodies[2]["input"]
