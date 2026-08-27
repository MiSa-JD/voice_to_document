from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import Any, Protocol

from pydantic import ValidationError

from app.schema import Classification, Transcript

CLASSIFICATION_SCHEMA_VERSION = 1
FAKE_CLASSIFICATION_MODEL = "fake-fixture-v1"
FAKE_CLASSIFICATION_PROMPT = "local-category-classifier-v1"


class ClassificationError(RuntimeError):
    code = "CLASSIFICATION_ERROR"


class ClassificationTimeoutError(ClassificationError):
    code = "CLASSIFICATION_TIMEOUT"


class MalformedClassificationError(ClassificationError):
    code = "MALFORMED_CLASSIFICATION"


class MissingClassificationFieldError(ClassificationError):
    code = "MISSING_CLASSIFICATION_FIELD"


class DisallowedClassificationCategoryError(ClassificationError):
    code = "DISALLOWED_CLASSIFICATION_CATEGORY"


class ClassificationAdapter(Protocol):
    @property
    def fingerprint(self) -> dict[str, object]: ...

    def classify(
        self,
        transcript: Transcript,
        allowed_categories: tuple[str, ...],
    ) -> Classification: ...


class FakeClassificationAdapter:
    """Deterministic, local-only adapter backed by committed fixture responses."""

    def __init__(self, response_loader: Callable[[str], object]) -> None:
        self._response_loader = response_loader

    @property
    def fingerprint(self) -> dict[str, object]:
        schema = json.dumps(
            Classification.model_json_schema(), sort_keys=True, separators=(",", ":")
        ).encode()
        return {
            "model": FAKE_CLASSIFICATION_MODEL,
            "prompt_sha256": _sha256(FAKE_CLASSIFICATION_PROMPT.encode()),
            "schema_sha256": _sha256(schema),
            "schema_version": CLASSIFICATION_SCHEMA_VERSION,
        }

    def classify(
        self,
        transcript: Transcript,
        allowed_categories: tuple[str, ...],
    ) -> Classification:
        if not allowed_categories:
            raise ValueError("allowed_categories must not be empty")
        return self.classify_content_hash(transcript.content_sha256, allowed_categories)

    def classify_content_hash(
        self,
        content_sha256: str,
        allowed_categories: tuple[str, ...],
    ) -> Classification:
        try:
            raw = self._response_loader(content_sha256)
        except TimeoutError as error:
            raise ClassificationTimeoutError("classification response timed out") from error
        return validate_classification_response(raw, allowed_categories)


def validate_classification_response(
    raw: object,
    allowed_categories: tuple[str, ...],
) -> Classification:
    if not allowed_categories:
        raise ValueError("allowed_categories must not be empty")
    value = _decode_response(raw)
    missing = tuple(
        name for name in ("category", "confidence", "reason", "schema_version") if name not in value
    )
    if missing:
        raise MissingClassificationFieldError(
            "classification response is missing required fields: " + ", ".join(missing)
        )
    try:
        result = Classification.model_validate(value)
    except ValidationError as error:
        raise MalformedClassificationError("classification response violates schema") from error
    if result.category not in allowed_categories:
        raise DisallowedClassificationCategoryError(
            f"classification category is not allowed: {result.category}"
        )
    return result


def _decode_response(raw: object) -> dict[str, Any]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as error:
            raise MalformedClassificationError(
                "classification response is not valid JSON"
            ) from error
    if not isinstance(raw, dict):
        raise MalformedClassificationError("classification response must be an object")
    return raw


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()
