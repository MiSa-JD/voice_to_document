from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from app.config import Settings
from pydantic import ValidationError


def test_valid_fake_settings(settings_values: dict[str, Any]) -> None:
    settings = Settings(**settings_values)

    assert settings.ai_mode == "fake"
    assert settings.categories == ("강의", "일상 대화", "회의", "게임 목록", "기타")
    assert settings.database_path == Path(settings_values["APP_DATA_DIR"]) / "app.db"
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

    with pytest.raises(ValidationError, match="SUMMARY_ROOT and APP_DATA_DIR must not overlap"):
        Settings(**settings_values)


def test_rejects_unknown_auto_summary_category(settings_values: dict[str, Any]) -> None:
    settings_values["CATEGORIES"] = "회의,기타"
    settings_values["AUTO_SUMMARY_CATEGORIES"] = "강의"

    with pytest.raises(ValidationError, match="AUTO_SUMMARY_CATEGORIES"):
        Settings(**settings_values)


def test_real_mode_requires_secret_variable_names(settings_values: dict[str, Any]) -> None:
    settings_values["AI_MODE"] = "real"

    with pytest.raises(ValidationError) as error:
        Settings(**settings_values)

    message = str(error.value)
    assert "HF_TOKEN" in message
    assert "LLM_API_KEY" in message
    assert "LLM_MODEL" in message


def test_secret_values_are_masked(settings_values: dict[str, Any]) -> None:
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

    rendered = repr(Settings(**settings_values))
    assert "hf_private_test_value" not in rendered
    assert "sk-private-test-value" not in rendered
