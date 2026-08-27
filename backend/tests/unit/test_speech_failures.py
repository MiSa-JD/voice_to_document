from __future__ import annotations

from app.speech_failures import (
    is_model_access_denied,
    is_model_download_failure,
    speech_failure_policy,
)


def test_user_action_failures_do_not_retry() -> None:
    oom = speech_failure_policy("MODEL_OOM")
    access = speech_failure_policy("MODEL_ACCESS_DENIED")

    assert not oom.retryable
    assert "WHISPER_BATCH_SIZE" in oom.message
    assert not access.retryable
    assert "HF_TOKEN" in access.message


def test_transient_failures_retry_with_safe_guidance() -> None:
    download = speech_failure_policy("MODEL_DOWNLOAD_FAILED")
    io_error = speech_failure_policy("INPUT_IO_ERROR")

    assert download.retryable
    assert "네트워크" in download.message
    assert io_error.retryable
    assert "저장소" in io_error.message


def test_unknown_failure_is_permanent_and_sanitized() -> None:
    policy = speech_failure_policy("PRIVATE_UNKNOWN")

    assert not policy.retryable
    assert "PRIVATE_UNKNOWN" not in policy.message


def test_exception_chain_classifies_access_before_download() -> None:
    access = RuntimeError("403 gated repository")
    download = RuntimeError("temporary name resolution failure")
    wrapped_access = RuntimeError("outer")
    wrapped_access.__cause__ = access

    assert is_model_access_denied(wrapped_access)
    assert not is_model_download_failure(wrapped_access)
    assert is_model_download_failure(download)
    assert not is_model_access_denied(download)
