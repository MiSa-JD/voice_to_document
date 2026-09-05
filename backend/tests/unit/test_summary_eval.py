from __future__ import annotations

import json
import urllib.request
import uuid
from typing import Any

from app.openai_summary import OpenAISummaryAdapter
from app.summary_eval import evaluate_cases, load_cases


def _fact(case: dict[str, Any]) -> dict[str, object]:
    case_id = str(case["case_id"])
    segments = list(case["segments"])
    indexes = list(case["required_evidence_segments"])
    terms = [item[0] if isinstance(item, list) else item for item in case["required_terms"]]
    return {
        "text": " / ".join(str(item) for item in terms),
        "evidence": [
            {
                "segment_id": str(
                    uuid.uuid5(uuid.NAMESPACE_URL, f"summary-eval:{case_id}:{index}")
                ),
                "start_ms": int(segments[int(index)]["start_ms"]),
                "end_ms": int(segments[int(index)]["end_ms"]),
                "quote": None,
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


def test_evaluation_checks_grounding_null_rendering_and_sanitized_output() -> None:
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
