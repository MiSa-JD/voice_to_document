from __future__ import annotations

import json
import urllib.request

from app.classification_eval import evaluate_cases, load_cases
from app.openai_classification import OpenAIClassificationAdapter


def _response(category: str) -> bytes:
    classification = json.dumps(
        {
            "schema_version": 1,
            "category": category,
            "confidence": 0.9,
            "reason": "합성 자료의 대표 특징과 일치합니다.",
        },
        ensure_ascii=False,
    )
    return json.dumps(
        {
            "status": "completed",
            "output": [{"content": [{"type": "output_text", "text": classification}]}],
        }
    ).encode()


def test_committed_evaluation_cases_cover_each_allowed_category_once() -> None:
    cases = load_cases()

    assert [case["expected_category"] for case in cases] == [
        "강의",
        "일상 대화",
        "회의",
        "게임 목록",
        "기타",
    ]
    serialized = json.dumps(cases, ensure_ascii=False)
    assert "/Users/" not in serialized
    assert "LLM_API_KEY" not in serialized


def test_evaluation_reports_only_case_results_and_fingerprint() -> None:
    cases = load_cases()
    responses = [_response(str(case["expected_category"])) for case in cases]
    request_bodies: list[dict[str, object]] = []

    def transport(request: urllib.request.Request, _timeout: float) -> bytes:
        assert isinstance(request.data, bytes)
        request_bodies.append(json.loads(request.data))
        return responses.pop(0)

    adapter = OpenAIClassificationAdapter(
        base_url="https://api.openai.com/v1",
        api_key="private-test-key",
        model="gpt-5.4-nano-2026-03-17",
        transport=transport,
    )

    results = evaluate_cases(
        adapter,
        ("강의", "일상 대화", "회의", "게임 목록", "기타"),
        cases,
    )

    assert len(results) == 5
    assert all(result.passed and result.has_reason for result in results)
    assert all(result.schema_version == 1 for result in results)
    public_results = json.dumps([result.__dict__ for result in results], ensure_ascii=False)
    assert "private-test-key" not in public_results
    assert "확률변수" not in public_results
    assert len(request_bodies) == 5
