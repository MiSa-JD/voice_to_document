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


@dataclass(frozen=True)
class ArtifactContent:
    kind: str
    relative_path: Path
    content: bytes
    schema_version: int = 1


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
        directory_fd = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
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


def write_summary_artifacts(
    database_path: Path,
    root: Path,
    recording_id: str,
    revision: int,
    category_slug: str,
    json_content: bytes,
    markdown_content: bytes,
    *,
    before_replace: Callable[[str], None] | None = None,
    before_register: Callable[[], None] | None = None,
) -> tuple[ArtifactResult, ArtifactResult]:
    migrate_database(database_path)
    root = root.resolve()
    base = Path(category_slug) / "요약" / recording_id / "revisions"
    contents = (
        ArtifactContent("summary_json", base / f"{revision}.json", json_content),
        ArtifactContent("summary_markdown", base / f"{revision}.md", markdown_content),
    )
    staged: list[tuple[ArtifactContent, Path, Path, str]] = []
    try:
        for item in contents:
            target = (root / item.relative_path).resolve()
            if not target.is_relative_to(root):
                raise ValueError("artifact path leaves configured root")
            target.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=target.parent,
                prefix=f".{target.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary.write(item.content)
                temporary.flush()
                os.fsync(temporary.fileno())
                staged.append(
                    (
                        item,
                        Path(temporary.name),
                        target,
                        hashlib.sha256(item.content).hexdigest(),
                    )
                )
        for item, staged_path, target, _digest in staged:
            if before_replace is not None:
                before_replace(item.kind)
            os.replace(staged_path, target)
            directory_fd = os.open(target.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        if before_register is not None:
            before_register()
        timestamp = utc_now()
        old_paths: list[Path] = []
        results: list[ArtifactResult] = []
        with connect(database_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            all_previous = connection.execute(
                """
                SELECT id, relative_path FROM artifacts
                WHERE recording_id = ? AND kind IN ('summary_json', 'summary_markdown')
                """,
                (recording_id,),
            ).fetchall()
            previous = [
                row
                for row in all_previous
                if Path(str(row["relative_path"])).parts[:1] != (category_slug,)
            ]
            for item, _temporary, target, digest in staged:
                existing = connection.execute(
                    """
                    SELECT id FROM artifacts
                    WHERE recording_id = ? AND kind = ? AND revision = ?
                    """,
                    (recording_id, item.kind, revision),
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
                        item.kind,
                        item.relative_path.as_posix(),
                        digest,
                        item.schema_version,
                        revision,
                        timestamp,
                    ),
                )
                results.append(ArtifactResult(artifact_id, digest, target))
            if previous:
                connection.executemany(
                    "DELETE FROM artifacts WHERE id = ?",
                    [(str(row["id"]),) for row in previous],
                )
                old_paths = [(root / str(row["relative_path"])).resolve() for row in previous]
            connection.commit()
        for path in old_paths:
            if path.is_relative_to(root):
                path.unlink(missing_ok=True)
                _remove_empty_parents(path.parent, root)
        return results[0], results[1]
    finally:
        for _item, staged_path, _target, _digest in staged:
            staged_path.unlink(missing_ok=True)


def _remove_empty_parents(directory: Path, root: Path) -> None:
    while directory != root and directory.is_relative_to(root):
        try:
            directory.rmdir()
        except OSError:
            break
        directory = directory.parent
