from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal, cast

from app.adapters import FakeAdapters, FakeFixtureNotFoundError
from app.artifacts import safe_category_slug, write_artifact, write_summary_artifacts
from app.classification import (
    ClassificationAdapter,
    ClassificationError,
    ClassificationTimeoutError,
    FakeClassificationAdapter,
    RetryableClassificationError,
)
from app.config import Settings
from app.db import connect, utc_now
from app.document_identity import document_relative_path, ensure_document_identity
from app.jobs import Job
from app.long_transcript import (
    LongTranscriptClassifier,
    SegmentSlice,
    TopicEvidence,
    TranscriptIdentity,
)
from app.renderer import (
    MARKDOWN_SCHEMA_VERSION,
    render_transcript_json,
    render_transcript_markdown,
    transcript_artifact_paths,
    with_classification,
)
from app.retranscriptions import commit_retranscription, request_for_job
from app.runtime import PermanentJobError, RetryableJobError
from app.schema import Classification, RecordingStatus, Segment, Transcript
from app.speaker_clips import generate_speaker_clips
from app.speaker_embeddings import (
    FakeSpeakerEmbeddingAdapter,
    SpeakerEmbeddingAdapter,
    SpeakerEmbeddingError,
    finalize_speaker_embeddings,
)
from app.state import enqueue_job, transition_and_enqueue, transition_recording
from app.summary import (
    RetryableSummaryError,
    SummaryAdapter,
    SummaryError,
    SummaryTimeoutError,
    summary_settings_fingerprint,
)
from app.summary_renderer import render_summary_markdown


class TranscriptRendererError(RuntimeError):
    pass


class _FakeTopicBackend:
    def __init__(self, classification_adapter: FakeClassificationAdapter) -> None:
        self.classification_adapter = classification_adapter

    @property
    def fingerprint(self) -> dict[str, object]:
        return {"model": "fake-segment-topic-v1", "final": self.classification_adapter.fingerprint}

    def extract(self, segments: tuple[SegmentSlice, ...]) -> str:
        payload = "\n".join(
            f"{item.segment_id}:{item.start_ms}:{item.end_ms}:{item.local_speaker_id}:"
            f"{item.part_index}:{item.text}"
            for item in segments
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    def classify_topics(
        self,
        identity: TranscriptIdentity,
        topics: tuple[TopicEvidence, ...],
        allowed_categories: tuple[str, ...],
    ) -> Classification:
        if not topics:
            raise ValueError("topic evidence must not be empty")
        return self.classification_adapter.classify_content_hash(
            identity.content_sha256, allowed_categories
        )


class FakePipelineHandler:
    def __init__(
        self,
        settings: Settings,
        logger: logging.Logger,
        adapters: FakeAdapters | None = None,
        classification_adapter: ClassificationAdapter | None = None,
        summary_adapter: SummaryAdapter | None = None,
        speaker_embedding_adapter: SpeakerEmbeddingAdapter | None = None,
        markdown_renderer: Callable[[Transcript], bytes] = render_transcript_markdown,
    ) -> None:
        self.settings = settings
        self.logger = logger
        self.adapters = adapters or FakeAdapters()
        if classification_adapter is None:
            direct_adapter = FakeClassificationAdapter(self._fake_classification_response)
            topic_backend = _FakeTopicBackend(direct_adapter)
            classification_adapter = LongTranscriptClassifier(
                direct_adapter,
                topic_backend,
                topic_backend,
                max_context_chars=settings.classification_context_max_chars,
            )
        self.classification_adapter = classification_adapter
        self.summary_adapter = summary_adapter or self.adapters
        self.speaker_embedding_adapter = speaker_embedding_adapter or FakeSpeakerEmbeddingAdapter()
        self.markdown_renderer = markdown_renderer

    def _fake_classification_response(self, content_sha256: str) -> object:
        try:
            return self.adapters.classification_response(content_sha256)
        except FakeFixtureNotFoundError:
            return {
                "schema_version": 1,
                "category": self.settings.categories[-1],
                "confidence": 0.0,
                "reason": "local deterministic fallback",
            }

    def __call__(self, job: Job) -> None:
        if job.kind == "finalize_speakers":
            try:
                result = finalize_speaker_embeddings(
                    self.settings,
                    job.recording_id,
                    self.speaker_embedding_adapter,
                    job.input_revision,
                )
            except SpeakerEmbeddingError as error:
                if error.code in {
                    "SPEAKER_EMBEDDING_SOURCE_CHANGED",
                    "SPEAKER_CLIP_NOT_AVAILABLE",
                    "SPEAKER_EMBEDDING_MODEL_LOAD_FAILED",
                    "MODEL_DOWNLOAD_FAILED",
                    "SPEAKER_EMBEDDING_FAILED",
                }:
                    raise RetryableJobError(error.code, str(error)) from error
                raise PermanentJobError(error.code, str(error)) from error
            if not result.stale:
                self._continue_after_speaker_finalization(job.recording_id, result.revision)
            return
        if job.kind == "render":
            try:
                self._render(job)
            except TranscriptRendererError as error:
                raise PermanentJobError(
                    "TRANSCRIPT_RENDER_ERROR", "transcript rerender failed"
                ) from error
            except OSError as error:
                raise RetryableJobError(
                    "ARTIFACT_IO_ERROR", "rerender artifact write failed"
                ) from error
            except ValueError as error:
                raise PermanentJobError("INVALID_RENDER_SOURCE", str(error)) from error
            return
        if (
            job.kind == "transcribe"
            and request_for_job(self.settings.database_path, job.id) is not None
        ):
            try:
                self._transcribe(job)
            except OSError as error:
                raise RetryableJobError(
                    "ARTIFACT_IO_ERROR", "retranscription staging failed"
                ) from error
            except (FakeFixtureNotFoundError, ValueError) as error:
                raise PermanentJobError(
                    "INVALID_RETRANSCRIPTION_RESULT", "retranscription result is invalid"
                ) from error
            return
        try:
            if job.kind == "transcribe":
                self._transcribe(job)
            elif job.kind == "classify":
                self._classify(job)
            elif job.kind == "summarize":
                self._summarize(job)
            else:
                raise PermanentJobError("UNSUPPORTED_JOB_KIND", f"unsupported job: {job.kind}")
        except ClassificationTimeoutError as error:
            self._mark_failed(job.recording_id, error.code, "분류 응답 시간이 초과되었습니다.")
            raise RetryableJobError(error.code, "classification timed out") from error
        except RetryableClassificationError as error:
            self._mark_failed(
                job.recording_id, error.code, "분류 공급자에 일시적으로 연결할 수 없습니다."
            )
            raise RetryableJobError(error.code, "classification provider unavailable") from error
        except ClassificationError as error:
            self._mark_failed(job.recording_id, error.code, "분류 결과가 유효하지 않습니다.")
            raise PermanentJobError(error.code, "classification result is invalid") from error
        except SummaryTimeoutError as error:
            self._mark_failed(job.recording_id, error.code, "요약 응답 시간이 초과되었습니다.")
            raise RetryableJobError(error.code, "summary timed out") from error
        except RetryableSummaryError as error:
            self._mark_failed(
                job.recording_id, error.code, "요약 공급자에 일시적으로 연결할 수 없습니다."
            )
            raise RetryableJobError(error.code, "summary provider unavailable") from error
        except SummaryError as error:
            self._mark_failed(job.recording_id, error.code, "요약 결과가 유효하지 않습니다.")
            raise PermanentJobError(error.code, "summary result is invalid") from error
        except TranscriptRendererError as error:
            self._mark_failed(
                job.recording_id,
                "TRANSCRIPT_RENDER_ERROR",
                "Markdown 결과를 생성할 수 없습니다.",
            )
            raise PermanentJobError(
                "TRANSCRIPT_RENDER_ERROR", "transcript markdown render failed"
            ) from error
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
        retranscription = request_for_job(self.settings.database_path, job.id)
        if retranscription is not None:
            transcript = self.adapters.transcribe(
                job.recording_id,
                str(recording["content_sha256"]),
                retranscription.target_revision,
                language=retranscription.language,
                initial_prompt=retranscription.initial_prompt,
            )
            commit_retranscription(self.settings, job.id, transcript)
            self._generate_speaker_clips(
                job.recording_id,
                Path(str(recording["source_path"])),
                transcript.revision,
            )
            return
        self._enter(job.recording_id, RecordingStatus.TRANSCRIBING)
        transcript = self.adapters.transcribe(
            job.recording_id,
            str(recording["content_sha256"]),
            int(recording["revision"]),
        )
        self._replace_segments(transcript)
        self._write_transcript_json(transcript)
        self._generate_speaker_clips(
            job.recording_id,
            Path(str(recording["source_path"])),
            transcript.revision,
        )
        if transcript.needs_speaker_review:
            self._set_review_required(job.recording_id)
        self._enqueue_speaker_finalization(transcript)

    def _classify(self, job: Job) -> None:
        recording = self._recording(job.recording_id)
        self._enter(job.recording_id, RecordingStatus.CLASSIFYING)
        transcript = self._load_transcript(job.recording_id, int(recording["revision"]))
        classification = self.classification_adapter.classify(transcript, self.settings.categories)
        applied, source = self._save_classification(job.recording_id, classification)
        classified = with_classification(
            transcript,
            applied,
            self.classification_adapter.fingerprint,
            source,
        )
        self._write_classified_transcript_artifacts(classified)
        if applied.category in self.settings.auto_summary_categories:
            transition_and_enqueue(
                self.settings.database_path,
                job.recording_id,
                RecordingStatus.SUMMARIZING,
                "summarize",
                transcript.revision,
                summary_settings_fingerprint(self.summary_adapter, applied.category),
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
        category = str(recording["category"])
        revision = int(recording["revision"])
        if (
            revision != job.input_revision
            or job.settings_fingerprint
            != summary_settings_fingerprint(self.summary_adapter, category)
        ):
            return
        transcript = self._load_transcript(job.recording_id, revision)
        summary = self.summary_adapter.summarize(transcript, category)
        slug = safe_category_slug(category)
        metadata = {
            "schema_version": 1,
            "recording_id": job.recording_id,
            "content_sha256": str(recording["content_sha256"]),
            "revision": revision,
            "created_at": utc_now(),
            "category": category,
            "category_slug": slug,
            "summary_fingerprint": self.summary_adapter.fingerprint,
            "summary": summary.model_dump(mode="json"),
        }
        write_summary_artifacts(
            self.settings.database_path,
            self.settings.summary_root,
            job.recording_id,
            revision,
            slug,
            _json_bytes(metadata),
            render_summary_markdown(summary, category),
        )
        if RecordingStatus(str(recording["status"])) is not RecordingStatus.COMPLETED:
            transition_recording(
                self.settings.database_path,
                job.recording_id,
                RecordingStatus.COMPLETED,
            )

    def _render(self, job: Job) -> None:
        recording = self._recording(job.recording_id)
        revision = int(recording["revision"])
        if revision != job.input_revision:
            raise ValueError("render job revision is stale")
        with connect(self.settings.database_path) as connection:
            previous = connection.execute(
                """
                SELECT relative_path FROM artifacts
                WHERE recording_id = ? AND kind = 'transcript_json' AND revision < ?
                ORDER BY revision DESC LIMIT 1
                """,
                (job.recording_id, revision),
            ).fetchone()
            had_summary = (
                connection.execute(
                    """
                    SELECT 1 FROM artifacts
                    WHERE recording_id = ? AND kind = 'summary_json' AND revision < ?
                    LIMIT 1
                    """,
                    (job.recording_id, revision),
                ).fetchone()
                is not None
            )
        if previous is None:
            raise ValueError("previous transcript artifact is missing")
        root = self.settings.transcript_root.resolve()
        previous_path = (root / str(previous["relative_path"])).resolve()
        if not previous_path.is_relative_to(root):
            raise ValueError("transcript artifact path leaves configured root")
        stored = Transcript.model_validate_json(previous_path.read_bytes())
        transcript = stored.model_copy(
            update={"revision": revision, "segments": self._segments(job.recording_id)},
            deep=True,
        )
        source = cast(Literal["auto", "manual"], str(recording["category_source"]))
        transcript = with_classification(
            transcript,
            Classification(
                schema_version=1,
                category=str(recording["category"]),
                confidence=(
                    None if source == "manual" else float(recording["category_confidence"])
                ),
                reason=(
                    "사용자가 수동으로 선택한 범주입니다."
                    if source == "manual"
                    else str(recording["category_reason"])
                ),
            ),
            stored.classification_fingerprint,
            source,
        )
        try:
            json_content = render_transcript_json(transcript)
            markdown_content = self.markdown_renderer(transcript)
        except Exception as error:
            raise TranscriptRendererError from error

        json_relative = Path(job.recording_id) / "revisions" / str(revision) / "transcript.json"
        write_artifact(
            self.settings.database_path,
            self.settings.transcript_root,
            job.recording_id,
            "transcript_json",
            json_relative,
            json_content,
            revision,
            schema_version=transcript.schema_version,
        )
        identity = ensure_document_identity(self.settings.database_path, job.recording_id)
        write_artifact(
            self.settings.database_path,
            self.settings.document_root,
            job.recording_id,
            "transcript_markdown",
            document_relative_path(identity.sequence, identity.title),
            markdown_content,
            revision,
            schema_version=MARKDOWN_SCHEMA_VERSION,
        )
        if had_summary:
            enqueue_job(
                self.settings.database_path,
                job.recording_id,
                "summarize",
                revision,
                summary_settings_fingerprint(self.summary_adapter, str(recording["category"])),
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
            timestamp = utc_now()
            speaker_ids = {
                speaker_id
                for segment in transcript.segments
                for speaker_id in (
                    ([segment.local_speaker_id] if segment.local_speaker_id is not None else [])
                    + segment.overlapping_speaker_ids
                )
            }
            connection.executemany(
                """
                INSERT INTO recording_speakers(
                    recording_id, local_speaker_id, speaker_source, revision,
                    created_at, updated_at
                ) VALUES (?, ?, 'unresolved', 1, ?, ?)
                ON CONFLICT(recording_id, local_speaker_id) DO NOTHING
                """,
                [
                    (str(transcript.recording_id), speaker_id, timestamp, timestamp)
                    for speaker_id in sorted(speaker_ids)
                ],
            )
            connection.execute(
                "DELETE FROM segments WHERE recording_id = ?", (str(transcript.recording_id),)
            )
            connection.executemany(
                """
                INSERT INTO segments(
                    id, recording_id, start_ms, end_ms, text, local_speaker_id,
                    assignment_status, overlapping_speaker_ids_json,
                    person_id, speaker_name, revision
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        str(segment.id),
                        str(transcript.recording_id),
                        segment.start_ms,
                        segment.end_ms,
                        segment.text,
                        segment.local_speaker_id,
                        segment.assignment_status,
                        json.dumps(segment.overlapping_speaker_ids, sort_keys=True),
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
        paths = transcript_artifact_paths(recording_id)
        write_artifact(
            self.settings.database_path,
            self.settings.transcript_root,
            recording_id,
            "transcript_json",
            paths.json,
            _json_bytes(transcript.model_dump(mode="json")),
            transcript.revision,
            schema_version=transcript.schema_version,
        )

    def _set_review_required(self, recording_id: str) -> None:
        with connect(self.settings.database_path) as connection:
            connection.execute(
                "UPDATE recordings SET needs_speaker_review = 1 WHERE id = ?", (recording_id,)
            )

    def _generate_speaker_clips(self, recording_id: str, source: Path, revision: int) -> None:
        try:
            generate_speaker_clips(
                self.settings.database_path,
                self.settings.speaker_root,
                recording_id,
                source,
                revision,
            )
        except Exception:
            self.logger.exception(
                "speaker_clip_generation_failed",
                extra={
                    "recording_id": recording_id,
                    "error_code": "SPEAKER_CLIP_GENERATION_FAILED",
                },
            )

    def _enqueue_classification(self, transcript: Transcript) -> None:
        self._enqueue_classification_revision(str(transcript.recording_id), transcript.revision)

    def _enqueue_classification_revision(self, recording_id: str, revision: int) -> None:
        fingerprint = hashlib.sha256(
            json.dumps(
                self.classification_adapter.fingerprint,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        transition_and_enqueue(
            self.settings.database_path,
            recording_id,
            RecordingStatus.CLASSIFYING,
            "classify",
            revision,
            fingerprint,
        )

    def _enqueue_speaker_finalization(self, transcript: Transcript) -> None:
        enqueue_job(
            self.settings.database_path,
            str(transcript.recording_id),
            "finalize_speakers",
            transcript.revision,
            self.settings.speaker_finalization_settings_fingerprint,
        )

    def _continue_after_speaker_finalization(self, recording_id: str, revision: int) -> None:
        with connect(self.settings.database_path) as connection:
            row = connection.execute(
                "SELECT status FROM recordings WHERE id = ?", (recording_id,)
            ).fetchone()
        if row is not None and str(row["status"]) == RecordingStatus.TRANSCRIBING.value:
            self._enqueue_classification_revision(recording_id, revision)

    def _save_classification(
        self, recording_id: str, classification: Classification
    ) -> tuple[Classification, Literal["auto", "manual"]]:
        with connect(self.settings.database_path) as connection:
            connection.execute(
                """
                UPDATE recordings
                SET automatic_category = ?,
                    category = CASE WHEN category_source = 'manual' THEN category ELSE ? END,
                    category_source = CASE
                        WHEN category_source = 'manual' THEN 'manual' ELSE 'auto'
                    END,
                    category_confidence = ?, category_reason = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    classification.category,
                    classification.category,
                    classification.confidence,
                    classification.reason,
                    utc_now(),
                    recording_id,
                ),
            )
            row = connection.execute(
                "SELECT category, category_source FROM recordings WHERE id = ?",
                (recording_id,),
            ).fetchone()
        if row is None:
            raise ValueError("recording is missing")
        source = cast(Literal["auto", "manual"], str(row["category_source"]))
        if source == "manual":
            return (
                Classification(
                    schema_version=1,
                    category=str(row["category"]),
                    confidence=None,
                    reason="사용자가 수동으로 선택한 범주입니다.",
                ),
                source,
            )
        return classification, source

    def _load_transcript(self, recording_id: str, revision: int) -> Transcript:
        with connect(self.settings.database_path) as connection:
            artifact = connection.execute(
                """
                SELECT relative_path FROM artifacts
                WHERE recording_id = ? AND kind = 'transcript_json' AND revision = ?
                """,
                (recording_id, revision),
            ).fetchone()
        if artifact is None:
            raise ValueError("transcript JSON artifact is missing")
        root = self.settings.transcript_root.resolve()
        path = (root / str(artifact["relative_path"])).resolve()
        if not path.is_relative_to(root):
            raise ValueError("transcript artifact path leaves configured root")
        transcript = Transcript.model_validate_json(path.read_bytes())
        if str(transcript.recording_id) != recording_id or transcript.revision != revision:
            raise ValueError("transcript artifact identity does not match job")
        return transcript

    def _write_classified_transcript_artifacts(self, transcript: Transcript) -> None:
        recording_id = str(transcript.recording_id)
        paths = transcript_artifact_paths(recording_id)
        write_artifact(
            self.settings.database_path,
            self.settings.transcript_root,
            recording_id,
            "transcript_json",
            paths.json,
            render_transcript_json(transcript),
            transcript.revision,
            schema_version=transcript.schema_version,
        )
        identity = ensure_document_identity(self.settings.database_path, recording_id)
        try:
            markdown = self.markdown_renderer(transcript)
        except Exception as error:
            raise TranscriptRendererError from error
        write_artifact(
            self.settings.database_path,
            self.settings.document_root,
            recording_id,
            "transcript_markdown",
            document_relative_path(identity.sequence, identity.title),
            markdown,
            transcript.revision,
            schema_version=MARKDOWN_SCHEMA_VERSION,
        )

    def _segments(self, recording_id: str) -> list[Segment]:
        with connect(self.settings.database_path) as connection:
            rows = connection.execute(
                """
                SELECT segments.id, segments.start_ms, segments.end_ms,
                       segments.local_speaker_id, segments.assignment_status,
                       segments.overlapping_speaker_ids_json, segments.person_id,
                       COALESCE(persons.display_name, segments.speaker_name) AS speaker_name,
                       segments.text
                FROM segments
                LEFT JOIN persons ON persons.id = segments.person_id
                WHERE segments.recording_id = ?
                ORDER BY segments.start_ms, segments.end_ms, segments.id
                """,
                (recording_id,),
            ).fetchall()
        segments: list[Segment] = []
        for row in rows:
            value = dict(row)
            value["overlapping_speaker_ids"] = json.loads(value.pop("overlapping_speaker_ids_json"))
            segments.append(Segment.model_validate(value))
        return segments

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
