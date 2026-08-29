from __future__ import annotations

import mimetypes
import stat
from collections.abc import Iterator
from pathlib import Path
from typing import Annotated, BinaryIO

from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse, StreamingResponse

from app.config import Settings
from app.db import connect, migrate_database
from app.recordings_api import ApiErrorBody, ApiErrorResponse, ApiProblem

CHUNK_SIZE = 64 * 1024


def create_media_router(settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/api/media", tags=["media"])

    @router.get(
        "/{artifact_id}",
        response_model=None,
        response_class=StreamingResponse,
        responses={
            404: {"model": ApiErrorResponse},
            416: {"model": ApiErrorResponse},
        },
    )
    def get_media(
        artifact_id: str,
        range_header: Annotated[str | None, Header(alias="Range")] = None,
    ) -> StreamingResponse | JSONResponse:
        artifact = _media_artifact(settings, artifact_id)
        path = _safe_media_path(artifact["root"], artifact["relative_path"])
        try:
            size = path.stat().st_size
            source = path.open("rb")
        except OSError as error:
            raise ApiProblem(404, "MEDIA_NOT_FOUND", "미디어를 찾을 수 없습니다.") from error
        if size <= 0:
            source.close()
            raise ApiProblem(404, "MEDIA_NOT_FOUND", "미디어를 찾을 수 없습니다.")

        try:
            byte_range = parse_byte_range(range_header, size)
        except ValueError:
            source.close()
            body = ApiErrorResponse(
                error=ApiErrorBody(
                    code="RANGE_NOT_SATISFIABLE",
                    message="요청한 미디어 범위를 제공할 수 없습니다.",
                )
            )
            return JSONResponse(
                status_code=416,
                content=body.model_dump(mode="json"),
                headers={
                    "Accept-Ranges": "bytes",
                    "Content-Range": f"bytes */{size}",
                },
            )

        start, end = byte_range if byte_range is not None else (0, size - 1)
        length = end - start + 1
        headers = {
            "Accept-Ranges": "bytes",
            "Content-Length": str(length),
        }
        status_code = 200
        if byte_range is not None:
            status_code = 206
            headers["Content-Range"] = f"bytes {start}-{end}/{size}"
        return StreamingResponse(
            _read_range(source, start, length),
            status_code=status_code,
            media_type=_audio_mime_type(path),
            headers=headers,
        )

    return router


def parse_byte_range(value: str | None, size: int) -> tuple[int, int] | None:
    if value is None:
        return None
    if size <= 0 or not value.startswith("bytes="):
        raise ValueError("invalid range")
    specification = value[6:]
    if not specification or "," in specification or specification.count("-") != 1:
        raise ValueError("invalid range")
    start_text, end_text = specification.split("-", 1)
    if start_text:
        if not start_text.isascii() or not start_text.isdigit():
            raise ValueError("invalid range")
        start = int(start_text)
        if start >= size:
            raise ValueError("unsatisfiable range")
        if end_text:
            if not end_text.isascii() or not end_text.isdigit():
                raise ValueError("invalid range")
            requested_end = int(end_text)
            if requested_end < start:
                raise ValueError("invalid range")
            end = min(requested_end, size - 1)
        else:
            end = size - 1
        return start, end
    if not end_text.isascii() or not end_text.isdigit():
        raise ValueError("invalid range")
    suffix_length = int(end_text)
    if suffix_length <= 0:
        raise ValueError("invalid range")
    return max(0, size - suffix_length), size - 1


def _media_artifact(settings: Settings, artifact_id: str) -> dict[str, object]:
    migrate_database(settings.database_path)
    with connect(settings.database_path) as connection:
        artifact = connection.execute(
            """
            SELECT artifacts.kind, artifacts.relative_path,
                   EXISTS(
                       SELECT 1 FROM speaker_clips
                       WHERE speaker_clips.artifact_id = artifacts.id
                   ) AS registered_clip
            FROM artifacts WHERE artifacts.id = ?
            """,
            (artifact_id,),
        ).fetchone()
    if artifact is None:
        raise ApiProblem(404, "MEDIA_NOT_FOUND", "미디어를 찾을 수 없습니다.")
    kind = str(artifact["kind"])
    if kind == "recording_audio":
        root = settings.recording_input_dir
    elif kind.startswith("speaker_clip:") and bool(artifact["registered_clip"]):
        root = settings.speaker_root
    else:
        raise ApiProblem(404, "MEDIA_NOT_FOUND", "미디어를 찾을 수 없습니다.")
    return {"root": root, "relative_path": str(artifact["relative_path"])}


def _safe_media_path(root_value: object, relative_value: object) -> Path:
    root = Path(str(root_value)).resolve()
    try:
        path = (root / str(relative_value)).resolve(strict=True)
        if not path.is_relative_to(root) or not stat.S_ISREG(path.stat().st_mode):
            raise ValueError("unsafe media path")
    except (OSError, ValueError) as error:
        raise ApiProblem(404, "MEDIA_NOT_FOUND", "미디어를 찾을 수 없습니다.") from error
    return path


def _read_range(source: BinaryIO, start: int, length: int) -> Iterator[bytes]:
    try:
        source.seek(start)
        remaining = length
        while remaining > 0:
            chunk = source.read(min(CHUNK_SIZE, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk
    finally:
        source.close()


def _audio_mime_type(path: Path) -> str:
    overrides = {".m4a": "audio/mp4", ".wav": "audio/wav"}
    return overrides.get(path.suffix.casefold()) or mimetypes.guess_type(path.name)[0] or "audio/*"
