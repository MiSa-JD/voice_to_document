from __future__ import annotations

import hashlib
import json
from typing import Protocol

from app.schema import CategorySummary, Transcript, summary_template_for_category


class SummaryAdapter(Protocol):
    @property
    def fingerprint(self) -> dict[str, object]: ...

    def summarize(self, transcript: Transcript, category: str) -> CategorySummary: ...


class SummaryError(RuntimeError):
    code = "SUMMARY_INVALID_OUTPUT"


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
