from __future__ import annotations

import os
from pathlib import Path
from typing import Literal, Self

from pydantic import AliasChoices, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    recording_input_dir: Path = Field(validation_alias="RECORDING_INPUT_DIR")
    transcript_root: Path = Field(validation_alias="TRANSCRIPT_ROOT")
    speaker_root: Path = Field(validation_alias="SPEAKER_ROOT")
    summary_root: Path = Field(validation_alias="SUMMARY_ROOT")
    app_data_dir: Path = Field(validation_alias="APP_DATA_DIR")

    scan_interval_seconds: float = Field(default=10, gt=0, validation_alias="SCAN_INTERVAL_SECONDS")
    file_stable_seconds: float = Field(default=30, gt=0, validation_alias="FILE_STABLE_SECONDS")
    categories_csv: str = Field(
        default="강의,일상 대화,회의,게임 목록,기타",
        validation_alias="CATEGORIES",
    )
    auto_summary_categories_csv: str = Field(
        default="강의,회의",
        validation_alias="AUTO_SUMMARY_CATEGORIES",
    )

    ai_mode: Literal["fake", "real"] | None = Field(
        default=None,
        validation_alias="AI_MODE",
        exclude=True,
    )
    speech_mode: Literal["fake", "real"] | None = Field(
        default=None,
        validation_alias="SPEECH_MODE",
    )
    document_mode: Literal["fake", "real"] | None = Field(
        default=None,
        validation_alias="DOCUMENT_MODE",
    )
    whisper_model: str = Field(default="large-v3", validation_alias="WHISPER_MODEL")
    whisper_device: str = Field(default="cuda", validation_alias="WHISPER_DEVICE")
    whisper_compute_type: str = Field(default="float16", validation_alias="WHISPER_COMPUTE_TYPE")
    whisper_language: str | None = Field(default=None, validation_alias="WHISPER_LANGUAGE")
    hf_token: SecretStr | None = Field(default=None, validation_alias="HF_TOKEN")

    llm_provider: str | None = Field(default=None, validation_alias="LLM_PROVIDER")
    llm_base_url: str | None = Field(default=None, validation_alias="LLM_BASE_URL")
    llm_api_key: SecretStr | None = Field(default=None, validation_alias="LLM_API_KEY")
    llm_model: str | None = Field(default=None, validation_alias="LLM_MODEL")

    app_bind_host: str = Field(default="0.0.0.0", validation_alias="APP_BIND_HOST")
    app_port: int = Field(default=38000, ge=1, le=65535, validation_alias="APP_PORT")
    log_level: str = Field(
        default="INFO",
        validation_alias=AliasChoices("LOG_LEVEL", "UVICORN_LOG_LEVEL"),
    )
    service_name: Literal["api", "worker", "test"] = Field(
        default="api", validation_alias="SERVICE_NAME"
    )

    @property
    def categories(self) -> tuple[str, ...]:
        return _csv_values(self.categories_csv)

    @property
    def auto_summary_categories(self) -> tuple[str, ...]:
        return _csv_values(self.auto_summary_categories_csv)

    @property
    def database_path(self) -> Path:
        return self.app_data_dir / "app.db"

    @property
    def effective_speech_mode(self) -> Literal["fake", "real"]:
        return self.speech_mode or self.ai_mode or "fake"

    @property
    def effective_document_mode(self) -> Literal["fake", "real"]:
        return self.document_mode or self.ai_mode or "fake"

    @property
    def uses_legacy_ai_mode(self) -> bool:
        return self.ai_mode is not None and self.speech_mode is None and self.document_mode is None

    @model_validator(mode="after")
    def validate_environment(self) -> Self:
        roots = {
            "RECORDING_INPUT_DIR": self.recording_input_dir,
            "TRANSCRIPT_ROOT": self.transcript_root,
            "SPEAKER_ROOT": self.speaker_root,
            "SUMMARY_ROOT": self.summary_root,
            "APP_DATA_DIR": self.app_data_dir,
        }
        resolved: dict[str, Path] = {}
        for name, path in roots.items():
            if not path.is_absolute():
                raise ValueError(f"{name} must be an absolute path")
            try:
                root = path.resolve(strict=True)
            except FileNotFoundError as error:
                raise ValueError(f"{name} does not exist") from error
            if not root.is_dir():
                raise ValueError(f"{name} must be a directory")
            if not os.access(root, os.R_OK | os.X_OK):
                raise ValueError(f"{name} is not readable")
            resolved[name] = root

        writable_names = {"APP_DATA_DIR"}
        if self.service_name == "worker":
            writable_names.update({"TRANSCRIPT_ROOT", "SPEAKER_ROOT", "SUMMARY_ROOT"})
        for name in writable_names:
            if not os.access(resolved[name], os.W_OK):
                raise ValueError(f"{name} is not writable for {self.service_name}")

        pairs = list(resolved.items())
        for index, (left_name, left) in enumerate(pairs):
            for right_name, right in pairs[index + 1 :]:
                if left == right or left in right.parents or right in left.parents:
                    raise ValueError(f"{left_name} and {right_name} must not overlap")

        if not self.categories:
            raise ValueError("CATEGORIES must contain at least one category")
        unknown = set(self.auto_summary_categories) - set(self.categories)
        if unknown:
            raise ValueError(
                "AUTO_SUMMARY_CATEGORIES contains values not present in CATEGORIES: "
                + ", ".join(sorted(unknown))
            )

        if self.effective_speech_mode == "real" and not _has_value(self.hf_token):
            raise ValueError("real SPEECH_MODE requires: HF_TOKEN")

        if self.effective_document_mode == "real":
            required = {
                "LLM_PROVIDER": self.llm_provider,
                "LLM_BASE_URL": self.llm_base_url,
                "LLM_API_KEY": self.llm_api_key,
                "LLM_MODEL": self.llm_model,
            }
            missing = [name for name, value in required.items() if not _has_value(value)]
            if missing:
                raise ValueError("real DOCUMENT_MODE requires: " + ", ".join(missing))
        return self

    def public_summary(self) -> dict[str, object]:
        return {
            "speech_mode": self.effective_speech_mode,
            "document_mode": self.effective_document_mode,
            "whisper_model": self.whisper_model,
            "categories": self.categories,
            "auto_summary_categories": self.auto_summary_categories,
            "log_level": self.log_level,
        }


def _csv_values(value: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(part.strip() for part in value.split(",") if part.strip()))


def _has_value(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, SecretStr):
        return bool(value.get_secret_value())
    return bool(str(value).strip())
