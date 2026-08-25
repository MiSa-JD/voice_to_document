from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any, cast

from app.adapters import FakeAdapters, FakeFixtureNotFoundError
from app.artifacts import safe_category_slug, write_artifact
from app.config import Settings
from app.db import connect, utc_now
from app.jobs import Job
from app.runtime import PermanentJobError, RetryableJobError
from app.schema import Classification, MeetingSummary, RecordingStatus, Segment, Transcript
from app.state import transition_and_enqueue, transition_recording


class FakePipelineHandler:
    def __init__(
        self,
        settings: Settings,
        logger: logging.Logger,
        adapters: FakeAdapters | None = None,
    ) -> None:
        self.settings = settings
        self.logger = logger
        self.adapters = adapters or FakeAdapters()

    def __call__(self, job: Job) -> None:
        try:
            if job.kind == "transcribe":
                self._transcribe(job)
            elif job.kind == "classify":
                self._classify(job)
            elif job.kind == "summarize":
                self._summarize(job)
            else:
                raise PermanentJobError("UNSUPPORTED_JOB_KIND", f"unsupported job: {job.kind}")
        except OSError as error:
            self._mark_failed(job.recording_id, "ARTIFACT_IO_ERROR", "결과 파일을 쓸 수 없습니다.")
            raise RetryableJobError("ARTIFACT_IO_ERROR", "artifact write failed") from error
        except (FakeFixtureNotFoundError, ValueError) as error:
            self._mark_failed(
                job.recording_id, "INVALID_FAKE_RESULT", "가짜 결과가 유효하지 않습니다."
            )
            raise PermanentJobError("INVALID_FAKE_RESULT", "fake result is invalid") from error
        except (PermanentJobError, RetryableJobError):
            raise
        except Exception:
            self._mark_failed(job.recording_id, "PIPELINE_ERROR", "처리 단계가 실패했습니다.")
            raise

    def _transcribe(self, job: Job) -> None:
        recording = self._recording(job.recording_id)
        self._enter(job.recording_id, RecordingStatus.TRANSCRIBING)
        transcript = self.adapters.transcribe(
            job.recording_id,
            str(recording["content_sha256"]),
            int(recording["revision"]),
        )
        self._replace_segments(transcript)
        self._write_transcript_json(transcript)
        if transcript.needs_speaker_review:
            self._set_review_required(job.recording_id)
            return
        transition_and_enqueue(
            self.settings.database_path,
            job.recording_id,
            RecordingStatus.CLASSIFYING,
            "classify",
            transcript.revision,
            "fake-document-v1",
        )

    def _classify(self, job: Job) -> None:
        recording = self._recording(job.recording_id)
        classification = self.adapters.classify(str(recording["content_sha256"]))
        classification.ensure_allowed(self.settings.categories)
        self._save_classification(job.recording_id, classification)
        self._write_transcript_markdown(job.recording_id, classification)
        if classification.category in self.settings.auto_summary_categories:
            transition_and_enqueue(
                self.settings.database_path,
                job.recording_id,
                RecordingStatus.SUMMARIZING,
                "summarize",
                int(recording["revision"]),
                "fake-summary-v1",
            )
        else:
            transition_recording(
                self.settings.database_path,
                job.recording_id,
                RecordingStatus.READY_FOR_SUMMARY,
            )
            transition_recording(
                self.settings.database_path,
                job.recording_id,
                RecordingStatus.COMPLETED,
            )

    def _summarize(self, job: Job) -> None:
        recording = self._recording(job.recording_id)
        summary = self.adapters.summarize(str(recording["content_sha256"]))
        category = str(recording["category"])
        slug = safe_category_slug(category)
        revision = int(recording["revision"])
        metadata = {
            "schema_version": 1,
            "recording_id": job.recording_id,
            "content_sha256": str(recording["content_sha256"]),
            "revision": revision,
            "created_at": utc_now(),
            "category": category,
            "category_slug": slug,
            "summary": summary.model_dump(mode="json"),
        }
        base = Path(slug) / "요약"
        write_artifact(
            self.settings.database_path,
            self.settings.summary_root,
            job.recording_id,
            "summary_json",
            base / f"{job.recording_id}.json",
            _json_bytes(metadata),
            revision,
        )
        write_artifact(
            self.settings.database_path,
            self.settings.summary_root,
            job.recording_id,
            "summary_markdown",
            base / f"{job.recording_id}.md",
            _summary_markdown(summary).encode("utf-8"),
            revision,
        )
        transition_recording(
            self.settings.database_path,
            job.recording_id,
            RecordingStatus.COMPLETED,
        )

    def _recording(self, recording_id: str) -> sqlite3.Row:
        with connect(self.settings.database_path) as connection:
            row = connection.execute(
                "SELECT * FROM recordings WHERE id = ?", (recording_id,)
            ).fetchone()
        if row is None:
            raise PermanentJobError("RECORDING_NOT_FOUND", "recording does not exist")
        return cast(sqlite3.Row, row)

    def _enter(self, recording_id: str, target: RecordingStatus) -> None:
        with connect(self.settings.database_path) as connection:
            status = RecordingStatus(
                str(
                    connection.execute(
                        "SELECT status FROM recordings WHERE id = ?", (recording_id,)
                    ).fetchone()["status"]
                )
            )
        if status is target:
            return
        transition_recording(self.settings.database_path, recording_id, target)

    def _replace_segments(self, transcript: Transcript) -> None:
        with connect(self.settings.database_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "DELETE FROM segments WHERE recording_id = ?", (str(transcript.recording_id),)
            )
            connection.executemany(
                """
                INSERT INTO segments(
                    id, recording_id, start_ms, end_ms, text, local_speaker_id,
                    person_id, speaker_name, revision
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        str(segment.id),
                        str(transcript.recording_id),
                        segment.start_ms,
                        segment.end_ms,
                        segment.text,
                        segment.local_speaker_id,
                        str(segment.person_id) if segment.person_id else None,
                        segment.speaker_name,
                        transcript.revision,
                    )
                    for segment in transcript.segments
                ],
            )
            connection.commit()

    def _write_transcript_json(self, transcript: Transcript) -> None:
        recording_id = str(transcript.recording_id)
        write_artifact(
            self.settings.database_path,
            self.settings.transcript_root,
            recording_id,
            "transcript_json",
            Path(recording_id) / "transcript.json",
            _json_bytes(transcript.model_dump(mode="json")),
            transcript.revision,
        )

    def _set_review_required(self, recording_id: str) -> None:
        with connect(self.settings.database_path) as connection:
            connection.execute(
                "UPDATE recordings SET needs_speaker_review = 1 WHERE id = ?", (recording_id,)
            )
        transition_recording(
            self.settings.database_path, recording_id, RecordingStatus.SPEAKER_REVIEW
        )

    def _save_classification(self, recording_id: str, classification: Classification) -> None:
        with connect(self.settings.database_path) as connection:
            connection.execute(
                """
                UPDATE recordings
                SET category = ?, category_confidence = ?, category_reason = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    classification.category,
                    classification.confidence,
                    classification.reason,
                    utc_now(),
                    recording_id,
                ),
            )

    def _write_transcript_markdown(self, recording_id: str, classification: Classification) -> None:
        recording = self._recording(recording_id)
        segments = self._segments(recording_id)
        lines = [
            f"# {recording['original_name']}",
            "",
            f"- 원본 파일: {recording['original_name']}",
            f"- 범주: {classification.category}",
            f"- 처리 시각: {utc_now()}",
            "",
            "## 전체 내용",
            "",
        ]
        for segment in segments:
            speaker = segment.speaker_name or f"미확정({segment.local_speaker_id})"
            lines.extend([f"**[{_timestamp(segment.start_ms)}] {speaker}**", segment.text, ""])
        write_artifact(
            self.settings.database_path,
            self.settings.transcript_root,
            recording_id,
            "transcript_markdown",
            Path(recording_id) / "transcript.md",
            "\n".join(lines).encode("utf-8"),
            int(recording["revision"]),
        )

    def _segments(self, recording_id: str) -> list[Segment]:
        with connect(self.settings.database_path) as connection:
            rows = connection.execute(
                """
                SELECT id, start_ms, end_ms, local_speaker_id, person_id, speaker_name, text
                FROM segments WHERE recording_id = ? ORDER BY start_ms, end_ms, id
                """,
                (recording_id,),
            ).fetchall()
        return [Segment.model_validate(dict(row)) for row in rows]

    def _mark_failed(self, recording_id: str, code: str, message: str) -> None:
        try:
            transition_recording(
                self.settings.database_path,
                recording_id,
                RecordingStatus.FAILED,
                code,
                message,
            )
        except (KeyError, ValueError):
            self.logger.exception(
                "recording_failure_state_error",
                extra={"recording_id": recording_id, "error_code": code},
            )


def _json_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def _timestamp(milliseconds: int) -> str:
    seconds = milliseconds // 1000
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def _summary_markdown(summary: MeetingSummary) -> str:
    lines = [
        "# 요약",
        "",
        "## 목적",
        summary.purpose,
        "",
        "## 논의 내용",
        *[f"- {item}" for item in summary.discussion],
        "",
        "## 결정 사항",
        *[f"- {item}" for item in summary.decisions],
        "",
        "## 할 일",
        *[f"- {item.task}" for item in summary.action_items],
        "",
        "## 미해결 사항",
        *([f"- {item}" for item in summary.open_questions] or ["- 없음"]),
        "",
    ]
    return "\n".join(lines)
