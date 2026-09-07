from __future__ import annotations

import hashlib
import json
from typing import Protocol

from pydantic import ValidationError

from app.schema import (
    CategorySummary,
    SummaryValidationError,
    Transcript,
    summary_template_for_category,
)


class SummaryAdapter(Protocol):
    @property
    def fingerprint(self) -> dict[str, object]: ...

    def summarize(self, transcript: Transcript, category: str) -> CategorySummary: ...


class SummaryError(RuntimeError):
    code = "SUMMARY_INVALID_OUTPUT"

    def __init__(self, message: str, *, reason: str = "unspecified") -> None:
        super().__init__(message)
        self.reason = (
            reason
            if reason
            in {
                "response_format",
                "refusal",
                "incomplete",
                "empty_output",
                "json_decode",
                "schema",
                "evidence",
                "request_rejected",
                "input_validation",
                "unexpected",
            }
            else "unspecified"
        )


class SummaryProviderError(SummaryError):
    pass


class RetryableSummaryError(SummaryError):
    code = "SUMMARY_PROVIDER_UNAVAILABLE"


class SummaryTimeoutError(RetryableSummaryError):
    code = "SUMMARY_TIMEOUT"


def summary_settings_fingerprint(adapter: SummaryAdapter, category: str) -> str:
    return _summary_fingerprint(adapter.fingerprint, category)


def configured_summary_settings_fingerprint(settings: object, category: str) -> str:
    from app.config import Settings
    from app.openai_summary import OpenAISummaryAdapter

    if not isinstance(settings, Settings):
        raise TypeError("settings must be Settings")
    if settings.effective_document_mode == "real":
        if settings.llm_model is None:
            raise ValueError("LLM_MODEL is required for real summaries")
        adapter_fingerprint = OpenAISummaryAdapter(
            base_url=settings.llm_base_url or "https://invalid.local/v1",
            api_key="",
            model=settings.llm_model,
            max_context_chars=settings.summary_context_max_chars,
        ).fingerprint
    else:
        adapter_fingerprint = {"provider": "fake", "model": "fixture-summary-v2"}
    return _summary_fingerprint(adapter_fingerprint, category)


def _summary_fingerprint(adapter_fingerprint: dict[str, object], category: str) -> str:
    payload = {
        "adapter": adapter_fingerprint,
        "category": category,
        "template": summary_template_for_category(category),
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


_DIAGNOSTIC_FIELDS = frozenset(
    [
        "template",
        "core_topics",
        "concepts",
        "examples",
        "review_items",
        "purpose",
        "discussion",
        "decisions",
        "action_items",
        "open_questions",
        "main_topics",
        "agreements",
        "reminders",
        "games",
        "preferences",
        "follow_ups",
        "key_summary",
        "key_facts",
        "facts",
        "text",
        "evidence",
        "task",
        "assignee",
        "due_date",
        "segment_id",
        "start_ms",
        "end_ms",
        "quote",
    ]
)
_DIAGNOSTIC_TYPES = frozenset(
    [
        "missing",
        "extra_forbidden",
        "model_type",
        "list_type",
        "dict_type",
        "string_type",
        "string_too_short",
        "string_too_long",
        "int_type",
        "int_parsing",
        "int_from_float",
        "finite_number",
        "greater_than",
        "greater_than_equal",
        "less_than",
        "less_than_equal",
        "too_short",
        "too_long",
        "literal_error",
        "uuid_type",
        "uuid_parsing",
        "uuid_version",
        "value_error",
    ]
)


def _safe_field_path(location: tuple[str | int, ...]) -> str:
    path = ""
    for part in location:
        if isinstance(part, int):
            path += f"[{part}]"
        else:
            field = part if part in _DIAGNOSTIC_FIELDS else "unknown_field"
            path += ("." if path else "") + field
    return path or "$"


def summary_validation_details(error: Exception, *, prefix: str | None = None) -> dict[str, object]:
    if isinstance(error, ValidationError):
        errors = error.errors(include_input=False, include_context=False, include_url=False)
        details = [
            {
                "validation_type": item["type"]
                if item["type"] in _DIAGNOSTIC_TYPES
                else "unknown_type",
                "field_path": _safe_field_path(((prefix,) if prefix else ()) + item["loc"]),
            }
            for item in errors[:5]
        ]
        count = error.error_count()
    elif isinstance(error, SummaryValidationError):
        details = [{"validation_type": error.validation_type, "field_path": error.field_path}]
        count = 1
    else:
        details = [
            {
                "validation_type": "invalid_json"
                if isinstance(error, json.JSONDecodeError)
                else "unknown_type",
                "field_path": "$",
            }
        ]
        count = 1
    return {
        "validation_errors": details,
        "error_count": count,
        "omitted_error_count": count - len(details),
    }
