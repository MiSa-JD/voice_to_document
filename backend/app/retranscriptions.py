from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

from app.config import Settings
from app.db import connect, utc_now
from app.schema import Transcript


@dataclass(frozen=True)
class RetranscriptionInput:
    request_id: str
    base_revision: int
    target_revision: int
    language: str | None
    initial_prompt: str | None


def request_for_job(database_path: Path, job_id: str) -> RetranscriptionInput | None:
    with connect(database_path) as connection:
        row = connection.execute(
            """
            SELECT id, base_revision, target_revision, requested_language,
                   content_hint, terms_json
            FROM retranscription_requests WHERE job_id = ?
            """,
            (job_id,),
        ).fetchone()
    if row is None:
        return None
    terms = json.loads(str(row["terms_json"] or "[]"))
    description = str(row["content_hint"]) if row["content_hint"] else None
    parts = [description or ""]
    if terms:
        parts.append("전문용어: " + ", ".join(str(item) for item in terms))
    prompt = "\n".join(part for part in parts if part) or None
    requested = str(row["requested_language"])
    return RetranscriptionInput(
        request_id=str(row["id"]),
        base_revision=int(row["base_revision"]),
        target_revision=int(row["target_revision"]),
        language=None if requested == "auto" else requested,
        initial_prompt=prompt,
    )


def commit_retranscription(
    settings: Settings,
    job_id: str,
    transcript: Transcript,
) -> None:
    request = request_for_job(settings.database_path, job_id)
    if request is None or transcript.revision != request.target_revision:
        raise ValueError("retranscription request does not match transcript")
    history_relative = _preserve_history(settings, str(transcript.recording_id), request)
    relative_path = (
        Path(str(transcript.recording_id))
        / "revisions"
        / str(transcript.revision)
        / "transcript.json"
    )
    content = (
        json.dumps(transcript.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, indent=2)
        + "\n"
    ).encode()
    target = _atomic_stage(settings.transcript_root, relative_path, content)
    digest = hashlib.sha256(content).hexdigest()
    timestamp = utc_now()
    recording_id = str(transcript.recording_id)
    speaker_ids = {
        speaker_id
        for segment in transcript.segments
        for speaker_id in (
            ([segment.local_speaker_id] if segment.local_speaker_id else [])
            + segment.overlapping_speaker_ids
        )
    }
    try:
        with connect(settings.database_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute(
                "SELECT revision FROM recordings WHERE id = ?", (recording_id,)
            ).fetchone()
            if current is None or int(current["revision"]) != request.base_revision:
                raise ValueError("recording changed while retranscription was running")
            connection.execute(
                "DELETE FROM recording_speakers WHERE recording_id = ?", (recording_id,)
            )
            connection.execute("DELETE FROM segments WHERE recording_id = ?", (recording_id,))
            connection.executemany(
                """
                INSERT INTO recording_speakers(
                    recording_id, local_speaker_id, speaker_source, revision,
                    clip_status, created_at, updated_at
                ) VALUES (?, ?, 'unresolved', ?, 'pending', ?, ?)
                """,
                [
                    (recording_id, speaker_id, transcript.revision, timestamp, timestamp)
                    for speaker_id in sorted(speaker_ids)
                ],
            )
            connection.executemany(
                """
                INSERT INTO segments(
                    id, recording_id, start_ms, end_ms, text, local_speaker_id,
                    assignment_status, overlapping_speaker_ids_json, speaker_source,
                    revision
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'unresolved', ?)
                """,
                [
                    (
                        str(segment.id),
                        recording_id,
                        segment.start_ms,
                        segment.end_ms,
                        segment.text,
                        segment.local_speaker_id,
                        segment.assignment_status,
                        json.dumps(segment.overlapping_speaker_ids, sort_keys=True),
                        transcript.revision,
                    )
                    for segment in transcript.segments
                ],
            )
            connection.execute(
                """
                UPDATE recordings
                SET revision = ?, status = 'CLASSIFYING', category = NULL,
                    category_confidence = NULL, category_reason = NULL,
                    needs_speaker_review = 1, last_error_code = NULL,
                    last_error_message = NULL, updated_at = ?
                WHERE id = ?
                """,
                (transcript.revision, timestamp, recording_id),
            )
            connection.execute(
                """
                INSERT INTO artifacts(
                    id, recording_id, kind, relative_path, content_sha256,
                    schema_version, revision, created_at
                ) VALUES (?, ?, 'transcript_json', ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    recording_id,
                    relative_path.as_posix(),
                    digest,
                    transcript.schema_version,
                    transcript.revision,
                    timestamp,
                ),
            )
            classify_job_id = str(uuid.uuid4())
            connection.execute(
                """
                INSERT INTO jobs(
                    id, recording_id, kind, status, attempts, available_at,
                    created_at, updated_at, input_revision, settings_fingerprint
                ) VALUES (?, ?, 'classify', 'queued', 0, ?, ?, ?, ?, ?)
                """,
                (
                    classify_job_id,
                    recording_id,
                    timestamp,
                    timestamp,
                    timestamp,
                    transcript.revision,
                    "retranscription-classify-v1",
                ),
            )
            connection.execute(
                """
                UPDATE retranscription_requests
                SET new_segment_count = ?, unresolved_speaker_count = ?,
                    history_relative_dir = ?, updated_at = ?
                WHERE job_id = ?
                """,
                (
                    len(transcript.segments),
                    len(speaker_ids),
                    history_relative.as_posix(),
                    timestamp,
                    job_id,
                ),
            )
            connection.commit()
    except Exception:
        target.unlink(missing_ok=True)
        raise


def _preserve_history(settings: Settings, recording_id: str, request: RetranscriptionInput) -> Path:
    relative = Path("history") / recording_id / str(request.base_revision)
    target_root = (settings.app_data_dir / relative).resolve()
    if not target_root.is_relative_to(settings.app_data_dir.resolve()):
        raise ValueError("history path leaves app data")
    roots = {
        "transcript_json": settings.transcript_root,
        "transcript_markdown": settings.document_root,
        "summary_json": settings.summary_root,
        "summary_markdown": settings.summary_root,
    }
    with connect(settings.database_path) as connection:
        rows = connection.execute(
            """
            SELECT kind, relative_path FROM artifacts
            WHERE recording_id = ? AND revision = ?
              AND kind IN ('transcript_json', 'transcript_markdown',
                           'summary_json', 'summary_markdown')
            """,
            (recording_id, request.base_revision),
        ).fetchall()
    target_root.mkdir(parents=True, exist_ok=True)
    for row in rows:
        kind = str(row["kind"])
        root = roots[kind].resolve()
        source = (root / str(row["relative_path"])).resolve()
        if not source.is_relative_to(root) or not source.is_file():
            raise ValueError("history source artifact is unavailable")
        shutil.copy2(source, target_root / f"{kind}{source.suffix}")
    return relative


def _atomic_stage(root: Path, relative: Path, content: bytes) -> Path:
    root = root.resolve()
    target = (root / relative).resolve()
    if not target.is_relative_to(root):
        raise ValueError("staging path leaves transcript root")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
            temporary = Path(handle.name)
        os.replace(temporary, target)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return target
