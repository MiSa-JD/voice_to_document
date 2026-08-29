from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any

import pytest
from app.alignment import AlignedSegment, AlignmentFingerprint, AlignmentResult
from app.config import Settings
from app.db import connect
from app.diarization import (
    AssignmentStatus,
    DiarizationFingerprint,
    DiarizationResult,
    DiarizationTurn,
    SegmentSpeakerAssignment,
)
from app.ingest import ingest_file
from app.real_pipeline import RealSpeechPipelineHandler, normalize_real_transcript
from app.runtime import process_one_job
from app.transcription import (
    ModelFingerprint,
    TranscriptionResult,
    TranscriptionSegment,
    WhisperXAdapterError,
    WhisperXErrorCode,
)

FIXTURE = Path(__file__).parents[1] / "fixtures" / "complete.m4a"


def _transcription() -> TranscriptionResult:
    return TranscriptionResult(
        language="ko",
        segments=(
            TranscriptionSegment(1.0, 1.8, "두 번째"),
            TranscriptionSegment(0.0, 0.8, "첫 번째"),
            TranscriptionSegment(1.8, 2.0, "미배정"),
        ),
        model_fingerprint=ModelFingerprint(
            whisperx_version="3.8.6",
            model="large-v3",
            device="cuda",
            compute_type="float16",
            batch_size=4,
            language=None,
        ),
    )


def _alignment() -> AlignmentResult:
    return AlignmentResult(
        language="ko",
        segments=(
            AlignedSegment(1.0, 1.8, " 두 번째 "),
            AlignedSegment(0.0, 0.8, "첫 번째"),
            AlignedSegment(1.8, 2.0, "미배정"),
        ),
        word_segments=(),
        model_fingerprint=AlignmentFingerprint(
            whisperx_version="3.8.6",
            device="cuda",
            interpolate_method="nearest",
            language="ko",
        ),
    )


def _diarization() -> DiarizationResult:
    return DiarizationResult(
        turns=(
            DiarizationTurn(0.0, 0.8, "SPEAKER_00"),
            DiarizationTurn(1.0, 1.8, "SPEAKER_00"),
            DiarizationTurn(1.2, 1.5, "SPEAKER_01"),
        ),
        assignments=(
            SegmentSpeakerAssignment(
                0,
                "SPEAKER_00",
                AssignmentStatus.OVERLAP,
                ("SPEAKER_00", "SPEAKER_01"),
            ),
            SegmentSpeakerAssignment(1, "SPEAKER_00", AssignmentStatus.ASSIGNED),
            SegmentSpeakerAssignment(2, None, AssignmentStatus.UNASSIGNED),
        ),
        speaker_ids=("SPEAKER_00", "SPEAKER_01"),
        model_fingerprint=DiarizationFingerprint(
            whisperx_version="3.8.6",
            pyannote_audio_version="4.0.7",
            model="pyannote/speaker-diarization-community-1",
            device="cuda",
        ),
    )


def test_real_results_normalize_to_ordered_transcript_v2() -> None:
    recording_id = "26f9afe3-8b2b-4a49-98c4-5c5b51a97355"

    transcript = normalize_real_transcript(
        recording_id=recording_id,
        content_sha256="a" * 64,
        revision=2,
        duration_ms=2000,
        transcription=_transcription(),
        alignment=_alignment(),
        diarization=_diarization(),
    )

    assert transcript.schema_version == 2
    assert [segment.text for segment in transcript.segments] == ["첫 번째", "두 번째", "미배정"]
    assert [segment.assignment_status for segment in transcript.segments] == [
        "assigned",
        "overlap",
        "unassigned",
    ]
    assert transcript.segments[-1].local_speaker_id is None
    assert transcript.model_fingerprints is not None
    assert transcript.model_fingerprints.transcription["model"] == "large-v3"


def test_real_result_segment_ids_are_stable() -> None:
    first = normalize_real_transcript(
        recording_id="26f9afe3-8b2b-4a49-98c4-5c5b51a97355",
        content_sha256="a" * 64,
        revision=1,
        duration_ms=2000,
        transcription=_transcription(),
        alignment=_alignment(),
        diarization=_diarization(),
    )
    second = normalize_real_transcript(
        recording_id="26f9afe3-8b2b-4a49-98c4-5c5b51a97355",
        content_sha256="a" * 64,
        revision=1,
        duration_ms=2000,
        transcription=_transcription(),
        alignment=_alignment(),
        diarization=_diarization(),
    )

    assert [segment.id for segment in first.segments] == [segment.id for segment in second.segments]


def test_real_result_rejects_missing_assignments() -> None:
    diarization = _diarization()
    invalid = DiarizationResult(
        turns=diarization.turns,
        assignments=diarization.assignments[:-1],
        speaker_ids=diarization.speaker_ids,
        model_fingerprint=diarization.model_fingerprint,
    )

    with pytest.raises(ValueError, match="assignments"):
        normalize_real_transcript(
            recording_id="26f9afe3-8b2b-4a49-98c4-5c5b51a97355",
            content_sha256="a" * 64,
            revision=1,
            duration_ms=2000,
            transcription=_transcription(),
            alignment=_alignment(),
            diarization=invalid,
        )


class StubTranscriptionAdapter:
    def __init__(self, error: WhisperXAdapterError | None = None) -> None:
        self.error = error
        self.path: Path | None = None

    def transcribe(self, normalized_wav: Path) -> TranscriptionResult:
        self.path = normalized_wav
        assert normalized_wav.is_file()
        if self.error is not None:
            raise self.error
        return _transcription()


class StubAlignmentAdapter:
    def align(
        self,
        normalized_wav: Path,
        segments: object,
        language: str,
        *,
        audio_duration: float,
    ) -> AlignmentResult:
        assert normalized_wav.is_file()
        assert segments == _transcription().segments
        assert language == "ko"
        assert audio_duration == 2
        return _alignment()


class StubDiarizationAdapter:
    def diarize(
        self,
        normalized_wav: Path,
        segments: object,
        *,
        audio_duration: float,
    ) -> DiarizationResult:
        assert normalized_wav.is_file()
        assert segments == _alignment().segments
        assert audio_duration == 2
        return _diarization()


def _real_settings(settings_values: dict[str, Any]) -> Settings:
    values = {**settings_values, "SPEECH_MODE": "real", "HF_TOKEN": "test-token"}
    return Settings(**values)


def test_real_handler_persists_classified_json_and_markdown_artifacts(
    settings_values: dict[str, Any],
) -> None:
    settings = _real_settings(settings_values)
    source = settings.recording_input_dir / "complete.m4a"
    shutil.copyfile(FIXTURE, source)
    original = source.read_bytes()
    registration = ingest_file(settings.database_path, source)
    transcription = StubTranscriptionAdapter()
    handler = RealSpeechPipelineHandler(
        settings,
        logging.getLogger("test"),
        transcription_adapter=transcription,
        alignment_adapter=StubAlignmentAdapter(),
        diarization_adapter=StubDiarizationAdapter(),
    )

    while process_one_job(settings.database_path, handler, logging.getLogger("test")):
        pass

    with connect(settings.database_path) as connection:
        recording = connection.execute(
            "SELECT status, needs_speaker_review FROM recordings"
        ).fetchone()
        segments = connection.execute(
            """
            SELECT assignment_status, local_speaker_id, overlapping_speaker_ids_json
            FROM segments ORDER BY start_ms
            """
        ).fetchall()
        recording_speakers = connection.execute(
            """
            SELECT local_speaker_id, person_id, speaker_source, speaker_score, revision
            FROM recording_speakers ORDER BY local_speaker_id
            """
        ).fetchall()
        artifacts = connection.execute(
            "SELECT kind, relative_path, schema_version, revision FROM artifacts ORDER BY kind"
        ).fetchall()
        jobs = connection.execute("SELECT kind, status FROM jobs ORDER BY created_at").fetchall()
    json_artifact = next(row for row in artifacts if row["kind"] == "transcript_json")
    markdown_artifact = next(row for row in artifacts if row["kind"] == "transcript_markdown")
    payload = json.loads((settings.transcript_root / json_artifact["relative_path"]).read_text())
    markdown = (settings.document_root / markdown_artifact["relative_path"]).read_text()

    assert dict(recording) == {"status": "COMPLETED", "needs_speaker_review": 1}
    assert [row["assignment_status"] for row in segments] == [
        "assigned",
        "overlap",
        "unassigned",
    ]
    assert segments[-1]["local_speaker_id"] is None
    assert json.loads(segments[1]["overlapping_speaker_ids_json"]) == [
        "SPEAKER_00",
        "SPEAKER_01",
    ]
    assert [dict(row) for row in recording_speakers] == [
        {
            "local_speaker_id": "SPEAKER_00",
            "person_id": None,
            "speaker_source": "unresolved",
            "speaker_score": None,
            "revision": 1,
        },
        {
            "local_speaker_id": "SPEAKER_01",
            "person_id": None,
            "speaker_source": "unresolved",
            "speaker_score": None,
            "revision": 1,
        },
    ]
    assert json_artifact["schema_version"] == 2
    assert markdown_artifact["schema_version"] == 1
    assert {row["revision"] for row in artifacts} == {1}
    assert payload["schema_version"] == 2
    assert payload["recording_id"] == registration.recording_id
    assert payload["model_fingerprints"]["diarization"]["model"].endswith("community-1")
    assert payload["classification"]["category"] == "회의"
    assert "Revision: 1" in markdown
    assert "SPEAKER_00" in markdown
    assert [dict(row) for row in jobs] == [
        {"kind": "transcribe", "status": "succeeded"},
        {"kind": "classify", "status": "succeeded"},
    ]
    assert source.read_bytes() == original
    assert transcription.path is not None and not transcription.path.exists()
    assert not process_one_job(settings.database_path, handler, logging.getLogger("test"))


def test_real_handler_can_stop_at_speech_evaluation_gate(
    settings_values: dict[str, Any],
) -> None:
    settings = _real_settings(settings_values)
    source = settings.recording_input_dir / "complete.m4a"
    shutil.copyfile(FIXTURE, source)
    ingest_file(settings.database_path, source)
    handler = RealSpeechPipelineHandler(
        settings,
        logging.getLogger("test"),
        transcription_adapter=StubTranscriptionAdapter(),
        alignment_adapter=StubAlignmentAdapter(),
        diarization_adapter=StubDiarizationAdapter(),
        continue_to_documents=False,
    )

    assert process_one_job(settings.database_path, handler, logging.getLogger("test"))

    with connect(settings.database_path) as connection:
        recording = connection.execute("SELECT status FROM recordings").fetchone()
        jobs = connection.execute("SELECT kind FROM jobs").fetchall()
    assert recording["status"] == "SPEAKER_REVIEW"
    assert [row["kind"] for row in jobs] == ["transcribe"]


def test_real_handler_records_sanitized_model_failure(settings_values: dict[str, Any]) -> None:
    settings = _real_settings(settings_values)
    source = settings.recording_input_dir / "complete.m4a"
    shutil.copyfile(FIXTURE, source)
    ingest_file(settings.database_path, source)
    adapter = StubTranscriptionAdapter(
        WhisperXAdapterError(
            WhisperXErrorCode.INVALID_RESPONSE,
            "WhisperX returned an invalid transcription response",
        )
    )
    handler = RealSpeechPipelineHandler(
        settings,
        logging.getLogger("test"),
        transcription_adapter=adapter,
        alignment_adapter=StubAlignmentAdapter(),
        diarization_adapter=StubDiarizationAdapter(),
    )

    assert process_one_job(settings.database_path, handler, logging.getLogger("test"))

    with connect(settings.database_path) as connection:
        recording = connection.execute(
            "SELECT status, last_error_code, last_error_message FROM recordings"
        ).fetchone()
        job = connection.execute("SELECT status, error_code, error_message FROM jobs").fetchone()
    assert dict(recording) == {
        "status": "FAILED",
        "last_error_code": "INVALID_RESPONSE",
        "last_error_message": (
            "음성 모델이 유효하지 않은 결과를 반환했습니다. 모델 버전과 설정을 확인하세요."
        ),
    }
    assert dict(job) == {
        "status": "failed",
        "error_code": "INVALID_RESPONSE",
        "error_message": (
            "음성 모델이 유효하지 않은 결과를 반환했습니다. 모델 버전과 설정을 확인하세요."
        ),
    }
    assert adapter.path is not None and not adapter.path.exists()


def test_model_oom_fails_once_with_action_guidance(settings_values: dict[str, Any]) -> None:
    settings = _real_settings(settings_values)
    source = settings.recording_input_dir / "complete.m4a"
    shutil.copyfile(FIXTURE, source)
    ingest_file(settings.database_path, source)
    handler = RealSpeechPipelineHandler(
        settings,
        logging.getLogger("test"),
        transcription_adapter=StubTranscriptionAdapter(
            WhisperXAdapterError(WhisperXErrorCode.MODEL_OOM, "private oom detail")
        ),
        alignment_adapter=StubAlignmentAdapter(),
        diarization_adapter=StubDiarizationAdapter(),
    )

    assert process_one_job(settings.database_path, handler, logging.getLogger("test"))

    with connect(settings.database_path) as connection:
        job = connection.execute(
            "SELECT status, attempts, error_code, error_message FROM jobs"
        ).fetchone()
    assert dict(job) == {
        "status": "failed",
        "attempts": 1,
        "error_code": "MODEL_OOM",
        "error_message": ("GPU 메모리가 부족합니다. WHISPER_BATCH_SIZE를 낮춘 뒤 다시 실행하세요."),
    }


def test_model_download_retries_three_times_then_fails(
    settings_values: dict[str, Any],
) -> None:
    settings = _real_settings(settings_values)
    source = settings.recording_input_dir / "complete.m4a"
    shutil.copyfile(FIXTURE, source)
    ingest_file(settings.database_path, source)
    handler = RealSpeechPipelineHandler(
        settings,
        logging.getLogger("test"),
        transcription_adapter=StubTranscriptionAdapter(
            WhisperXAdapterError(
                WhisperXErrorCode.MODEL_DOWNLOAD_FAILED,
                "private network detail",
            )
        ),
        alignment_adapter=StubAlignmentAdapter(),
        diarization_adapter=StubDiarizationAdapter(),
    )

    for expected_attempt in (1, 2, 3):
        assert process_one_job(settings.database_path, handler, logging.getLogger("test"))
        with connect(settings.database_path) as connection:
            job = connection.execute(
                "SELECT status, attempts, error_code, error_message FROM jobs"
            ).fetchone()
            if expected_attempt < 3:
                connection.execute("UPDATE jobs SET available_at = '2000-01-01T00:00:00+00:00'")
        assert job["attempts"] == expected_attempt
        assert job["status"] == ("queued" if expected_attempt < 3 else "failed")
        assert job["error_code"] == "MODEL_DOWNLOAD_FAILED"
        assert job["error_message"] == (
            "모델을 내려받지 못했습니다. 네트워크와 모델 캐시 권한을 확인하세요."
        )

    assert not process_one_job(settings.database_path, handler, logging.getLogger("test"))
