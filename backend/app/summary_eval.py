from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol

from pydantic import SecretStr

from app.config import Settings
from app.openai_summary import OpenAISummaryAdapter
from app.schema import CategorySummary, Segment, Transcript
from app.summary import SummaryError
from app.summary_renderer import render_summary_markdown

FIXTURE_PATH = Path(__file__).parent.parent / "tests" / "fixtures" / "summary_eval.json"


class EvaluationAdapter(Protocol):
    @property
    def fingerprint(self) -> dict[str, object]: ...

    def summarize(self, transcript: Transcript, category: str) -> CategorySummary: ...


@dataclass(frozen=True)
class EvaluationResult:
    case_id: str
    category: str
    checks: dict[str, bool]
    passed: bool
    fingerprint: dict[str, object]


def load_cases(path: Path = FIXTURE_PATH) -> list[dict[str, Any]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list) or len(value) != 5:
        raise ValueError("summary evaluation requires exactly five cases")
    return value


def evaluate_cases(
    adapter: EvaluationAdapter, cases: list[dict[str, Any]]
) -> list[EvaluationResult]:
    results: list[EvaluationResult] = []
    for case in cases:
        transcript = _transcript(case)
        category = str(case["category"])
        try:
            summary = adapter.summarize(transcript, category)
        except SummaryError:
            results.append(
                EvaluationResult(
                    case_id=str(case["case_id"]),
                    category=category,
                    checks={"provider_output": False},
                    passed=False,
                    fingerprint=adapter.fingerprint,
                )
            )
            continue
        payload = summary.model_dump(mode="json")
        public_text = " ".join(_text_values(payload))
        evidence_ids = set(_evidence_ids(payload))
        required_ids = {
            str(transcript.segments[int(index)].id)
            for index in list(case["required_evidence_segments"])
        }
        unknown_action_checks = _unknown_action_checks(payload, transcript, case)
        fingerprint = adapter.fingerprint
        checks = {
            "template": summary.template == str(case["expected_template"]),
            "required_facts": all(
                _required_fact_present(term, public_text) for term in list(case["required_terms"])
            ),
            "required_evidence": required_ids.issubset(evidence_ids),
            "known_evidence_only": evidence_ids.issubset(
                {str(item.id) for item in transcript.segments}
            ),
            **unknown_action_checks,
            "unknown_markdown_label": _unknown_markdown_label(summary, category, case),
            "fingerprint": _valid_fingerprint(fingerprint),
        }
        results.append(
            EvaluationResult(
                case_id=str(case["case_id"]),
                category=category,
                checks=checks,
                passed=all(checks.values()),
                fingerprint=fingerprint,
            )
        )
    return results


def run(settings: Settings) -> int:
    if (
        not isinstance(settings.llm_api_key, SecretStr)
        or not settings.llm_api_key.get_secret_value()
    ):
        raise ValueError("summary evaluation requires LLM_API_KEY")
    if not settings.llm_base_url or not settings.llm_model:
        raise ValueError("summary evaluation requires LLM_BASE_URL and LLM_MODEL")
    adapter = OpenAISummaryAdapter(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key.get_secret_value(),
        model=settings.llm_model,
        max_context_chars=settings.summary_context_max_chars,
    )
    results = evaluate_cases(adapter, load_cases())
    for result in results:
        print(json.dumps(asdict(result), ensure_ascii=False, sort_keys=True))
    print(
        json.dumps(
            {"passed": sum(item.passed for item in results), "total": len(results)},
            sort_keys=True,
        )
    )
    return 0 if all(item.passed for item in results) else 1


def _transcript(case: dict[str, Any]) -> Transcript:
    case_id = str(case["case_id"])
    raw_segments = list(case["segments"])
    return Transcript(
        recording_id=uuid.uuid5(uuid.NAMESPACE_URL, f"summary-eval:{case_id}"),
        content_sha256=hashlib.sha256(
            json.dumps(raw_segments, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest(),
        revision=1,
        language="ko",
        needs_speaker_review=False,
        segments=[
            Segment(
                id=uuid.uuid5(uuid.NAMESPACE_URL, f"summary-eval:{case_id}:{index}"),
                start_ms=int(item["start_ms"]),
                end_ms=int(item["end_ms"]),
                local_speaker_id=str(item["speaker"]),
                text=str(item["text"]),
            )
            for index, item in enumerate(raw_segments)
        ],
    )


def _text_values(value: object) -> list[str]:
    if isinstance(value, dict):
        return [
            item
            for key, child in value.items()
            if key not in {"quote", "segment_id"}
            for item in _text_values(child)
        ]
    if isinstance(value, list):
        return [item for child in value for item in _text_values(child)]
    return [value] if isinstance(value, str) else []


def _evidence_ids(value: object) -> list[str]:
    if isinstance(value, dict):
        results: list[str] = []
        if isinstance(value.get("evidence"), list):
            results.extend(
                str(item["segment_id"])
                for item in value["evidence"]
                if isinstance(item, dict) and "segment_id" in item
            )
        for key, child in value.items():
            if key != "evidence":
                results.extend(_evidence_ids(child))
        return results
    if isinstance(value, list):
        return [item for child in value for item in _evidence_ids(child)]
    return []


def _required_fact_present(value: object, public_text: str) -> bool:
    alternatives = value if isinstance(value, list) else [value]
    normalized = public_text.replace(" ", "").casefold()
    return any(str(item).replace(" ", "").casefold() in normalized for item in alternatives)


def _unknown_action_checks(
    payload: dict[str, object], transcript: Transcript, case: dict[str, Any]
) -> dict[str, bool]:
    if not case.get("requires_unknown_action"):
        return {
            "unknown_action_present": True,
            "unknown_assignee_is_null": True,
            "unknown_due_date_is_null": True,
        }
    actions = payload.get("action_items")
    if not isinstance(actions, list):
        actions = []
    segment_id = str(transcript.segments[int(case["unknown_action_segment"])].id)
    matching = [
        item for item in actions if isinstance(item, dict) and segment_id in _evidence_ids(item)
    ]
    return {
        "unknown_action_present": bool(matching),
        "unknown_assignee_is_null": bool(matching)
        and all(item.get("assignee") is None for item in matching),
        "unknown_due_date_is_null": bool(matching)
        and all(item.get("due_date") is None for item in matching),
    }


def _unknown_markdown_label(summary: CategorySummary, category: str, case: dict[str, Any]) -> bool:
    if not case.get("requires_unknown_action"):
        return True
    markdown = render_summary_markdown(summary, category).decode()
    return "회의록" in markdown and markdown.count("확인되지 않음") >= 2


def _valid_fingerprint(value: dict[str, object]) -> bool:
    required = {
        "provider": "openai_compatible",
        "temperature": 0,
        "prompt_version": "openai-grounded-summary-v2",
        "schema_version": 1,
        "template_version": 1,
        "context_strategy": "full-or-all-chunk-evidence-v1",
    }
    return (
        all(value.get(key) == expected for key, expected in required.items())
        and isinstance(value.get("model"), str)
        and bool(value.get("model"))
        and all(
            isinstance(value.get(key), str) and len(str(value[key])) == 64
            for key in ("prompt_sha256", "schema_sha256")
        )
    )


def main() -> None:
    try:
        status = run(Settings())  # type: ignore[call-arg]
    except ValueError as error:
        raise SystemExit(str(error)) from None
    raise SystemExit(status)


if __name__ == "__main__":
    main()
