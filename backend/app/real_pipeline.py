from __future__ import annotations

import logging
import math
import stat
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from app.alignment import (
    AlignedSegment,
    AlignmentConfig,
    AlignmentResult,
    WhisperXAlignmentAdapter,
    WhisperXAlignmentError,
)
from app.classification import ClassificationAdapter
from app.config import Settings
from app.diarization import (
    DiarizationConfig,
    DiarizationResult,
    WhisperXDiarizationAdapter,
    WhisperXDiarizationError,
)
from app.jobs import Job
from app.media import AudioNormalizationError, normalized_audio
from app.pipeline import FakePipelineHandler
from app.retranscriptions import commit_retranscription, request_for_job
from app.runtime import PermanentJobError, RetryableJobError
from app.schema import RecordingStatus, Segment, SpeechModelFingerprints, Transcript
from app.speaker_embeddings import PyannoteSpeakerEmbeddingAdapter, SpeakerEmbeddingAdapter
from app.speech_failures import speech_failure_policy
from app.state import transition_recording
from app.transcription import (
    TranscriptionResult,
    TranscriptionSegment,
    WhisperXAdapter,
    WhisperXAdapterError,
    WhisperXConfig,
)


class TranscriptionAdapter(Protocol):
    def transcribe(
        self,
        normalized_wav: Path,
        *,
        language: str | None = None,
        initial_prompt: str | None = None,
    ) -> TranscriptionResult: ...


class AlignmentAdapter(Protocol):
    def align(
        self,
        normalized_wav: Path,
        segments: Sequence[TranscriptionSegment],
        language: str,
        *,
        audio_duration: float,
    ) -> AlignmentResult: ...


class DiarizationAdapter(Protocol):
    def diarize(
        self,
        normalized_wav: Path,
        segments: Sequence[AlignedSegment],
        *,
        audio_duration: float,
    ) -> DiarizationResult: ...


class RealSpeechInputError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class RealSpeechPipelineHandler(FakePipelineHandler):
    def __init__(
        self,
        settings: Settings,
        logger: logging.Logger,
        *,
        transcription_adapter: TranscriptionAdapter | None = None,
        alignment_adapter: AlignmentAdapter | None = None,
        diarization_adapter: DiarizationAdapter | None = None,
        speaker_embedding_adapter: SpeakerEmbeddingAdapter | None = None,
        classification_adapter: ClassificationAdapter | None = None,
        continue_to_documents: bool = True,
    ) -> None:
        # Fake document adapters remain available after R5 speaker review is implemented.
        super().__init__(settings, logger, classification_adapter=classification_adapter)
        self.speaker_embedding_adapter = (
            speaker_embedding_adapter
            or PyannoteSpeakerEmbeddingAdapter(
                model=settings.speaker_embedding_model,
                revision=settings.speaker_embedding_revision,
                device=settings.speaker_embedding_device,
                model_cache_root=settings.model_cache_root,
                hf_token=settings.hf_token,
            )
        )
        self.transcription_adapter = transcription_adapter or WhisperXAdapter(
            WhisperXConfig(
                model=settings.whisper_model,
                device=settings.whisper_device,
                compute_type=settings.whisper_compute_type,
                language=settings.whisper_language,
                batch_size=settings.whisper_batch_size,
                model_cache_root=settings.model_cache_root,
            ),
            hf_token=settings.hf_token,
        )
        self.alignment_adapter = alignment_adapter or WhisperXAlignmentAdapter(
            AlignmentConfig(
                device=settings.whisper_device,
                model_cache_root=settings.model_cache_root,
            )
        )
        self.diarization_adapter = diarization_adapter or WhisperXDiarizationAdapter(
            DiarizationConfig(
                device=settings.whisper_device,
                model_cache_root=settings.model_cache_root,
            ),
            hf_token=settings.hf_token,
        )
        self.continue_to_documents = continue_to_documents

    def __call__(self, job: Job) -> None:
        if job.kind != "transcribe":
            super().__call__(job)
            return
        try:
            self._transcribe_real(job)
        except AudioNormalizationError as error:
            self._fail_with_policy(job, str(error.code), cause=error)
        except (WhisperXAdapterError, WhisperXAlignmentError, WhisperXDiarizationError) as error:
            self._fail_with_policy(job, str(error.code), cause=error)
        except RealSpeechInputError as error:
            self._fail_with_policy(job, error.code, cause=error)
        except ValueError as error:
            self._fail_with_policy(job, "INVALID_SPEECH_RESULT", cause=error)
        except OSError as error:
            self._fail_with_policy(job, "ARTIFACT_IO_ERROR", cause=error)
        except (PermanentJobError, RetryableJobError):
            raise
        except Exception:
            if request_for_job(self.settings.database_path, job.id) is None:
                self._mark_failed(job.recording_id, "PIPELINE_ERROR", "처리 단계가 실패했습니다.")
            raise

    def _transcribe_real(self, job: Job) -> None:
        recording = self._recording(job.recording_id)
        retranscription = request_for_job(self.settings.database_path, job.id)
        if retranscription is None:
            self._enter(job.recording_id, RecordingStatus.TRANSCRIBING)
        source = self._validated_source(str(recording["source_path"]))
        duration_ms = int(recording["duration_ms"])
        audio_duration = duration_ms / 1000
        with normalized_audio(source) as normalized_wav:
            if retranscription is None:
                transcription = self.transcription_adapter.transcribe(normalized_wav)
            else:
                transcription = self.transcription_adapter.transcribe(
                    normalized_wav,
                    language=retranscription.language,
                    initial_prompt=retranscription.initial_prompt,
                )
            alignment = self.alignment_adapter.align(
                normalized_wav,
                transcription.segments,
                transcription.language,
                audio_duration=audio_duration,
            )
            diarization = self.diarization_adapter.diarize(
                normalized_wav,
                alignment.segments,
                audio_duration=audio_duration,
            )
        transcript = normalize_real_transcript(
            recording_id=job.recording_id,
            content_sha256=str(recording["content_sha256"]),
            revision=(
                int(recording["revision"])
                if retranscription is None
                else retranscription.target_revision
            ),
            duration_ms=duration_ms,
            transcription=transcription,
            alignment=alignment,
            diarization=diarization,
        )
        if retranscription is not None:
            commit_retranscription(self.settings, job.id, transcript)
            self._generate_speaker_clips(job.recording_id, source, transcript.revision)
            return
        self._replace_segments(transcript)
        self._write_transcript_json(transcript)
        self._generate_speaker_clips(job.recording_id, source, transcript.revision)
        self._set_review_required(job.recording_id)
        if self.continue_to_documents:
            self._enqueue_speaker_finalization(transcript)
        else:
            transition_recording(
                self.settings.database_path,
                job.recording_id,
                RecordingStatus.SPEAKER_REVIEW,
            )
            self._enqueue_speaker_finalization(transcript)

    def _validated_source(self, value: str) -> Path:
        try:
            source = Path(value).resolve(strict=True)
            input_root = self.settings.recording_input_dir.resolve(strict=True)
        except FileNotFoundError as error:
            raise RealSpeechInputError("INPUT_NOT_AVAILABLE") from error
        except OSError as error:
            raise RealSpeechInputError("INPUT_IO_ERROR") from error
        if not source.is_relative_to(input_root):
            raise RealSpeechInputError("INPUT_NOT_AVAILABLE")
        try:
            if not stat.S_ISREG(source.stat().st_mode):
                raise RealSpeechInputError("INPUT_NOT_AVAILABLE")
        except FileNotFoundError as error:
            raise RealSpeechInputError("INPUT_NOT_AVAILABLE") from error
        except OSError as error:
            raise RealSpeechInputError("INPUT_IO_ERROR") from error
        return source

    def _fail_with_policy(
        self,
        job: Job,
        code: str,
        *,
        cause: Exception | None = None,
    ) -> None:
        policy = speech_failure_policy(code)
        if request_for_job(self.settings.database_path, job.id) is None:
            self._mark_failed(job.recording_id, code, policy.message)
        error_type = RetryableJobError if policy.retryable else PermanentJobError
        error = error_type(code, policy.message)
        if cause is not None:
            raise error from cause
        raise error


def normalize_real_transcript(
    *,
    recording_id: str,
    content_sha256: str,
    revision: int,
    duration_ms: int,
    transcription: TranscriptionResult,
    alignment: AlignmentResult,
    diarization: DiarizationResult,
) -> Transcript:
    if duration_ms <= 0:
        raise ValueError("recording duration must be positive")
    if alignment.language != transcription.language.strip().lower():
        raise ValueError("transcription and alignment languages do not match")
    assignments = {item.segment_index: item for item in diarization.assignments}
    expected_indexes = set(range(len(alignment.segments)))
    if set(assignments) != expected_indexes or len(diarization.assignments) != len(assignments):
        raise ValueError("diarization assignments do not match aligned segments")

    namespace = uuid.UUID(recording_id)
    segments: list[Segment] = []
    for index, aligned in enumerate(alignment.segments):
        if not math.isfinite(aligned.start) or not math.isfinite(aligned.end):
            raise ValueError("aligned segment time is not finite")
        text = aligned.text.strip()
        start_ms = min(max(round(aligned.start * 1000), 0), duration_ms)
        end_ms = min(max(round(aligned.end * 1000), start_ms), duration_ms)
        if not text or end_ms <= start_ms:
            continue
        assignment = assignments[index]
        segments.append(
            Segment(
                id=uuid.uuid5(namespace, f"segment:{index}"),
                start_ms=start_ms,
                end_ms=end_ms,
                local_speaker_id=assignment.local_speaker_id,
                assignment_status=assignment.status.value,
                overlapping_speaker_ids=list(assignment.overlapping_speaker_ids),
                text=text,
            )
        )
    segments.sort(key=lambda segment: (segment.start_ms, segment.end_ms, str(segment.id)))
    if not segments:
        raise ValueError("speech result has no usable segments")

    return Transcript(
        recording_id=namespace,
        content_sha256=content_sha256,
        revision=revision,
        language=alignment.language,
        needs_speaker_review=True,
        segments=segments,
        model_fingerprints=SpeechModelFingerprints(
            transcription=transcription.model_fingerprint.as_dict(),
            alignment=alignment.model_fingerprint.as_dict(),
            diarization=diarization.model_fingerprint.as_dict(),
        ),
    )
