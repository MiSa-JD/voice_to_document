from __future__ import annotations

import logging
import signal
import threading

from app.config import Settings
from app.db import migrate_database
from app.discovery import StabilityTracker
from app.jobs import Job
from app.log import configure_logging
from app.long_transcript import LongTranscriptClassifier
from app.openai_classification import OpenAIClassificationAdapter
from app.pipeline import FakePipelineHandler
from app.real_pipeline import RealSpeechPipelineHandler
from app.reconciliation import reconcile_markdown_artifacts
from app.runtime import JobHandler, discover_once, process_one_job


def run(settings: Settings | None = None, handler: JobHandler | None = None) -> int:
    config = settings or Settings()  # type: ignore[call-arg]
    logger = configure_logging("worker", config.log_level)
    stop = threading.Event()

    if config.uses_legacy_ai_mode:
        logger.warning(
            "legacy_ai_mode",
            extra={"stage": "configuration", "replacement": "SPEECH_MODE,DOCUMENT_MODE"},
        )

    def request_stop(signum: int, _frame: object) -> None:
        logger.info("worker_stop_requested", extra={"signal": signum})
        stop.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)

    migrate_database(config.database_path)
    reconcile_markdown_artifacts(
        config.database_path,
        config.transcript_root,
        config.document_root,
        logger,
    )
    tracker = StabilityTracker(config.file_stable_seconds)
    job_handler = handler or build_handler(config, logger)
    logger.info("worker_started", extra={"stage": "readiness"})
    while not stop.is_set():
        discover_once(config, tracker, logger)
        while process_one_job(config.database_path, job_handler, logger, stop.is_set):
            if stop.is_set():
                break
        stop.wait(timeout=config.scan_interval_seconds)
    logger.info("worker_stopped", extra={"stage": "shutdown"})
    return 0


def build_handler(config: Settings, logger: logging.Logger) -> JobHandler:
    classification_adapter = None
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
    if config.effective_speech_mode == "real":
        return RealSpeechPipelineHandler(
            config, logger, classification_adapter=classification_adapter
        )
    return FakePipelineHandler(config, logger, classification_adapter=classification_adapter)


def _r2_handler(logger: logging.Logger) -> JobHandler:
    def handle(job: Job) -> None:
        logger.info(
            "r2_job_handled",
            extra={
                "job_id": job.id,
                "recording_id": job.recording_id,
                "stage": job.kind,
                "attempt": job.attempts,
            },
        )

    return handle


def main() -> None:
    try:
        raise SystemExit(run())
    except Exception:
        logging.getLogger("worker").exception("worker_start_failed")
        raise


if __name__ == "__main__":
    main()
