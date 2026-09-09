from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.speech_failures import _POLICIES as SPEECH_POLICIES

FailureCategory = Literal["transient", "action_required", "invalid_output", "internal"]


@dataclass(frozen=True)
class JobFailurePolicy:
    category: FailureCategory
    message: str
    retryable: bool = False


_TRANSIENT = {
    "CLASSIFICATION_TIMEOUT",
    "CLASSIFICATION_PROVIDER_UNAVAILABLE",
    "SUMMARY_TIMEOUT",
    "SUMMARY_PROVIDER_UNAVAILABLE",
    "SPEAKER_EMBEDDING_SOURCE_CHANGED",
    "SPEAKER_CLIP_NOT_AVAILABLE",
    "SPEAKER_EMBEDDING_MODEL_LOAD_FAILED",
    "SPEAKER_EMBEDDING_FAILED",
}
_INVALID_OUTPUT = {
    "SUMMARY_INVALID_OUTPUT",
    "CLASSIFICATION_INVALID_OUTPUT",
    "CLASSIFICATION_ERROR",
    "MALFORMED_CLASSIFICATION",
    "MISSING_CLASSIFICATION_FIELD",
    "DISALLOWED_CLASSIFICATION_CATEGORY",
    "INVALID_RESPONSE",
    "INVALID_SPEECH_RESULT",
    "INVALID_FAKE_RESULT",
    "INVALID_RETRANSCRIPTION_RESULT",
    "INVALID_SPEAKER_EMBEDDING",
}
_RECOVERY_MESSAGES = {
    "RECOVERY_REVISION_CHANGED": "입력이 변경되었습니다. 최신 내용을 확인한 뒤 새로 요청해 주세요.",
    "RECOVERY_SETTINGS_CHANGED": (
        "모델 또는 처리 설정이 달라졌습니다. 설정을 확인한 뒤 전용 기능에서 새로 요청해 주세요."
    ),
    "RECOVERY_INPUT_MISSING": (
        "필요한 원본 또는 결과 파일이 없습니다. 동기화와 저장소를 확인해 주세요."
    ),
    "RECOVERY_INPUT_INVALID": (
        "저장된 입력이나 결과의 무결성이 일치하지 않습니다. 원본과 결과 파일을 확인해 주세요."
    ),
    "RECOVERY_ATTEMPTS_EXHAUSTED": (
        "중단된 작업이 자동 시도 한도에 도달했습니다. 입력을 확인한 뒤 다시 시도해 주세요."
    ),
}


def job_failure_policy(code: str | None) -> JobFailurePolicy | None:
    if code is None:
        return None
    if code in _INVALID_OUTPUT:
        return JobFailurePolicy(
            "invalid_output",
            "처리 결과가 유효하지 않습니다. 입력과 설정을 확인한 뒤 다시 요청해 주세요.",
        )
    if code in SPEECH_POLICIES:
        policy = SPEECH_POLICIES[code]
        return JobFailurePolicy(
            "transient" if policy.retryable else "action_required",
            policy.message.replace("자동 재시도합니다.", "실행 상태를 확인해 주세요."),
            policy.retryable,
        )
    if code in _TRANSIENT:
        return JobFailurePolicy(
            "transient", "일시적인 처리 오류입니다. 연결과 실행 환경을 확인해 주세요.", True
        )
    if code in _RECOVERY_MESSAGES:
        return JobFailurePolicy("action_required", _RECOVERY_MESSAGES[code])
    if code in {
        "SUMMARY_INVALID_INPUT",
        "INVALID_RENDER_SOURCE",
        "MODEL_ACCESS_DENIED",
        "SPEAKER_EMBEDDING_ACCESS_DENIED",
    }:
        return JobFailurePolicy(
            "action_required", "입력 자료와 모델 접근 권한을 확인한 뒤 다시 요청해 주세요."
        )
    return JobFailurePolicy(
        "internal", "예상하지 못한 내부 오류입니다. 작업 ID와 오류 코드를 관리자에게 알려 주세요."
    )
