from __future__ import annotations

from typing import Protocol

from app.schema import CategorySummary, Transcript


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
