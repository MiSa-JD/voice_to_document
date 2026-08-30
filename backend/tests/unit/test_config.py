from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from app.config import Settings
from pydantic import ValidationError


def test_valid_fake_settings(settings_values: dict[str, Any]) -> None:
    settings = Settings(**settings_values)

    assert settings.effective_speech_mode == "fake"
    assert settings.effective_document_mode == "fake"
    assert settings.categories == ("강의", "일상 대화", "회의", "게임 목록", "기타")
    assert settings.database_path == Path(settings_values["APP_DATA_DIR"]) / "app.db"
    assert settings.document_root == Path(settings_values["SUMMARY_ROOT"])
    assert settings.category_definitions[1].display_name == "일상 대화"
    assert settings.category_definitions[1].slug == "일상-대화"
    assert settings.whisper_batch_size == 4
    assert settings.whisper_language is None
    assert "hf_token" not in settings.public_summary()


def test_missing_required_path_names_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "RECORDING_INPUT_DIR",
        "TRANSCRIPT_ROOT",
        "SPEAKER_ROOT",
        "SUMMARY_ROOT",
        "APP_DATA_DIR",
    ):
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(ValidationError, match="RECORDING_INPUT_DIR"):
        Settings.model_validate({})


def test_rejects_missing_directory(settings_values: dict[str, Any], tmp_path: Path) -> None:
    settings_values["TRANSCRIPT_ROOT"] = tmp_path / "missing"

    with pytest.raises(ValidationError, match="TRANSCRIPT_ROOT does not exist"):
        Settings(**settings_values)


def test_rejects_overlapping_roots(settings_values: dict[str, Any]) -> None:
    app_root = Path(settings_values["APP_DATA_DIR"])
    nested = app_root / "nested"
    nested.mkdir()
    settings_values["SUMMARY_ROOT"] = nested

    with pytest.raises(ValidationError, match="DOCUMENT_ROOT and APP_DATA_DIR must not overlap"):
        Settings(**settings_values)


def test_rejects_unknown_auto_summary_category(settings_values: dict[str, Any]) -> None:
    settings_values["CATEGORIES"] = "회의,기타"
    settings_values["AUTO_SUMMARY_CATEGORIES"] = "강의"

    with pytest.raises(ValidationError, match="AUTO_SUMMARY_CATEGORIES"):
        Settings(**settings_values)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("CATEGORIES", "회의,,기타"),
        ("CATEGORIES", "회의,회의"),
        ("AUTO_SUMMARY_CATEGORIES", "회의,"),
        ("AUTO_SUMMARY_CATEGORIES", "회의,회의"),
    ],
)
def test_rejects_empty_or_duplicate_category_values(
    settings_values: dict[str, Any], name: str, value: str
) -> None:
    settings_values[name] = value

    with pytest.raises(ValidationError, match=f"{name} must not contain"):
        Settings(**settings_values)


def test_rejects_category_slug_collision(settings_values: dict[str, Any]) -> None:
    settings_values["CATEGORIES"] = "Team Meeting,team-meeting"
    settings_values["AUTO_SUMMARY_CATEGORIES"] = "Team Meeting"

    with pytest.raises(ValidationError, match="colliding slugs"):
        Settings(**settings_values)


def test_document_root_takes_precedence_over_legacy_summary_root(
    settings_values: dict[str, Any], tmp_path: Path
) -> None:
    document_root = tmp_path / "markdown"
    document_root.mkdir()
    settings_values["DOCUMENT_ROOT"] = document_root

    settings = Settings(**settings_values)

    assert settings.document_root == document_root
    assert settings.summary_root == document_root


def test_real_speech_only_requires_hf_token(settings_values: dict[str, Any]) -> None:
    settings_values.update({"SPEECH_MODE": "real", "SERVICE_NAME": "worker"})

    with pytest.raises(ValidationError, match="HF_TOKEN"):
        Settings(**settings_values)

    settings_values["HF_TOKEN"] = "hf_private_test_value"
    settings = Settings(**settings_values)

    assert settings.effective_speech_mode == "real"
    assert settings.effective_document_mode == "fake"


def test_api_real_speech_skips_worker_token_and_model_cache_validation(
    settings_values: dict[str, Any], tmp_path: Path
) -> None:
    settings_values.update(
        {
            "SERVICE_NAME": "api",
            "SPEECH_MODE": "real",
            "HF_TOKEN": "",
            "MODEL_CACHE_ROOT": tmp_path / "not-mounted-in-api",
        }
    )

    settings = Settings(**settings_values)

    assert settings.effective_speech_mode == "real"


def test_whisper_language_blank_means_auto_detection(settings_values: dict[str, Any]) -> None:
    settings_values["WHISPER_LANGUAGE"] = "  "

    settings = Settings(**settings_values)

    assert settings.whisper_language is None


def test_rejects_non_positive_whisper_batch_size(settings_values: dict[str, Any]) -> None:
    settings_values["WHISPER_BATCH_SIZE"] = 0

    with pytest.raises(ValidationError, match="WHISPER_BATCH_SIZE"):
        Settings(**settings_values)


def test_auto_match_defaults_to_candidate_only_mode(settings_values: dict[str, Any]) -> None:
    settings = Settings(**settings_values)

    assert settings.speaker_auto_match_enabled is False
    assert settings.speaker_auto_match_threshold is None
    assert settings.speaker_match_margin is None
    assert settings.speaker_finalization_settings_fingerprint


def test_auto_match_requires_both_bounded_scores(settings_values: dict[str, Any]) -> None:
    settings_values["SPEAKER_AUTO_MATCH_ENABLED"] = True

    with pytest.raises(ValidationError, match="SPEAKER_AUTO_MATCH_THRESHOLD"):
        Settings(**settings_values)

    settings_values.update({"SPEAKER_AUTO_MATCH_THRESHOLD": 0.8, "SPEAKER_MATCH_MARGIN": 0.1})
    assert Settings(**settings_values).speaker_auto_match_enabled is True

    settings_values["SPEAKER_MATCH_MARGIN"] = 1.1
    with pytest.raises(ValidationError, match="SPEAKER_MATCH_MARGIN"):
        Settings(**settings_values)


@pytest.mark.parametrize("value", [Path("relative/cache"), Path("/missing-model-cache")])
def test_real_speech_validates_model_cache_root(
    settings_values: dict[str, Any],
    value: Path,
) -> None:
    settings_values.update(
        {
            "SERVICE_NAME": "worker",
            "SPEECH_MODE": "real",
            "HF_TOKEN": "hf_private_test_value",
            "MODEL_CACHE_ROOT": value,
        }
    )

    with pytest.raises(ValidationError, match="MODEL_CACHE_ROOT"):
        Settings(**settings_values)


def test_real_speech_rejects_model_cache_overlapping_results(
    settings_values: dict[str, Any],
) -> None:
    settings_values.update(
        {
            "SERVICE_NAME": "worker",
            "SPEECH_MODE": "real",
            "HF_TOKEN": "hf_private_test_value",
            "MODEL_CACHE_ROOT": settings_values["TRANSCRIPT_ROOT"],
        }
    )

    with pytest.raises(ValidationError, match="MODEL_CACHE_ROOT and TRANSCRIPT_ROOT"):
        Settings(**settings_values)


def test_real_speech_requires_writable_model_cache(
    settings_values: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache_root = Path(settings_values["MODEL_CACHE_ROOT"]).resolve()
    real_access = os.access

    def fake_access(path: str | os.PathLike[str], mode: int) -> bool:
        if Path(path).resolve() == cache_root and mode == os.W_OK | os.X_OK:
            return False
        return real_access(path, mode)

    monkeypatch.setattr(os, "access", fake_access)
    settings_values.update(
        {
            "SERVICE_NAME": "worker",
            "SPEECH_MODE": "real",
            "HF_TOKEN": "hf_private_test_value",
        }
    )

    with pytest.raises(ValidationError, match="MODEL_CACHE_ROOT is not writable"):
        Settings(**settings_values)


def test_real_document_requires_llm_variable_names(settings_values: dict[str, Any]) -> None:
    settings_values["DOCUMENT_MODE"] = "real"

    with pytest.raises(ValidationError) as error:
        Settings(**settings_values)

    message = str(error.value)
    assert "LLM_API_KEY" in message
    assert "LLM_MODEL" in message


def test_legacy_ai_mode_remains_compatible(
    settings_values: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings_values.pop("SPEECH_MODE")
    settings_values.pop("DOCUMENT_MODE")
    settings_values.update(
        {
            "AI_MODE": "real",
            "HF_TOKEN": "hf_private_test_value",
            "LLM_PROVIDER": "openai_compatible",
            "LLM_BASE_URL": "https://example.invalid/v1",
            "LLM_API_KEY": "sk-private-test-value",
            "LLM_MODEL": "test-model",
        }
    )

    monkeypatch.chdir(tmp_path)
    settings = Settings(**settings_values)

    assert settings.uses_legacy_ai_mode
    assert settings.effective_speech_mode == "real"
    assert settings.effective_document_mode == "real"


def test_secret_values_are_masked(settings_values: dict[str, Any]) -> None:
    settings_values.update(
        {
            "SPEECH_MODE": "real",
            "DOCUMENT_MODE": "real",
            "HF_TOKEN": "hf_private_test_value",
            "LLM_PROVIDER": "openai_compatible",
            "LLM_BASE_URL": "https://example.invalid/v1",
            "LLM_API_KEY": "sk-private-test-value",
            "LLM_MODEL": "test-model",
        }
    )

    rendered = repr(Settings(**settings_values))
    assert "hf_private_test_value" not in rendered
    assert "sk-private-test-value" not in rendered
