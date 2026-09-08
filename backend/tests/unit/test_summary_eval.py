from __future__ import annotations

import json
import logging
import urllib.request
import uuid
from typing import Any

import pytest
from app.openai_summary import OpenAISummaryAdapter
from app.summary_eval import evaluate_cases, load_cases, long_meeting_case


def _fact(case: dict[str, Any]) -> dict[str, object]:
    case_id = str(case["case_id"])
    indexes = list(case["required_evidence_segments"])
    terms = [item[0] if isinstance(item, list) else item for item in case["required_terms"]]
    return {
        "text": " / ".join(str(item) for item in terms),
        "evidence": [
            {
                "segment_id": str(
                    uuid.uuid5(uuid.NAMESPACE_URL, f"summary-eval:{case_id}:{index}")
                ),
            }
            for index in indexes
        ],
    }


def _summary(case: dict[str, Any]) -> dict[str, object]:
    fact = _fact(case)
    template = str(case["expected_template"])
    if template == "lecture":
        return {
            "template": template,
            "core_topics": [fact],
            "concepts": [],
            "examples": [],
            "review_items": [],
        }
    if template == "meeting":
        return {
            "template": template,
            "purpose": fact,
            "discussion": [],
            "decisions": [],
            "action_items": [
                {
                    "task": "회의록 정리",
                    "assignee": None,
                    "due_date": None,
                    "evidence": fact["evidence"],
                }
            ],
            "open_questions": [],
        }
    if template == "daily_conversation":
        return {"template": template, "main_topics": [fact], "agreements": [], "reminders": []}
    if template == "game_list":
        return {"template": template, "games": [fact], "preferences": [], "follow_ups": []}
    return {"template": template, "key_summary": fact, "key_facts": [], "follow_ups": []}


def _response(summary: dict[str, object]) -> bytes:
    return json.dumps(
        {
            "status": "completed",
            "output": [
                {
                    "content": [
                        {"type": "output_text", "text": json.dumps(summary, ensure_ascii=False)}
                    ]
                }
            ],
        }
    ).encode()


def test_committed_summary_cases_cover_five_templates_without_private_values() -> None:
    cases = load_cases()

    assert [case["expected_template"] for case in cases] == [
        "lecture",
        "daily_conversation",
        "meeting",
        "game_list",
        "other",
    ]
    serialized = json.dumps(cases, ensure_ascii=False)
    assert "/Users/" not in serialized
    assert "LLM_API_KEY" not in serialized


def test_evaluation_checks_grounding_null_rendering_and_sanitized_output(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="summary_eval")
    cases = load_cases()
    responses = [_response(_summary(case)) for case in cases]
    requests: list[urllib.request.Request] = []

    def transport(request: urllib.request.Request, _timeout: float) -> bytes:
        requests.append(request)
        return responses.pop(0)

    adapter = OpenAISummaryAdapter(
        base_url="https://api.openai.com/v1",
        api_key="private-test-key",
        model="gpt-5.4-nano-2026-03-17",
        transport=transport,
    )

    results = evaluate_cases(adapter, cases)

    assert len(results) == 5
    assert all(result.passed and all(result.checks.values()) for result in results)
    public_results = json.dumps([result.__dict__ for result in results], ensure_ascii=False)
    assert "private-test-key" not in public_results
    assert "확률변수" not in public_results
    assert len(requests) == 5
    events = [record for record in caplog.records if record.name == "summary_eval"]
    assert [record.__dict__["case_id"] for record in events] == [
        case["case_id"] for case in cases for _ in range(2)
    ]
    assert all(not hasattr(record, "job_id") for record in events)
    assert all(record.__dict__["input_revision"] == 1 for record in events)


def test_long_meeting_preserves_beginning_middle_end_and_rejects_omissions() -> None:
    case = long_meeting_case()
    assert 30_000 <= sum(len(item["text"]) for item in case["segments"]) <= 50_000
    assert case["segments"][-1]["end_ms"] == 45 * 60 * 1000
    payload = _summary(case)
    adapter = OpenAISummaryAdapter(
        base_url="https://example.invalid/v1",
        api_key="private-test-key",
        model="test",
        transport=lambda request, timeout: _response(payload),
    )
    assert evaluate_cases(adapter, [case])[0].passed
    payload["purpose"] = {**_fact(case), "text": "은하수 240"}
    assert not evaluate_cases(adapter, [case])[0].checks["required_facts"]
    payload["purpose"] = {**_fact(case), "evidence": []}
    result = evaluate_cases(adapter, [case])[0]
    assert not result.passed
    assert result.failure_reason == "schema"


def test_evaluation_requires_reference_contract_fingerprint() -> None:
    from app.summary_eval import _valid_fingerprint

    adapter = OpenAISummaryAdapter(base_url="https://example.invalid", api_key="", model="test")
    assert _valid_fingerprint(adapter.fingerprint)
    assert adapter.fingerprint["schema_version"] == adapter.fingerprint["template_version"] == 1
    assert not _valid_fingerprint(
        {**adapter.fingerprint, "prompt_version": "openai-grounded-summary-v3"}
    )
    assert not _valid_fingerprint({**adapter.fingerprint, "evidence_time_strategy": "other"})


@pytest.mark.parametrize("key", ["provider_schema_version", "evidence_quote_strategy"])
def test_evaluation_rejects_missing_or_old_quote_contract(key: str) -> None:
    from app.summary_eval import _valid_fingerprint

    adapter = OpenAISummaryAdapter(base_url="https://example.invalid", api_key="", model="test")
    fingerprint = adapter.fingerprint
    fingerprint.pop(key)
    assert not _valid_fingerprint(fingerprint)
    fingerprint[key] = 2 if key == "provider_schema_version" else "other"
    assert not _valid_fingerprint(fingerprint)


def test_fingerprint_hashes_match_actual_prompt_and_all_provider_schemas() -> None:
    import hashlib

    from app.openai_summary import SYSTEM_INSTRUCTION, _summary_schema

    adapter = OpenAISummaryAdapter(base_url="https://example.invalid", api_key="", model="test")
    fingerprint = adapter.fingerprint
    schemas = {
        name: _summary_schema(name)
        for name in ["lecture", "meeting", "daily_conversation", "game_list", "other"]
    }
    assert fingerprint["prompt_version"] == "openai-grounded-summary-v4"
    assert fingerprint["provider_schema_version"] == 3
    assert fingerprint["evidence_quote_strategy"] == "source-segment-text-v1"
    assert fingerprint["prompt_sha256"] == hashlib.sha256(SYSTEM_INSTRUCTION.encode()).hexdigest()
    assert (
        fingerprint["schema_sha256"]
        == hashlib.sha256(
            json.dumps(schemas, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    assert (
        fingerprint["prompt_sha256"]
        != "a44f43f17480f110db1a998879f2f100c8a3e412c4d8be1a438f90101daae3ec"
    )
    assert (
        fingerprint["schema_sha256"]
        != "b1252d5aaf885c2149732be347bdeff3ab168eedd5e54ed2ba959247c64f2772"
    )
