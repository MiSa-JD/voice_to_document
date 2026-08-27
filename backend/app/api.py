from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.config import Settings
from app.db import check_database
from app.log import configure_logging
from app.recordings_api import ApiErrorBody, ApiErrorResponse, ApiProblem, create_recordings_router

DatabaseProbe = Callable[[Path], None]


def create_app(
    settings: Settings | None = None,
    database_probe: DatabaseProbe = check_database,
) -> FastAPI:
    config = settings or Settings()  # type: ignore[call-arg]
    logger = configure_logging("api", config.log_level)
    application = FastAPI(title="Voice to Document API", version="0.2.0")
    logger.info("api_configured", extra={"stage": "startup", **config.public_summary()})

    @application.get("/health/live", tags=["health"])
    def live() -> dict[str, str]:
        return {"status": "live"}

    @application.get("/health/ready", tags=["health"])
    def ready() -> JSONResponse:
        checks: dict[str, dict[str, str]] = {}
        ready_state = True

        try:
            database_probe(config.database_path)
            checks["database"] = {"status": "ok"}
        except (OSError, sqlite3.Error) as error:
            ready_state = False
            checks["database"] = {
                "status": "error",
                "message": _safe_error(error),
            }

        for name, path in _required_paths(config).items():
            if path.is_dir():
                checks[name] = {"status": "ok"}
            else:
                ready_state = False
                checks[name] = {
                    "status": "error",
                    "message": "configured directory is unavailable",
                }

        return JSONResponse(
            status_code=200 if ready_state else 503,
            content={"status": "ready" if ready_state else "not_ready", "checks": checks},
        )

    @application.exception_handler(ApiProblem)
    def handle_api_problem(_request: Request, error: ApiProblem) -> JSONResponse:
        body = ApiErrorResponse(
            error=ApiErrorBody(
                code=error.code,
                message=error.message,
                details=error.details,
            )
        )
        return JSONResponse(status_code=error.status_code, content=body.model_dump(mode="json"))

    @application.exception_handler(RequestValidationError)
    def handle_validation_error(_request: Request, error: RequestValidationError) -> JSONResponse:
        body = ApiErrorResponse(
            error=ApiErrorBody(
                code="INVALID_REQUEST",
                message="요청 값이 유효하지 않습니다.",
                details={"fields": [list(item["loc"]) for item in error.errors()]},
            )
        )
        return JSONResponse(status_code=422, content=body.model_dump(mode="json"))

    application.include_router(create_recordings_router(config))

    return application


def _required_paths(settings: Settings) -> dict[str, Path]:
    return {
        "recording_input": settings.recording_input_dir,
        "transcript_root": settings.transcript_root,
        "speaker_root": settings.speaker_root,
        "document_root": settings.document_root,
        "app_data": settings.app_data_dir,
    }


def _safe_error(error: BaseException) -> str:
    if isinstance(error, OSError):
        return "database path is unavailable"
    return "database connection failed"
