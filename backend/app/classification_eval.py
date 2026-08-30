from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from pydantic import SecretStr

from app.config import Settings
from app.openai_classification import OpenAIClassificationAdapter
from app.schema import Segment, Transcript

FIXTURE_PATH = Path(__file__).parent.parent / "tests" / "fixtures" / "classification_eval.json"


@dataclass(frozen=True)
class EvaluationResult:
    case_id: str
    expected_category: str
    actual_category: str
    passed: bool
    schema_version: int
    confidence: float
    has_reason: bool
    model: str
    fingerprint: dict[str, object]


def load_cases(path: Path = FIXTURE_PATH) -> list[dict[str, Any]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list) or len(value) != 5:
        raise ValueError("classification evaluation requires exactly five cases")
    return value


def evaluate_cases(
    adapter: OpenAIClassificationAdapter,
    categories: tuple[str, ...],
    cases: list[dict[str, Any]],
) -> list[EvaluationResult]:
    results: list[EvaluationResult] = []
    for case in cases:
        case_id = str(case["case_id"])
        segments = list(case["segments"])
        transcript = Transcript(
            recording_id=uuid.uuid5(uuid.NAMESPACE_URL, f"classification-eval:{case_id}"),
            content_sha256=hashlib.sha256(
                json.dumps(segments, ensure_ascii=False, sort_keys=True).encode()
            ).hexdigest(),
            revision=1,
            language="ko",
            needs_speaker_review=False,
            segments=[
                Segment(
                    id=uuid.uuid5(uuid.NAMESPACE_URL, f"classification-eval:{case_id}:{index}"),
                    start_ms=int(item["start_ms"]),
                    end_ms=int(item["end_ms"]),
                    local_speaker_id=str(item["speaker"]),
                    text=str(item["text"]),
                )
                for index, item in enumerate(segments)
            ],
        )
        classification = adapter.classify(transcript, categories)
        if classification.confidence is None:
            raise ValueError("automatic classification must include confidence")
        expected = str(case["expected_category"])
        results.append(
            EvaluationResult(
                case_id=case_id,
                expected_category=expected,
                actual_category=classification.category,
                passed=classification.category == expected,
                schema_version=classification.schema_version,
                confidence=classification.confidence,
                has_reason=bool(classification.reason.strip()),
                model=adapter.model,
                fingerprint=adapter.fingerprint,
            )
        )
    return results


def run(settings: Settings) -> int:
    if (
        not isinstance(settings.llm_api_key, SecretStr)
        or not settings.llm_api_key.get_secret_value()
    ):
        raise ValueError("classification evaluation requires LLM_API_KEY")
    if not settings.llm_base_url or not settings.llm_model:
        raise ValueError("classification evaluation requires LLM_BASE_URL and LLM_MODEL")
    adapter = OpenAIClassificationAdapter(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key.get_secret_value(),
        model=settings.llm_model,
    )
    results = evaluate_cases(adapter, settings.categories, load_cases())
    for result in results:
        print(json.dumps(asdict(result), ensure_ascii=False, sort_keys=True))
    passed = sum(result.passed for result in results)
    print(json.dumps({"passed": passed, "total": len(results)}, sort_keys=True))
    return 0 if passed == len(results) and all(item.has_reason for item in results) else 1


def main() -> None:
    try:
        status = run(Settings())  # type: ignore[call-arg]
    except ValueError as error:
        raise SystemExit(str(error)) from None
    raise SystemExit(status)


if __name__ == "__main__":
    main()
