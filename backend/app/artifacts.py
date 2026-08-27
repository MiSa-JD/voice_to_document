from __future__ import annotations

import hashlib
import os
import tempfile
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app.categories import category_slug
from app.db import connect, migrate_database, utc_now


@dataclass(frozen=True)
class ArtifactResult:
    artifact_id: str
    content_sha256: str
    path: Path


def write_artifact(
    database_path: Path,
    root: Path,
    recording_id: str,
    kind: str,
    relative_path: Path,
    content: bytes,
    revision: int,
    schema_version: int = 1,
    before_replace: Callable[[], None] | None = None,
    before_register: Callable[[], None] | None = None,
) -> ArtifactResult:
    migrate_database(database_path)
    root = root.resolve()
    target = (root / relative_path).resolve()
    if not target.is_relative_to(root):
        raise ValueError("artifact path leaves configured root")
    target.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(content).hexdigest()

    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        if before_replace is not None:
            before_replace()
        os.replace(temporary_path, target)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

    if before_register is not None:
        before_register()
    with connect(database_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        existing = connection.execute(
            """
            SELECT id FROM artifacts
            WHERE recording_id = ? AND kind = ? AND revision = ?
            """,
            (recording_id, kind, revision),
        ).fetchone()
        artifact_id = str(existing["id"]) if existing is not None else str(uuid.uuid4())
        connection.execute(
            """
            INSERT INTO artifacts(
                id, recording_id, kind, relative_path, content_sha256,
                schema_version, revision, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(recording_id, kind, revision) DO UPDATE SET
                relative_path = excluded.relative_path,
                content_sha256 = excluded.content_sha256,
                schema_version = excluded.schema_version,
                created_at = excluded.created_at
            """,
            (
                artifact_id,
                recording_id,
                kind,
                relative_path.as_posix(),
                digest,
                schema_version,
                revision,
                utc_now(),
            ),
        )
        connection.commit()
    return ArtifactResult(artifact_id, digest, target)


def safe_category_slug(category: str) -> str:
    return category_slug(category)
