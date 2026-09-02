from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app.artifacts import write_artifact
from app.db import connect
from app.document_identity import document_relative_path, ensure_document_identity
from app.renderer import MARKDOWN_SCHEMA_VERSION, render_transcript_markdown
from app.repository import record_audit_event
from app.schema import Classification, Segment, Transcript


class ReconciliationError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ReconciliationResult:
    inspected: int = 0
    repaired: int = 0
    failed: int = 0


def reconcile_markdown_artifacts(
    database_path: Path,
    transcript_root: Path,
    document_root: Path,
    logger: logging.Logger,
    markdown_renderer: Callable[[Transcript], bytes] = render_transcript_markdown,
) -> ReconciliationResult:
    transcript_root = transcript_root.resolve()
    document_root = document_root.resolve()
    with connect(database_path) as connection:
        rows = connection.execute(
            """
            SELECT a.recording_id, a.relative_path, a.revision
            FROM artifacts AS a
            JOIN recordings AS r ON r.id = a.recording_id AND r.revision = a.revision
            WHERE a.kind = 'transcript_markdown'
            ORDER BY r.created_at, r.id
            """
        ).fetchall()

    inspected = repaired = failed = 0
    for row in rows:
        recording_id = str(row["recording_id"])
        relative_path = Path(str(row["relative_path"]))
        old_path = (document_root / relative_path).resolve()
        legacy_path = relative_path.parent != Path(".")
        if not legacy_path and old_path.is_relative_to(document_root) and old_path.is_file():
            continue
        inspected += 1
        try:
            if not old_path.is_relative_to(document_root):
                raise ReconciliationError("MARKDOWN_PATH_INVALID")
            transcript = _rebuild_transcript(
                database_path, transcript_root, recording_id, int(row["revision"])
            )
            identity = ensure_document_identity(database_path, recording_id)
            target_relative = document_relative_path(identity.sequence, identity.title)
            try:
                markdown = markdown_renderer(transcript)
            except Exception as error:
                raise ReconciliationError("MARKDOWN_RENDER_FAILED") from error
            write_artifact(
                database_path,
                document_root,
                recording_id,
                "transcript_markdown",
                target_relative,
                markdown,
                transcript.revision,
                schema_version=MARKDOWN_SCHEMA_VERSION,
            )
            if legacy_path and old_path != document_root / target_relative:
                old_path.unlink(missing_ok=True)
                _remove_empty_parents(old_path.parent, document_root)
            repaired += 1
            logger.info(
                "markdown_reconciled",
                extra={"recording_id": recording_id, "stage": "reconciliation"},
            )
        except Exception as error:
            code = (
                error.code if isinstance(error, ReconciliationError) else "MARKDOWN_RECOVERY_FAILED"
            )
            failed += 1
            logger.error(
                "markdown_reconciliation_failed",
                extra={
                    "recording_id": recording_id,
                    "stage": "reconciliation",
                    "error_code": code,
                },
            )
            record_audit_event(
                database_path,
                "markdown_reconciliation_failed",
                {"error_code": code},
                recording_id,
            )
    return ReconciliationResult(inspected, repaired, failed)


def _rebuild_transcript(
    database_path: Path, transcript_root: Path, recording_id: str, revision: int
) -> Transcript:
    with connect(database_path) as connection:
        recording = connection.execute(
            """
            SELECT content_sha256, category, category_source,
                   category_confidence, category_reason
            FROM recordings WHERE id = ? AND revision = ?
            """,
            (recording_id, revision),
        ).fetchone()
        artifact = connection.execute(
            """
            SELECT relative_path FROM artifacts
            WHERE recording_id = ? AND kind = 'transcript_json' AND revision = ?
            """,
            (recording_id, revision),
        ).fetchone()
        segment_rows = connection.execute(
            """
            SELECT id, start_ms, end_ms, text, local_speaker_id, assignment_status,
                   overlapping_speaker_ids_json, person_id, speaker_name
            FROM segments WHERE recording_id = ?
            ORDER BY start_ms, end_ms, id
            """,
            (recording_id,),
        ).fetchall()
    if recording is None or artifact is None:
        raise ReconciliationError("RECOVERY_SOURCE_MISSING")
    json_path = (transcript_root / str(artifact["relative_path"])).resolve()
    if not json_path.is_relative_to(transcript_root) or not json_path.is_file():
        raise ReconciliationError("TRANSCRIPT_JSON_MISSING")
    try:
        stored = Transcript.model_validate_json(json_path.read_bytes())
    except Exception as error:
        raise ReconciliationError("TRANSCRIPT_JSON_INVALID") from error
    if (
        str(stored.recording_id) != recording_id
        or stored.revision != revision
        or stored.content_sha256 != str(recording["content_sha256"])
    ):
        raise ReconciliationError("TRANSCRIPT_IDENTITY_MISMATCH")
    if not segment_rows:
        raise ReconciliationError("SEGMENTS_MISSING")
    if recording["category"] is None or recording["category_source"] is None:
        raise ReconciliationError("CLASSIFICATION_MISSING")
    source = str(recording["category_source"])
    if source == "auto" and (
        recording["category_confidence"] is None or recording["category_reason"] is None
    ):
        raise ReconciliationError("CLASSIFICATION_MISSING")
    classification = Classification(
        schema_version=1,
        category=str(recording["category"]),
        confidence=(None if source == "manual" else float(recording["category_confidence"])),
        reason=(
            "사용자가 수동으로 선택한 범주입니다."
            if source == "manual"
            else str(recording["category_reason"])
        ),
    )
    if stored.classification != classification or stored.classification_source != source:
        raise ReconciliationError("CLASSIFICATION_MISMATCH")
    segments = [
        Segment.model_validate(
            {
                **dict(row),
                "overlapping_speaker_ids": json.loads(row["overlapping_speaker_ids_json"]),
            }
        )
        for row in segment_rows
    ]
    return stored.model_copy(
        update={
            "segments": segments,
            "classification": classification,
            "classification_source": source,
        }
    )


def _remove_empty_parents(directory: Path, root: Path) -> None:
    while directory != root and directory.is_relative_to(root):
        try:
            directory.rmdir()
        except OSError:
            break
        directory = directory.parent
