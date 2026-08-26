from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest
from app.alignment import AlignedSegment
from app.diarization import (
    AssignmentStatus,
    DiarizationConfig,
    DiarizationErrorCode,
    WhisperXDiarizationAdapter,
    WhisperXDiarizationError,
    WhisperXDiarizationRuntime,
)
from pydantic import SecretStr


class FakeTable:
    def __init__(self, records: object) -> None:
        self.records = records

    def to_dict(self, *, orient: str) -> object:
        assert orient == "records"
        return self.records


class FakeModel:
    def __init__(self, result: object, *, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls: list[tuple[str, int | None, int | None, bool]] = []

    def __call__(
        self,
        audio: str,
        *,
        num_speakers: int | None = None,
        min_speakers: int | None = None,
        max_speakers: int | None = None,
        return_embeddings: bool = False,
    ) -> object:
        assert num_speakers is None
        self.calls.append((audio, min_speakers, max_speakers, return_embeddings))
        if self.error is not None:
            raise self.error
        return self.result


class FakeRuntime:
    def __init__(
        self,
        result: object,
        *,
        model_error: Exception | None = None,
        run_error: Exception | None = None,
    ) -> None:
        self.model = FakeModel(result, error=run_error)
        self.model_error = model_error
        self.factory_calls: list[tuple[str, str | None, str, str]] = []
        self.DiarizationPipeline = self.create_pipeline

    def create_pipeline(
        self,
        model_name: str,
        token: str | None,
        device: str,
        cache_dir: str,
    ) -> FakeModel:
        self.factory_calls.append((model_name, token, device, cache_dir))
        if self.model_error is not None:
            raise self.model_error
        return self.model


def adapter_for(
    tmp_path: Path,
    runtime: FakeRuntime,
    *,
    min_speakers: int | None = None,
    max_speakers: int | None = None,
    hf_token: str | None = "hf_private_test_value",
    version_getter: Callable[[str], str] | None = None,
) -> WhisperXDiarizationAdapter:
    cache = tmp_path / "models"
    cache.mkdir(exist_ok=True)
    return WhisperXDiarizationAdapter(
        DiarizationConfig(
            model_cache_root=cache,
            min_speakers=min_speakers,
            max_speakers=max_speakers,
        ),
        hf_token=SecretStr(hf_token) if hf_token is not None else None,
        runtime_loader=lambda: cast(WhisperXDiarizationRuntime, runtime),
        version_getter=version_getter or (lambda package: versions()[package]),
    )


def versions() -> dict[str, str]:
    return {"whisperx": "3.8.6", "pyannote.audio": "4.0.7"}


def segments() -> tuple[AlignedSegment, ...]:
    return (
        AlignedSegment(start=0, end=1, text="first"),
        AlignedSegment(start=1, end=2, text="second"),
        AlignedSegment(start=2.2, end=2.8, text="unassigned"),
    )


def test_normalizes_speakers_and_assigns_overlap_and_unassigned(tmp_path: Path) -> None:
    runtime = FakeRuntime(
        FakeTable(
            [
                {"start": 1.0, "end": 2.0, "speaker": "raw-b"},
                {"start": 0.0, "end": 1.5, "speaker": "raw-a"},
            ]
        )
    )

    result = adapter_for(tmp_path, runtime).diarize(
        tmp_path / "private audio.wav",
        segments(),
        audio_duration=3,
    )

    assert [(turn.start, turn.end, turn.speaker_id) for turn in result.turns] == [
        (0.0, 1.5, "SPEAKER_00"),
        (1.0, 2.0, "SPEAKER_01"),
    ]
    assert result.speaker_ids == ("SPEAKER_00", "SPEAKER_01")
    assert [assignment.local_speaker_id for assignment in result.assignments] == [
        "SPEAKER_00",
        "SPEAKER_01",
        None,
    ]
    assert [assignment.status for assignment in result.assignments] == [
        AssignmentStatus.ASSIGNED,
        AssignmentStatus.OVERLAP,
        AssignmentStatus.UNASSIGNED,
    ]
    assert result.assignments[1].overlapping_speaker_ids == (
        "SPEAKER_00",
        "SPEAKER_01",
    )
    assert result.model_fingerprint.as_dict() == {
        "whisperx_version": "3.8.6",
        "pyannote_audio_version": "4.0.7",
        "model": "pyannote/speaker-diarization-community-1",
        "device": "cuda",
    }


def test_sequential_speakers_are_not_marked_as_overlapping(tmp_path: Path) -> None:
    runtime = FakeRuntime(
        [
            {"start": 0, "end": 1, "speaker": "a"},
            {"start": 1, "end": 2, "speaker": "b"},
        ]
    )
    source = (AlignedSegment(start=0, end=2, text="handoff"),)

    result = adapter_for(tmp_path, runtime).diarize(
        tmp_path / "audio.wav", source, audio_duration=2
    )

    assert result.assignments[0].status == AssignmentStatus.ASSIGNED
    assert result.assignments[0].local_speaker_id == "SPEAKER_00"
    assert result.assignments[0].overlapping_speaker_ids == ()


def test_primary_speaker_tie_uses_earliest_turn_then_id(tmp_path: Path) -> None:
    runtime = FakeRuntime(
        [
            {"start": 1, "end": 2, "speaker": "later"},
            {"start": 0, "end": 1, "speaker": "earlier"},
        ]
    )

    result = adapter_for(tmp_path, runtime).diarize(
        tmp_path / "audio.wav",
        (AlignedSegment(start=0, end=2, text="tie"),),
        audio_duration=2,
    )

    assert result.assignments[0].local_speaker_id == "SPEAKER_00"


def test_clamps_turns_to_audio_bounds_and_discards_empty_tail(tmp_path: Path) -> None:
    runtime = FakeRuntime(
        [
            {"start": -1, "end": 0.5, "speaker": "a"},
            {"start": 2.5, "end": 4, "speaker": "b"},
            {"start": 4, "end": 5, "speaker": "c"},
        ]
    )

    result = adapter_for(tmp_path, runtime).diarize(tmp_path / "audio.wav", (), audio_duration=3)

    assert [(turn.start, turn.end) for turn in result.turns] == [(0.0, 0.5), (2.5, 3.0)]


def test_empty_diarization_marks_every_segment_unassigned(tmp_path: Path) -> None:
    result = adapter_for(tmp_path, FakeRuntime(FakeTable([]))).diarize(
        tmp_path / "audio.wav", segments(), audio_duration=3
    )

    assert result.turns == ()
    assert result.speaker_ids == ()
    assert all(item.status == AssignmentStatus.UNASSIGNED for item in result.assignments)


def test_reuses_pipeline_and_passes_constraints_and_token(tmp_path: Path) -> None:
    runtime = FakeRuntime([])
    adapter = adapter_for(tmp_path, runtime, min_speakers=2, max_speakers=4)

    adapter.diarize(tmp_path / "one.wav", (), audio_duration=1)
    adapter.diarize(tmp_path / "two.wav", (), audio_duration=1)

    assert len(runtime.factory_calls) == 1
    model_name, token, device, cache_dir = runtime.factory_calls[0]
    assert model_name == "pyannote/speaker-diarization-community-1"
    assert token == "hf_private_test_value"
    assert device == "cuda"
    assert cache_dir == str((tmp_path / "models").resolve())
    assert runtime.model.calls == [
        (str(tmp_path / "one.wav"), 2, 4, False),
        (str(tmp_path / "two.wav"), 2, 4, False),
    ]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"model": " "},
        {"device": " "},
        {"min_speakers": 0},
        {"max_speakers": -1},
        {"min_speakers": 3, "max_speakers": 2},
    ],
)
def test_rejects_invalid_config(tmp_path: Path, kwargs: dict[str, object]) -> None:
    cache = tmp_path / "models"
    cache.mkdir()

    with pytest.raises(ValueError):
        DiarizationConfig(model_cache_root=cache, **kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize("duration", [0, -1, float("inf"), float("nan")])
def test_rejects_invalid_audio_duration(tmp_path: Path, duration: float) -> None:
    with pytest.raises(WhisperXDiarizationError) as error:
        adapter_for(tmp_path, FakeRuntime([])).diarize(
            tmp_path / "audio.wav", (), audio_duration=duration
        )

    assert error.value.code == DiarizationErrorCode.INVALID_RESPONSE


@pytest.mark.parametrize(
    "result",
    [
        None,
        {},
        [None],
        [{"start": 0, "end": 1}],
        [{"start": "0", "end": 1, "speaker": "a"}],
        [{"start": 0, "end": 0, "speaker": "a"}],
        [{"start": 0, "end": 1, "speaker": " "}],
        FakeTable("not records"),
    ],
)
def test_rejects_invalid_diarization_response(tmp_path: Path, result: object) -> None:
    with pytest.raises(WhisperXDiarizationError) as error:
        adapter_for(tmp_path, FakeRuntime(result)).diarize(
            tmp_path / "audio.wav", (), audio_duration=2
        )

    assert error.value.code == DiarizationErrorCode.INVALID_RESPONSE


@pytest.mark.parametrize(
    ("runtime", "expected"),
    [
        (
            FakeRuntime([], model_error=RuntimeError("load failed")),
            DiarizationErrorCode.MODEL_LOAD_FAILED,
        ),
        (
            FakeRuntime([], model_error=RuntimeError("CUDA out of memory")),
            DiarizationErrorCode.MODEL_OOM,
        ),
        (
            FakeRuntime([], model_error=RuntimeError("403 gated repo")),
            DiarizationErrorCode.MODEL_ACCESS_DENIED,
        ),
        (
            FakeRuntime([], model_error=RuntimeError("network timed out")),
            DiarizationErrorCode.MODEL_DOWNLOAD_FAILED,
        ),
        (
            FakeRuntime([], run_error=RuntimeError("run failed")),
            DiarizationErrorCode.DIARIZATION_FAILED,
        ),
        (
            FakeRuntime([], run_error=RuntimeError("CUDA out of memory")),
            DiarizationErrorCode.MODEL_OOM,
        ),
        (
            FakeRuntime([], run_error=RuntimeError("401 unauthorized")),
            DiarizationErrorCode.MODEL_ACCESS_DENIED,
        ),
    ],
)
def test_classifies_failures_without_sensitive_details(
    tmp_path: Path,
    runtime: FakeRuntime,
    expected: DiarizationErrorCode,
) -> None:
    with pytest.raises(WhisperXDiarizationError) as error:
        adapter_for(tmp_path, runtime).diarize(
            tmp_path / "private-source.wav", (), audio_duration=2
        )

    assert error.value.code == expected
    assert "private-source.wav" not in str(error.value)
    assert "hf_private_test_value" not in str(error.value)
    assert "failed" not in str(error.value).casefold()


def test_missing_token_is_not_rendered_or_passed_as_empty_string(tmp_path: Path) -> None:
    runtime = FakeRuntime([])

    adapter_for(tmp_path, runtime, hf_token=None).diarize(
        tmp_path / "audio.wav", (), audio_duration=1
    )

    assert runtime.factory_calls[0][1] is None
