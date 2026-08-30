from __future__ import annotations

import json
import socket
import uuid

import pytest
from app.classification import (
    ClassificationTimeoutError,
    DisallowedClassificationCategoryError,
    FakeClassificationAdapter,
    MalformedClassificationError,
    MissingClassificationFieldError,
)
from app.schema import Segment, Transcript


def _transcript() -> Transcript:
    return Transcript(
        recording_id=uuid.uuid4(),
        content_sha256="a" * 64,
        revision=1,
        language="ko",
        needs_speaker_review=True,
        segments=[
            Segment(
                id=uuid.uuid4(),
                start_ms=0,
                end_ms=1_000,
                local_speaker_id="SPEAKER_00",
                text="로컬 테스트 발화",
            )
        ],
    )


def _valid_response(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": 1,
        "category": "회의",
        "confidence": 0.9,
        "reason": "결정 사항이 포함됨",
    }
    value.update(changes)
    return value


def test_fake_adapter_is_deterministic_and_never_uses_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(socket, "socket", lambda *_args, **_kwargs: pytest.fail("network used"))
    adapter = FakeClassificationAdapter(lambda _digest: json.dumps(_valid_response()))

    first = adapter.classify(_transcript(), ("회의", "기타"))
    second = adapter.classify(_transcript(), ("회의", "기타"))

    assert first == second
    assert first.schema_version == 1
    assert set(adapter.fingerprint) == {
        "model",
        "prompt_sha256",
        "schema_sha256",
        "schema_version",
    }
    assert len(str(adapter.fingerprint["prompt_sha256"])) == 64


@pytest.mark.parametrize("raw", ["{broken", [], 1, None])
def test_fake_adapter_distinguishes_malformed_response(raw: object) -> None:
    with pytest.raises(MalformedClassificationError) as error:
        FakeClassificationAdapter(lambda _digest: raw).classify(_transcript(), ("회의",))

    assert error.value.code == "MALFORMED_CLASSIFICATION"


def test_fake_adapter_distinguishes_missing_fields() -> None:
    with pytest.raises(MissingClassificationFieldError) as error:
        FakeClassificationAdapter(lambda _digest: {"category": "회의"}).classify(
            _transcript(), ("회의",)
        )

    assert error.value.code == "MISSING_CLASSIFICATION_FIELD"


def test_fake_adapter_distinguishes_disallowed_category() -> None:
    with pytest.raises(DisallowedClassificationCategoryError) as error:
        FakeClassificationAdapter(lambda _digest: _valid_response(category="비밀")).classify(
            _transcript(), ("회의",)
        )

    assert error.value.code == "DISALLOWED_CLASSIFICATION_CATEGORY"


def test_automatic_classification_rejects_null_confidence() -> None:
    with pytest.raises(MalformedClassificationError):
        FakeClassificationAdapter(lambda _digest: _valid_response(confidence=None)).classify(
            _transcript(), ("회의",)
        )


def test_fake_adapter_distinguishes_timeout() -> None:
    def timeout(_digest: str) -> object:
        raise TimeoutError

    with pytest.raises(ClassificationTimeoutError) as error:
        FakeClassificationAdapter(timeout).classify(_transcript(), ("회의",))

    assert error.value.code == "CLASSIFICATION_TIMEOUT"
