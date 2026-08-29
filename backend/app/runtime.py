from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.config import Settings
from app.discovery import StabilityTracker
from app.ingest import FileChangedDuringIngestError, ingest_file
from app.jobs import Job, claim_next_job, complete_job, fail_job, release_job
from app.media import MediaProbeError
from app.repository import RegistrationResult, record_audit_event

JobHandler = Callable[[Job], None]


class RetryableJobError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class PermanentJobError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def discover_once(
    settings: Settings,
    tracker: StabilityTracker,
    logger: logging.Logger,
) -> list[RegistrationResult]:
    results: list[RegistrationResult] = []
    for path in tracker.scan(settings.recording_input_dir):
        try:
            result = ingest_file(
                settings.database_path,
                path,
                recording_root=settings.recording_input_dir,
            )
        except MediaProbeError as error:
            _record_discovery_failure(settings, logger, path, error.code, str(error))
        except FileChangedDuringIngestError:
            logger.info("input_changed_during_ingest", extra={"file_name": path.name})
        except OSError:
            _record_discovery_failure(
                settings,
                logger,
                path,
                "INPUT_IO_ERROR",
                "input file could not be read",
            )
        else:
            logger.info(
                "recording_registered" if result.created else "recording_duplicate",
                extra={"recording_id": result.recording_id, "file_name": path.name},
            )
            results.append(result)
    return results


def process_one_job(
    database_path: Path,
    handler: JobHandler,
    logger: logging.Logger,
    stop_requested: Callable[[], bool] = lambda: False,
) -> bool:
    job = claim_next_job(database_path)
    if job is None:
        return False
    if stop_requested():
        release_job(database_path, job.id)
        return False
    try:
        handler(job)
    except RetryableJobError as error:
        retry_at = None
        if job.attempts < 3:
            retry_at = (datetime.now(UTC) + timedelta(seconds=2**job.attempts)).isoformat()
        fail_job(database_path, job.id, error.code, str(error), retry_at=retry_at)
        logger.warning(
            "job_retry_scheduled" if retry_at else "job_failed",
            extra={
                "job_id": job.id,
                "recording_id": job.recording_id,
                "stage": job.kind,
                "attempt": job.attempts,
                "error_code": error.code,
            },
        )
    except PermanentJobError as error:
        fail_job(database_path, job.id, error.code, str(error))
        logger.error(
            "job_failed",
            extra={
                "job_id": job.id,
                "recording_id": job.recording_id,
                "stage": job.kind,
                "attempt": job.attempts,
                "error_code": error.code,
            },
        )
    except Exception:
        fail_job(database_path, job.id, "UNEXPECTED_JOB_ERROR", "job handler failed")
        logger.exception(
            "job_failed",
            extra={
                "job_id": job.id,
                "recording_id": job.recording_id,
                "stage": job.kind,
                "attempt": job.attempts,
                "error_code": "UNEXPECTED_JOB_ERROR",
            },
        )
    else:
        complete_job(database_path, job.id)
        logger.info(
            "job_succeeded",
            extra={
                "job_id": job.id,
                "recording_id": job.recording_id,
                "stage": job.kind,
                "attempt": job.attempts,
            },
        )
    return True


def _record_discovery_failure(
    settings: Settings,
    logger: logging.Logger,
    path: Path,
    error_code: object,
    message: str,
) -> None:
    code = str(error_code)
    record_audit_event(
        settings.database_path,
        "input_rejected",
        {"file_name": path.name, "error_code": code, "message": message},
    )
    logger.warning(
        "input_rejected",
        extra={"file_name": path.name, "error_code": code, "stage": "discovery"},
    )
