from __future__ import annotations

import hashlib
from pathlib import Path

from app.media import probe_media
from app.repository import RegistrationResult, register_recording


class FileChangedDuringIngestError(RuntimeError):
    pass


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def ingest_file(
    database_path: Path,
    source_path: Path,
    recording_root: Path | None = None,
) -> RegistrationResult:
    before = source_path.stat()
    media = probe_media(source_path)
    content_sha256 = sha256_file(source_path)
    after = source_path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise FileChangedDuringIngestError("file changed while it was being inspected")
    return register_recording(
        database_path=database_path,
        source_path=source_path,
        content_sha256=content_sha256,
        size_bytes=after.st_size,
        duration_ms=media.duration_ms,
        recorded_at=media.recorded_at,
        recording_root=recording_root,
    )
