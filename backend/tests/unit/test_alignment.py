from __future__ import annotations

from pathlib import Path

import pytest
from app.alignment import (
    AlignmentConfig,
    AlignmentErrorCode,
    WhisperXAlignmentAdapter,
    WhisperXAlignmentError,
)
from app.transcription import TranscriptionSegment


class FakeRuntime:
    def __init__(
        self,
        result: object,
        *,
        model_error: Exception | None = None,
        align_error: Exception | None = None,
        audio_error: Exception | None = None,
    ) -> None:
        self.result = result
        self.model_error = model_error
        self.align_error = align_error
        self.audio_error = audio_error
        self.model_calls: list[dict[str, object]] = []
        self.align_calls: list[dict[str, object]] = []
        self.audio_calls: list[str] = []

    def load_align_model(
        self,
        language_code: str,
        device: str,
        *,
        model_name: str | None = None,
        model_dir: str | None = None,
    ) -> tuple[object, object]:
        self.model_calls.append(
            {
                "language_code": language_code,
                "device": device,
                "model_name": model_name,
                "model_dir": model_dir,
            }
        )
        if self.model_error is not None:
            raise self.model_error
        return "align-model", "align-metadata"

    def load_audio(self, file: str) -> object:
        self.audio_calls.append(file)
        if self.audio_error is not None:
            raise self.audio_error
        return "decoded-audio"

    def align(
        self,
        transcript: list[dict[str, object]],
        model: object,
        align_model_metadata: object,
        audio: object,
        device: str,
        *,
        interpolate_method: str = "nearest",
        return_char_alignments: bool = False,
        print_progress: bool = False,
    ) -> object:
        self.align_calls.append(
            {
                "transcript": transcript,
                "model": model,
                "metadata": align_model_metadata,
                "audio": audio,
                "device": device,
                "interpolate_method": interpolate_method,
                "return_char_alignments": return_char_alignments,
                "print_progress": print_progress,
            }
        )
        if self.align_error is not None:
            raise self.align_error
        return self.result


def source_segments() -> tuple[TranscriptionSegment, ...]:
    return (
        TranscriptionSegment(0.0, 1.25, "첫 문장"),
        TranscriptionSegment(1.25, 2.5, "두 번째 문장"),
    )


def valid_result() -> dict[str, object]:
    return {
        "segments": [
            {
                "start": 0.1,
                "end": 1.2,
                "text": "첫 문장",
                "words": [
                    {"word": "첫", "start": 0.1, "end": 0.4, "score": 0.95},
                    {"word": "문장", "start": 0.5, "end": 1.2, "score": 0.9},
                ],
            },
            {
                "start": 1.3,
                "end": 2.4,
                "text": "두 번째 문장",
                "words": [{"word": "두", "start": 1.3, "end": 1.6}],
            },
        ]
    }


def adapter_for(tmp_path: Path, runtime: FakeRuntime) -> WhisperXAlignmentAdapter:
    return WhisperXAlignmentAdapter(
        AlignmentConfig(model_cache_root=tmp_path),
        runtime_loader=lambda: runtime,
        version_getter=lambda package: "3.8.6" if package == "whisperx" else "unexpected",
    )


def test_aligns_transcription_and_normalizes_words(tmp_path: Path) -> None:
    runtime = FakeRuntime(valid_result())
    adapter = adapter_for(tmp_path, runtime)
    source = tmp_path / "normalized.wav"

    result = adapter.align(source, source_segments(), " KO ", audio_duration=2.5)

    assert runtime.model_calls == [
        {
            "language_code": "ko",
            "device": "cuda",
            "model_name": None,
            "model_dir": str(tmp_path),
        }
    ]
    assert runtime.audio_calls == [str(source)]
    assert runtime.align_calls[0]["transcript"] == [
        {"start": 0.0, "end": 1.25, "text": "첫 문장"},
        {"start": 1.25, "end": 2.5, "text": "두 번째 문장"},
    ]
    assert result.language == "ko"
    assert len(result.segments) == 2
    assert [word.word for word in result.word_segments] == ["첫", "문장", "두"]
    assert result.model_fingerprint.as_dict() == {
        "whisperx_version": "3.8.6",
        "device": "cuda",
        "interpolate_method": "nearest",
        "language": "ko",
    }


def test_caches_alignment_model_per_language(tmp_path: Path) -> None:
    runtime = FakeRuntime(valid_result())
    adapter = adapter_for(tmp_path, runtime)

    adapter.align(tmp_path / "one.wav", source_segments(), "ko", audio_duration=2.5)
    adapter.align(tmp_path / "two.wav", source_segments(), "ko", audio_duration=2.5)

    assert len(runtime.model_calls) == 1
    assert len(runtime.align_calls) == 2


def test_preserves_segment_and_missing_word_times(tmp_path: Path) -> None:
    runtime = FakeRuntime(
        {
            "segments": [
                {
                    "text": "첫 문장",
                    "words": [{"word": "첫"}, {"word": "문장", "start": 0.5}],
                }
            ]
        }
    )

    result = adapter_for(tmp_path, runtime).align(
        tmp_path / "audio.wav", source_segments(), "ko", audio_duration=2.5
    )

    assert [(segment.start, segment.end, segment.text) for segment in result.segments] == [
        (0.0, 1.25, "첫 문장"),
        (1.25, 2.5, "두 번째 문장"),
    ]
    assert [(word.start, word.end) for word in result.segments[0].words] == [
        (None, None),
        (None, None),
    ]


def test_clamps_segment_word_and_score_to_audio_bounds(tmp_path: Path) -> None:
    runtime = FakeRuntime(
        {
            "segments": [
                {
                    "start": -5,
                    "end": 8,
                    "text": "첫 문장",
                    "words": [{"word": "첫", "start": -1, "end": 8, "score": 2}],
                },
                {"start": 2, "end": 1, "text": "두 번째 문장"},
            ]
        }
    )

    result = adapter_for(tmp_path, runtime).align(
        tmp_path / "audio.wav", source_segments(), "ko", audio_duration=2.5
    )

    assert (result.segments[0].start, result.segments[0].end) == (0.0, 2.5)
    assert (result.word_segments[0].start, result.word_segments[0].end) == (0.0, 2.5)
    assert result.word_segments[0].score == 1.0
    assert (result.segments[1].start, result.segments[1].end) == (1.25, 2.5)


def test_empty_transcription_still_loads_and_calls_alignment_model(tmp_path: Path) -> None:
    runtime = FakeRuntime({"segments": []})

    result = adapter_for(tmp_path, runtime).align(
        tmp_path / "silence.wav", (), "en", audio_duration=2.0
    )

    assert result.segments == ()
    assert result.word_segments == ()
    assert len(runtime.model_calls) == 1
    assert runtime.align_calls[0]["transcript"] == []


def test_accepts_alignment_output_split_into_more_sentence_segments(tmp_path: Path) -> None:
    runtime = FakeRuntime(
        {
            "segments": [
                {"start": 0, "end": 0.5, "text": "첫", "words": []},
                {"start": 0.5, "end": 1.25, "text": "문장", "words": []},
                {"start": 1.25, "end": 2.5, "text": "두 번째 문장", "words": []},
            ]
        }
    )

    result = adapter_for(tmp_path, runtime).align(
        tmp_path / "audio.wav", source_segments(), "ko", audio_duration=2.5
    )

    assert [(segment.start, segment.end, segment.text) for segment in result.segments] == [
        (0.0, 0.5, "첫"),
        (0.5, 1.25, "문장"),
        (1.25, 2.5, "두 번째 문장"),
    ]


@pytest.mark.parametrize("language", ["", "  "])
def test_rejects_empty_language(tmp_path: Path, language: str) -> None:
    with pytest.raises(WhisperXAlignmentError) as error:
        adapter_for(tmp_path, FakeRuntime(valid_result())).align(
            tmp_path / "audio.wav", source_segments(), language, audio_duration=2.5
        )
    assert error.value.code == AlignmentErrorCode.INVALID_RESPONSE


@pytest.mark.parametrize("duration", [0, -1, float("inf"), float("nan")])
def test_rejects_invalid_audio_duration(tmp_path: Path, duration: float) -> None:
    with pytest.raises(WhisperXAlignmentError) as error:
        adapter_for(tmp_path, FakeRuntime(valid_result())).align(
            tmp_path / "audio.wav", source_segments(), "ko", audio_duration=duration
        )
    assert error.value.code == AlignmentErrorCode.INVALID_RESPONSE


@pytest.mark.parametrize(
    "result",
    [
        None,
        {},
        {"segments": "invalid"},
        {"segments": [None, {}]},
        {"segments": [{"words": "invalid"}, {}]},
        {"segments": [{"words": [{}]}, {}]},
        {"segments": [{}, {}, {}]},
    ],
)
def test_rejects_invalid_alignment_response(tmp_path: Path, result: object) -> None:
    with pytest.raises(WhisperXAlignmentError) as error:
        adapter_for(tmp_path, FakeRuntime(result)).align(
            tmp_path / "audio.wav", source_segments(), "ko", audio_duration=2.5
        )
    assert error.value.code == AlignmentErrorCode.INVALID_RESPONSE


@pytest.mark.parametrize(
    ("runtime", "expected"),
    [
        (
            FakeRuntime(valid_result(), model_error=RuntimeError("load failed")),
            AlignmentErrorCode.MODEL_LOAD_FAILED,
        ),
        (
            FakeRuntime(valid_result(), model_error=RuntimeError("CUDA out of memory")),
            AlignmentErrorCode.MODEL_OOM,
        ),
        (
            FakeRuntime(valid_result(), model_error=RuntimeError("unsupported language: xx")),
            AlignmentErrorCode.UNSUPPORTED_LANGUAGE,
        ),
        (
            FakeRuntime(valid_result(), model_error=RuntimeError("403 gated repo")),
            AlignmentErrorCode.MODEL_ACCESS_DENIED,
        ),
        (
            FakeRuntime(valid_result(), model_error=RuntimeError("network timed out")),
            AlignmentErrorCode.MODEL_DOWNLOAD_FAILED,
        ),
        (
            FakeRuntime(valid_result(), align_error=RuntimeError("align failed")),
            AlignmentErrorCode.ALIGNMENT_FAILED,
        ),
        (
            FakeRuntime(valid_result(), align_error=RuntimeError("CUDA out of memory")),
            AlignmentErrorCode.MODEL_OOM,
        ),
        (
            FakeRuntime(valid_result(), audio_error=RuntimeError("decode failed")),
            AlignmentErrorCode.ALIGNMENT_FAILED,
        ),
    ],
)
def test_classifies_failures_without_sensitive_details(
    tmp_path: Path,
    runtime: FakeRuntime,
    expected: AlignmentErrorCode,
) -> None:
    with pytest.raises(WhisperXAlignmentError) as error:
        adapter_for(tmp_path, runtime).align(
            tmp_path / "private-source.wav", source_segments(), "ko", audio_duration=2.5
        )
    assert error.value.code == expected
    assert "private-source.wav" not in str(error.value)
    assert "failed" not in str(error.value).casefold()
