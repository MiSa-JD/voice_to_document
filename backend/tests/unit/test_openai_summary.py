from __future__ import annotations

import io
import json
import logging
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


def _fact(text: str = "안건 확인", **reference_fields: object) -> dict[str, object]:
    return {
        "text": text,
        "evidence": [
            {
                "segment_id": "00000000-0000-0000-0000-000000000001",
                **reference_fields,
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
    assert "반드시 JSON null" in body["instructions"]
    assert "action_items에서 누락하지 마세요" in body["instructions"]
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
    first = json.dumps({"facts": [_fact("첫 부분")]}, ensure_ascii=False)
    second = json.dumps({"facts": [_fact("둘째 부분")]}, ensure_ascii=False)
    transport = RecordingTransport(
        _response(first),
        _response(second),
        _response(_meeting(purpose=_fact("전체 목적"), action_items=[])),
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


@pytest.mark.parametrize(
    ("response", "reason", "calls"),
    [
        (b"private-response", "response_format", 1),
        (b"[]", "response_format", 1),
        (_response("", status="incomplete"), "incomplete", 1),
        (b'{"output":[{"content":[{"type":"refusal"}]}]}', "refusal", 1),
        (_response(" "), "empty_output", 1),
        (_response("private-response"), "json_decode", 2),
        (_response("{}"), "schema", 2),
        (_response("[]"), "schema", 2),
        (_response(_meeting(purpose=_fact(quote="private-response"))), "schema", 2),
    ],
)
def test_safe_output_failure_reasons(response: bytes, reason: str, calls: int) -> None:
    transport = RecordingTransport(*([response] * calls))
    with pytest.raises(SummaryProviderError) as raised:
        _adapter(transport).summarize(_transcript(), "회의")
    assert raised.value.reason == reason
    assert raised.value.code == "SUMMARY_INVALID_OUTPUT"
    assert "private-response" not in str(raised.value)
    assert len(transport.requests) == calls


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        ("private-response", "json_decode"),
        ("[]", "schema"),
        ('{"facts": []}', "schema"),
        (json.dumps({"facts": [_fact(quote="private-response")]}), "schema"),
    ],
)
def test_chunk_failure_reasons(raw: str, reason: str) -> None:
    transport = RecordingTransport(_response(raw), _response(raw))
    with pytest.raises(SummaryProviderError) as raised:
        _adapter(transport, max_context_chars=5).summarize(_transcript(), "회의")
    assert raised.value.reason == reason
    assert len(transport.requests) == 2


def test_timeout_is_forwarded_without_changing_fingerprint() -> None:
    transport = RecordingTransport(_response(_meeting()))
    adapter = _adapter(transport)
    fingerprint = adapter.fingerprint
    adapter.timeout_seconds = 450.5
    adapter.summarize(_transcript(), "회의")
    assert transport.requests[0][1] == 450.5
    assert fingerprint == adapter.fingerprint


@pytest.mark.parametrize(
    ("field", "value", "kind"),
    [
        ("segment_id", "00000000-0000-0000-0000-000000000099", "unknown_segment"),
        ("start_ms", 1, "timestamp_mismatch"),
        ("quote", "PRIVATE_SENTINEL", "quote_mismatch"),
    ],
)
def test_evidence_diagnostics_use_response_paths(field: str, value: object, kind: str) -> None:
    from app.schema import SummaryFact, SummaryValidationError, validate_fact_evidence

    raw = _fact()
    raw["evidence"][0].update(start_ms=0, end_ms=1000)  # type: ignore[index]
    raw["evidence"][0][field] = value  # type: ignore[index]
    fact = SummaryFact.model_validate(raw)
    with pytest.raises(SummaryValidationError) as raised:
        validate_fact_evidence([("facts[2]", fact)], _transcript())
    assert raised.value.validation_type == kind
    assert raised.value.field_path == "facts[2].evidence[0]"
    assert "PRIVATE_SENTINEL" not in str(raised.value)


def test_chunk_membership_has_fixed_diagnostic() -> None:
    from app.schema import SummaryFact, SummaryValidationError, validate_fact_evidence

    raw = _fact()
    raw["evidence"][0].update(start_ms=0, end_ms=1000)  # type: ignore[index]
    with pytest.raises(SummaryValidationError) as raised:
        validate_fact_evidence(
            [("facts[0]", SummaryFact.model_validate(raw))], _transcript(), allowed_ids=set()
        )
    assert raised.value.validation_type == "outside_chunk"
    assert raised.value.field_path == "facts[0].evidence[0]"


@pytest.mark.parametrize(
    ("value", "kind", "path"),
    [
        ({}, "missing", "text"),
        ({"text": 12, "evidence": []}, "string_type", "text"),
        ({"text": "", "evidence": []}, "string_too_short", "text"),
        ({"text": "ok", "evidence": []}, "too_short", "evidence"),
    ],
)
def test_schema_diagnostic_types(value: object, kind: str, path: str) -> None:
    from app.schema import SummaryFact
    from app.summary import summary_validation_details
    from pydantic import ValidationError

    with pytest.raises(ValidationError) as raised:
        SummaryFact.model_validate(value)
    details = summary_validation_details(raised.value)
    assert details["validation_errors"][0] == {  # type: ignore[index]
        "validation_type": kind,
        "field_path": path,
    }


def test_schema_diagnostics_redact_keys_and_limit_details() -> None:
    from app.schema import SummaryFact
    from app.summary import summary_validation_details
    from pydantic import ValidationError

    with pytest.raises(ValidationError) as raised:
        SummaryFact.model_validate({f"PRIVATE_SENTINEL_{i}": "SECRET_VALUE" for i in range(9)})
    details = summary_validation_details(raised.value, prefix="facts")
    assert details["error_count"] == 11
    assert details["omitted_error_count"] == 6
    assert len(details["validation_errors"]) == 5  # type: ignore[arg-type]
    assert "unknown_field" in json.dumps(details)
    assert "PRIVATE_SENTINEL" not in json.dumps(details)
    assert "SECRET_VALUE" not in json.dumps(details)


def test_unknown_pydantic_error_type_is_redacted() -> None:
    from app.summary import summary_validation_details
    from pydantic import ValidationError
    from pydantic_core import PydanticCustomError

    error = ValidationError.from_exception_data(
        "private",
        [
            {
                "type": PydanticCustomError("PRIVATE_TYPE", "PRIVATE_MESSAGE"),
                "loc": ("PRIVATE_KEY", 2),
                "input": "PRIVATE_INPUT",
            }
        ],
    )
    details = summary_validation_details(error)
    assert details["validation_errors"] == [
        {"validation_type": "unknown_type", "field_path": "unknown_field[2]"}
    ]
    assert "PRIVATE" not in json.dumps(details)


@pytest.fixture
def diagnostic_log() -> tuple[io.StringIO, logging.Logger]:
    import logging

    from app.log import JsonFormatter

    output = io.StringIO()
    handler = logging.StreamHandler(output)
    handler.setFormatter(JsonFormatter("summary-test"))
    logger = logging.Logger("summary-test", level=logging.INFO)
    logger.addHandler(handler)
    return output, logger


@pytest.mark.parametrize("chunked", [False, True])
@pytest.mark.parametrize("second", ["success", "schema", "evidence"])
def test_each_response_logs_validation_and_correction(
    diagnostic_log: tuple[io.StringIO, logging.Logger],
    chunked: bool,
    second: str,
) -> None:
    from app.summary import SummaryExecutionContext

    output, logger = diagnostic_log
    valid = json.dumps({"facts": [_fact()]}) if chunked else _meeting()
    invalid_evidence = (
        json.dumps({"facts": [_fact(segment_id="00000000-0000-0000-0000-000000000099")]})
        if chunked
        else _meeting(purpose=_fact(segment_id="00000000-0000-0000-0000-000000000099"))
    )
    final = valid if second == "success" else "{}" if second == "schema" else invalid_evidence
    responses = [_response("{}"), _response(final)]
    if chunked and second == "success":
        responses += [_response(valid), _response(_meeting())]
    transport = RecordingTransport(*responses)
    adapter = _adapter(transport, max_context_chars=20 if chunked else 120_000)
    fingerprint = adapter.fingerprint
    context = SummaryExecutionContext(logger, job_id="test-job", job_attempt=3, input_revision=2)
    if second == "success":
        adapter.summarize(_transcript(), "회의", context=context)
    else:
        with pytest.raises(SummaryProviderError) as raised:
            adapter.summarize(_transcript(), "회의", context=context)
        assert raised.value.code == "SUMMARY_INVALID_OUTPUT"
        assert raised.value.reason == second
        assert "PRIVATE" not in str(raised.value)
    events = [json.loads(line) for line in output.getvalue().splitlines()]
    assert [event["event"] for event in events[:4]] == [
        "summary_request_started",
        "summary_validation_failed",
        "summary_request_started",
        "summary_validation_succeeded" if second == "success" else "summary_validation_failed",
    ]
    assert [event["provider_attempt"] for event in events[:4]] == [1, 1, 2, 2]
    assert events[1]["failure_reason"] == "schema"
    if second != "success":
        assert events[3]["failure_reason"] == second
    if second == "evidence":
        assert events[3]["validation_errors"] == [
            {
                "validation_type": "unknown_segment",
                "field_path": "facts[0].evidence[0]" if chunked else "purpose.evidence[0]",
            }
        ]
    for event in events:
        assert (event["job_id"], event["job_attempt"], event["input_revision"]) == (
            "test-job",
            3,
            2,
        )
        assert event["template"] == "meeting"
        assert event["elapsed_seconds"] >= 0
    assert events[0]["phase"] == ("chunk_extraction" if chunked else "final_summary")
    assert events[0]["segment_count"] == 1
    if chunked:
        assert events[0]["chunk_index"] == 0
        assert events[0]["chunk_count"] == 2
        if second == "success":
            assert events[4]["chunk_index"] == 1
            assert events[-1]["phase"] == "final_summary"
            assert "chunk_index" not in events[-1]
            assert events[-1]["input_chars"] == len("안건 확인") * 2
            assert events[-1]["segment_count"] == 1
    else:
        assert "chunk_index" not in events[0]
        assert "chunk_count" not in events[0]
        assert events[0]["input_chars"] == len(_transcript().segments[0].text)
    assert len(transport.requests) == (4 if chunked and second == "success" else 2)
    assert fingerprint == adapter.fingerprint
    assert "PRIVATE" not in output.getvalue()
    assert "sk-private-value" not in output.getvalue()
    assert _transcript().segments[0].text not in output.getvalue()


@pytest.mark.parametrize(
    ("chunked", "raw", "kind", "path"),
    [
        (False, "[]", "model_type", "$"),
        (True, "[]", "object_required", "$"),
        (True, '{"facts":[]}', "empty_facts", "facts"),
        (True, '{"facts":[{}]}', "missing", "facts[0].text"),
        (False, "PRIVATE_JSON", "invalid_json", "$"),
    ],
)
def test_manual_and_schema_checks_reach_json_formatter(
    diagnostic_log: tuple[io.StringIO, logging.Logger],
    chunked: bool,
    raw: str,
    kind: str,
    path: str,
) -> None:
    from app.summary import SummaryExecutionContext

    output, logger = diagnostic_log
    transport = RecordingTransport(_response(raw), _response(raw))
    with pytest.raises(SummaryProviderError):
        _adapter(transport, max_context_chars=5 if chunked else 120_000).summarize(
            _transcript("PRIVATE_TRANSCRIPT"),
            "회의",
            context=SummaryExecutionContext(logger),
        )
    failures = [
        json.loads(line)
        for line in output.getvalue().splitlines()
        if json.loads(line)["event"] == "summary_validation_failed"
    ]
    assert len(failures) == 2
    assert failures[0]["validation_errors"][0] == {"validation_type": kind, "field_path": path}
    assert "PRIVATE" not in output.getvalue()


def test_sensitive_schema_errors_are_bounded_in_formatted_log(
    diagnostic_log: tuple[io.StringIO, logging.Logger],
) -> None:
    from app.summary import SummaryExecutionContext

    output, logger = diagnostic_log
    raw = json.dumps({f"/private/SECRET_KEY_{i}": "SECRET_VALUE" for i in range(10)})
    with pytest.raises(SummaryProviderError) as raised:
        _adapter(RecordingTransport(_response(raw), _response(raw))).summarize(
            _transcript("SECRET_TRANSCRIPT"),
            "회의",
            context=SummaryExecutionContext(logger),
        )
    events = [json.loads(line) for line in output.getvalue().splitlines()]
    assert events[1]["error_count"] == 16
    assert events[1]["omitted_error_count"] == 11
    assert len(events[1]["validation_errors"]) == 5
    assert "SECRET" not in output.getvalue() + str(raised.value)
    assert "exception" not in output.getvalue()


def test_transport_failure_logs_without_traceback_or_extra_retry(
    diagnostic_log: tuple[io.StringIO, logging.Logger],
) -> None:
    from app.summary import SummaryExecutionContext

    output, logger = diagnostic_log
    transport = RecordingTransport(TimeoutError("PRIVATE_EXCEPTION"))
    with pytest.raises(SummaryTimeoutError):
        _adapter(transport).summarize(
            _transcript(), "회의", context=SummaryExecutionContext(logger)
        )
    assert len(transport.requests) == 1
    events = [json.loads(line) for line in output.getvalue().splitlines()]
    assert [e["event"] for e in events] == ["summary_request_started", "summary_validation_failed"]
    assert "PRIVATE_EXCEPTION" not in output.getvalue()
    assert "exception" not in events[1]


def test_shared_adapter_keeps_overlapping_call_contexts_separate(
    diagnostic_log: tuple[io.StringIO, logging.Logger],
) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from app.summary import SummaryExecutionContext

    output, logger = diagnostic_log
    barrier = Barrier(2)

    def transport(request: urllib.request.Request, timeout: float) -> bytes:
        barrier.wait(timeout=5)
        return _response(_meeting())

    adapter = _adapter(transport)

    def run(index: int) -> None:
        transcript = _transcript(f"공개 revision {index} 원문")
        transcript.revision = index
        result = adapter.summarize(
            transcript,
            "회의",
            context=SummaryExecutionContext(
                logger,
                job_id=f"job-{index}",
                job_attempt=index,
                input_revision=index,
            ),
        )
        assert isinstance(result, MeetingSummary)
        assert result.purpose.evidence[0].quote == transcript.segments[0].text

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(run, [1, 2]))
    events = [json.loads(line) for line in output.getvalue().splitlines()]
    for index in [1, 2]:
        own = [event for event in events if event["job_id"] == f"job-{index}"]
        assert [event["event"] for event in own] == [
            "summary_request_started",
            "summary_validation_succeeded",
        ]
        assert all(event["job_attempt"] == index for event in own)
        assert all(event["input_revision"] == index for event in own)


@pytest.mark.parametrize(
    ("chunked", "kind"),
    [
        (chunked, kind)
        for chunked in [False, True]
        for kind in ["unknown_segment", "outside_chunk"]
        if chunked or kind != "outside_chunk"
    ],
)
@pytest.mark.parametrize("corrected", [False, True])
def test_evidence_reason_logged_for_each_attempt(
    diagnostic_log: tuple[io.StringIO, logging.Logger],
    chunked: bool,
    kind: str,
    corrected: bool,
) -> None:
    from app.summary import SummaryExecutionContext

    output, logger = diagnostic_log
    transcript = _transcript("abcde")
    transcript.segments.append(
        Segment(
            id=uuid.UUID("00000000-0000-0000-0000-000000000002"),
            start_ms=1000,
            end_ms=2000,
            text="fghij",
            local_speaker_id="SPEAKER_00",
        )
    )
    fact = _fact()
    evidence = fact["evidence"][0]  # type: ignore[index]
    if kind == "unknown_segment":
        evidence["segment_id"] = "00000000-0000-0000-0000-000000000099"
    else:
        evidence.update(segment_id=str(transcript.segments[1].id))
    invalid = json.dumps({"facts": [fact]}) if chunked else _meeting(purpose=fact, action_items=[])
    valid = (
        json.dumps({"facts": [_fact()]}) if chunked else _meeting(purpose=_fact(), action_items=[])
    )
    responses = [_response(invalid), _response(valid if corrected else invalid)]
    if chunked and corrected:
        second_fact = _fact()
        second_fact["evidence"][0].update(  # type: ignore[index]
            segment_id=str(transcript.segments[1].id),
        )
        responses += [
            _response(json.dumps({"facts": [second_fact]})),
            _response(_meeting(purpose=_fact(), action_items=[])),
        ]
    adapter = _adapter(RecordingTransport(*responses), max_context_chars=5 if chunked else 120_000)
    if corrected:
        adapter.summarize(transcript, "회의", context=SummaryExecutionContext(logger))
    else:
        with pytest.raises(SummaryProviderError):
            adapter.summarize(transcript, "회의", context=SummaryExecutionContext(logger))
    failures = [
        json.loads(line)
        for line in output.getvalue().splitlines()
        if json.loads(line)["event"] == "summary_validation_failed"
    ]
    assert len(failures) == (1 if corrected else 2)
    assert [event["provider_attempt"] for event in failures] == ([1] if corrected else [1, 2])
    assert all(
        event["validation_errors"]
        == [
            {
                "validation_type": kind,
                "field_path": "facts[0].evidence[0]" if chunked else "purpose.evidence[0]",
            }
        ]
        for event in failures
    )
    assert "PRIVATE" not in output.getvalue()


@pytest.mark.parametrize("category", ["강의", "회의", "일상 대화", "게임 목록", "기타"])
def test_all_template_evidence_uses_original_text_and_times(category: str) -> None:
    from app.openai_summary import _summary_schema
    from app.schema import summary_template_for_category, validate_summary_evidence

    transcript = _transcript()
    transcript.segments.append(
        Segment(
            id=uuid.UUID("abcdefab-0000-0000-0000-000000000002"),
            start_ms=4321,
            end_ms=9876,
            text="공개 두 번째 문장",
            local_speaker_id="SPEAKER_00",
        )
    )
    before = transcript.model_dump_json()
    template = summary_template_for_category(category)
    schema = _summary_schema(template)
    properties = schema["properties"]
    assert isinstance(properties, dict)
    evidence = [{"segment_id": str(segment.id).upper()} for segment in transcript.segments]
    payload: dict[str, object] = {"template": template}
    for name, definition in properties.items():
        if name == "template":
            continue
        fact = (
            {"task": "공개 할 일", "assignee": None, "due_date": None, "evidence": evidence}
            if name == "action_items"
            else {"text": "공개 사실", "evidence": evidence}
        )
        payload[name] = [fact] if definition["type"] == "array" else fact
    transport = RecordingTransport(_response(json.dumps(payload)))
    result = _adapter(transport).summarize(transcript, category)
    validate_summary_evidence(result, transcript)
    for name, field in result.model_dump(mode="json").items():
        if name == "template":
            continue
        for fact in field if isinstance(field, list) else [field]:
            assert [(e["start_ms"], e["end_ms"]) for e in fact["evidence"]] == [
                (0, 1000),
                (4321, 9876),
            ]
            assert [e["quote"] for e in fact["evidence"]] == [
                segment.text for segment in transcript.segments
            ]
    assert transcript.model_dump_json() == before
    assert "start_ms" not in json.dumps(schema)
    assert "end_ms" not in json.dumps(schema)
    assert "quote" not in json.dumps(schema)


@pytest.mark.parametrize("chunked", [False, True])
@pytest.mark.parametrize(
    ("reference", "kind", "suffix"),
    [
        ({}, "missing", ".segment_id"),
        ({"segment_id": None}, "uuid_type", ".segment_id"),
        ({"segment_id": "PRIVATE_UUID"}, "uuid_parsing", ".segment_id"),
        ({"segment_id": str(uuid.UUID(int=1)), "start_ms": 0}, "extra_forbidden", ".start_ms"),
        ({"segment_id": str(uuid.UUID(int=1)), "end_ms": 1000}, "extra_forbidden", ".end_ms"),
        (
            {"segment_id": str(uuid.UUID(int=1)), "PRIVATE_KEY": "PRIVATE_VALUE"},
            "extra_forbidden",
            ".unknown_field",
        ),
        *[
            (
                {"segment_id": str(uuid.UUID(int=1)), "quote": quote},
                "extra_forbidden",
                ".quote",
            )
            for quote in [None, "안건을 확인", "PRIVATE_QUOTE", 123]
        ],
    ],
)
def test_reference_schema_errors_keep_safe_response_paths(
    diagnostic_log: tuple[io.StringIO, logging.Logger],
    chunked: bool,
    reference: dict[str, object],
    kind: str,
    suffix: str,
) -> None:
    from app.summary import SummaryExecutionContext

    output, logger = diagnostic_log
    fact = {"text": "공개 사실", "evidence": [reference]}
    raw = json.dumps({"facts": [fact]}) if chunked else _meeting(purpose=fact)
    transport = RecordingTransport(_response(raw), _response(raw))
    with pytest.raises(SummaryProviderError) as raised:
        _adapter(transport, max_context_chars=5 if chunked else 120_000).summarize(
            _transcript(), "회의", context=SummaryExecutionContext(logger)
        )
    assert raised.value.reason == "schema"
    events = [json.loads(line) for line in output.getvalue().splitlines()]
    path = ("facts[0]" if chunked else "purpose") + ".evidence[0]" + suffix
    assert events[1]["validation_errors"] == [{"validation_type": kind, "field_path": path}]
    assert events[3]["validation_errors"] == events[1]["validation_errors"]
    assert len(transport.requests) == 2
    assert "PRIVATE" not in output.getvalue()


@pytest.mark.parametrize("end_ms", [1000, 999])
def test_final_evidence_still_rejects_equal_and_reversed_times(end_ms: int) -> None:
    from app.schema import Evidence
    from pydantic import ValidationError

    with pytest.raises(ValidationError) as raised:
        Evidence(segment_id=uuid.UUID(int=1), start_ms=1000, end_ms=end_ms)
    assert raised.value.errors()[0]["type"] == "value_error"


def test_split_segment_keeps_original_times_and_quote_policy() -> None:
    transcript = _transcript("abcdefghij")
    transcript.segments[0].start_ms = 4321
    transcript.segments[0].end_ms = 9876
    # Each slice resolves to the whole original segment, never a partial quote.
    facts = json.dumps({"facts": [_fact()]})
    transport = RecordingTransport(
        _response(facts),
        _response(facts),
        _response(_meeting(purpose=_fact(), action_items=[])),
    )
    result = _adapter(transport, max_context_chars=5).summarize(transcript, "회의")
    assert isinstance(result, MeetingSummary)
    assert (result.purpose.evidence[0].start_ms, result.purpose.evidence[0].end_ms) == (4321, 9876)
    final_request = transport.requests[-1][0]
    assert isinstance(final_request.data, bytes)
    material = json.loads(json.loads(final_request.data)["input"].split("\n")[-1])
    assert len(material["evidence_from_all_chunks"]) == 2
    assert "start_ms" not in json.dumps(material)
    assert "end_ms" not in json.dumps(material)
    assert "quote" not in json.dumps(material)
    assert result.purpose.evidence[0].quote == transcript.segments[0].text
    assert all(
        fact["evidence"] == [{"segment_id": str(transcript.segments[0].id)}]
        for facts in material["evidence_from_all_chunks"]
        for fact in facts
    )


@pytest.mark.parametrize("chunked", [False, True])
@pytest.mark.parametrize("quote", [None, "안건을 확인", "안건을 검토했습니다."])
def test_provider_quote_is_rejected_then_id_only_correction_succeeds(
    diagnostic_log: tuple[io.StringIO, logging.Logger], chunked: bool, quote: str | None
) -> None:
    from app.summary import SummaryExecutionContext

    output, logger = diagnostic_log
    invalid = _fact(quote=quote)
    raw = json.dumps({"facts": [invalid]}) if chunked else _meeting(purpose=invalid)
    valid = json.dumps({"facts": [_fact()]}) if chunked else _meeting()
    responses = [_response(raw), _response(valid)]
    if chunked:
        responses += [_response(valid), _response(_meeting())]
    transport = RecordingTransport(*responses)
    transcript = _transcript()
    result = _adapter(transport, max_context_chars=20 if chunked else 120_000).summarize(
        transcript, "회의", context=SummaryExecutionContext(logger)
    )
    assert isinstance(result, MeetingSummary)
    assert result.purpose.evidence[0].quote == transcript.segments[0].text
    events = [json.loads(line) for line in output.getvalue().splitlines()]
    assert events[1]["failure_reason"] == "schema"
    assert events[1]["validation_errors"] == [
        {
            "validation_type": "extra_forbidden",
            "field_path": "facts[0].evidence[0].quote" if chunked else "purpose.evidence[0].quote",
        }
    ]
    assert events[3]["event"] == "summary_validation_succeeded"
    assert len(transport.requests) == (4 if chunked else 2)


def test_original_quote_mismatch_reproduction_and_resolver_preserves_inputs() -> None:
    from app.schema import SummaryFact, SummaryValidationError, validate_fact_evidence
    from app.summary_references import ReferenceFacts, resolve_evidence_references

    transcript = _transcript("공개 안건을 확인했습니다. 다음 주에 다시 논의합니다.")
    legacy = SummaryFact.model_validate(
        _fact(quote="공개 안건을 검토했습니다.", start_ms=0, end_ms=1000)
    )
    with pytest.raises(SummaryValidationError) as raised:
        validate_fact_evidence([("facts[0]", legacy)], transcript)
    assert raised.value.validation_type == "quote_mismatch"
    references = ReferenceFacts.model_validate({"facts": [_fact()]})
    before_references = references.model_dump_json()
    before_transcript = transcript.model_dump_json()
    resolved = resolve_evidence_references(references, transcript)
    fact = SummaryFact.model_validate(resolved["facts"][0])  # type: ignore[index]
    validate_fact_evidence([("facts[0]", fact)], transcript)
    assert fact.evidence[0].quote == transcript.segments[0].text
    assert references.model_dump_json() == before_references
    assert transcript.model_dump_json() == before_transcript


@pytest.mark.parametrize("chunked", [False, True])
@pytest.mark.parametrize("evidence", [[], None, {}, [None], ["PRIVATE_VALUE"]])
def test_provider_rejects_empty_or_mistyped_evidence(chunked: bool, evidence: object) -> None:
    fact = {"text": "공개 사실", "evidence": evidence}
    raw = json.dumps({"facts": [fact]}) if chunked else _meeting(purpose=fact)
    with pytest.raises(SummaryProviderError) as raised:
        _adapter(
            RecordingTransport(_response(raw), _response(raw)),
            max_context_chars=5 if chunked else 120_000,
        ).summarize(_transcript(), "회의")
    assert raised.value.reason == "schema"


def test_provider_rejects_wrong_category() -> None:
    raw = _meeting(template="other")
    with pytest.raises(SummaryProviderError) as raised:
        _adapter(RecordingTransport(_response(raw), _response(raw))).summarize(
            _transcript(), "회의"
        )
    assert raised.value.reason == "schema"
