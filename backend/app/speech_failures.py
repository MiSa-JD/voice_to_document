from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SpeechFailurePolicy:
    retryable: bool
    message: str


_POLICIES: dict[str, SpeechFailurePolicy] = {
    "MODEL_OOM": SpeechFailurePolicy(
        False,
        "GPU 메모리가 부족합니다. WHISPER_BATCH_SIZE를 낮춘 뒤 다시 실행하세요.",
    ),
    "MODEL_ACCESS_DENIED": SpeechFailurePolicy(
        False,
        "HF_TOKEN과 pyannote 모델 사용 승인을 확인한 뒤 다시 실행하세요.",
    ),
    "MODEL_DOWNLOAD_FAILED": SpeechFailurePolicy(
        True,
        "모델을 내려받지 못했습니다. 네트워크와 모델 캐시 권한을 확인하세요.",
    ),
    "MODEL_LOAD_FAILED": SpeechFailurePolicy(
        False,
        "음성 모델을 불러오지 못했습니다. 고정된 모델·CUDA runtime 설정을 확인하세요.",
    ),
    "TRANSCRIPTION_FAILED": SpeechFailurePolicy(
        True,
        "전사 실행이 일시적으로 실패했습니다. 자동 재시도합니다.",
    ),
    "ALIGNMENT_FAILED": SpeechFailurePolicy(
        True,
        "시간 정렬이 일시적으로 실패했습니다. 자동 재시도합니다.",
    ),
    "DIARIZATION_FAILED": SpeechFailurePolicy(
        True,
        "화자 분리가 일시적으로 실패했습니다. 자동 재시도합니다.",
    ),
    "FFMPEG_TIMEOUT": SpeechFailurePolicy(
        True,
        "오디오 변환 시간이 초과되었습니다. 자동 재시도합니다.",
    ),
    "INPUT_IO_ERROR": SpeechFailurePolicy(
        True,
        "원본 녹음을 일시적으로 읽을 수 없습니다. 저장소 상태를 확인하세요.",
    ),
    "ARTIFACT_IO_ERROR": SpeechFailurePolicy(
        True,
        "결과 파일을 일시적으로 저장할 수 없습니다. 저장소 상태를 확인하세요.",
    ),
    "FFMPEG_NOT_FOUND": SpeechFailurePolicy(
        False,
        "FFmpeg를 실행할 수 없습니다. worker 이미지와 실행 환경을 확인하세요.",
    ),
    "DISK_FULL": SpeechFailurePolicy(
        False,
        "작업 디스크 공간이 부족합니다. 공간을 확보한 뒤 다시 실행하세요.",
    ),
    "AUDIO_STREAM_INVALID": SpeechFailurePolicy(
        False,
        "사용 가능한 음성 스트림이 없습니다. 원본 녹음을 다시 동기화하세요.",
    ),
    "NORMALIZATION_FAILED": SpeechFailurePolicy(
        False,
        "녹음을 변환할 수 없습니다. 원본 파일이 손상되지 않았는지 확인하세요.",
    ),
    "INPUT_NOT_AVAILABLE": SpeechFailurePolicy(
        False,
        "원본 녹음이 없거나 허용된 입력 폴더 밖에 있습니다. 동기화 상태를 확인하세요.",
    ),
    "UNSUPPORTED_LANGUAGE": SpeechFailurePolicy(
        False,
        "감지된 언어를 정렬할 수 없습니다. WHISPER_LANGUAGE 설정을 확인하세요.",
    ),
    "INVALID_RESPONSE": SpeechFailurePolicy(
        False,
        "음성 모델이 유효하지 않은 결과를 반환했습니다. 모델 버전과 설정을 확인하세요.",
    ),
    "INVALID_SPEECH_RESULT": SpeechFailurePolicy(
        False,
        "정규화할 수 없는 음성 결과입니다. 모델 버전과 입력 녹음을 확인하세요.",
    ),
}


def speech_failure_policy(code: str) -> SpeechFailurePolicy:
    return _POLICIES.get(
        code,
        SpeechFailurePolicy(False, "음성 처리에 실패했습니다. worker 로그를 확인하세요."),
    )


def is_model_access_denied(error: BaseException) -> bool:
    return _matches_exception_chain(
        error,
        type_markers=("gatedrepoerror", "repositorynotfounderror"),
        message_markers=(
            "401",
            "403",
            "access denied",
            "forbidden",
            "gated repo",
            "gated repository",
            "unauthorized",
        ),
    )


def is_model_download_failure(error: BaseException) -> bool:
    return _matches_exception_chain(
        error,
        type_markers=(
            "connectionerror",
            "connecttimeout",
            "readtimeout",
            "proxyerror",
            "offlineerror",
        ),
        message_markers=(
            "429",
            "502",
            "503",
            "504",
            "connection reset",
            "connection refused",
            "failed to establish a new connection",
            "name resolution",
            "network is unreachable",
            "rate limit",
            "temporary failure",
            "timed out",
            "timeout",
        ),
    )


def _matches_exception_chain(
    error: BaseException,
    *,
    type_markers: tuple[str, ...],
    message_markers: tuple[str, ...],
) -> bool:
    current: BaseException | None = error
    visited: set[int] = set()
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        name = type(current).__name__.casefold()
        message = str(current).casefold()
        if any(marker in name for marker in type_markers) or any(
            marker in message for marker in message_markers
        ):
            return True
        current = current.__cause__ or current.__context__
    return False
