from __future__ import annotations

from app.classification import ClassificationAdapter
from app.config import Settings
from app.long_transcript import LongTranscriptClassifier
from app.openai_classification import OpenAIClassificationAdapter
from app.openai_summary import OpenAISummaryAdapter
from app.summary import SummaryAdapter


def build_document_adapters(
    config: Settings,
) -> tuple[ClassificationAdapter | None, SummaryAdapter | None]:
    """Build document configuration without initializing speech runtimes."""
    classification_adapter = None
    summary_adapter = None
    if config.effective_document_mode == "real":
        if config.llm_api_key is None or config.llm_base_url is None or config.llm_model is None:
            raise RuntimeError("real document settings were not validated")
        backend = OpenAIClassificationAdapter(
            base_url=config.llm_base_url,
            api_key=config.llm_api_key.get_secret_value(),
            model=config.llm_model,
        )
        classification_adapter = LongTranscriptClassifier(
            backend,
            backend,
            backend,
            max_context_chars=config.classification_context_max_chars,
        )
        summary_adapter = OpenAISummaryAdapter(
            base_url=config.llm_base_url,
            api_key=config.llm_api_key.get_secret_value(),
            model=config.llm_model,
            max_context_chars=config.summary_context_max_chars,
            timeout_seconds=config.summary_request_timeout_seconds,
        )
    return classification_adapter, summary_adapter
