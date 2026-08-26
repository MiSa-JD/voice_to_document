from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest


@pytest.fixture
def settings_values(tmp_path: Path) -> dict[str, Any]:
    names = ["inbox", "transcripts", "speakers", "documents", "app", "model-cache"]
    paths = {name: tmp_path / name for name in names}
    for path in paths.values():
        path.mkdir()
    return {
        "RECORDING_INPUT_DIR": paths["inbox"],
        "TRANSCRIPT_ROOT": paths["transcripts"],
        "SPEAKER_ROOT": paths["speakers"],
        "SUMMARY_ROOT": paths["documents"],
        "APP_DATA_DIR": paths["app"],
        "MODEL_CACHE_ROOT": paths["model-cache"],
        "SPEECH_MODE": "fake",
        "DOCUMENT_MODE": "fake",
        "HF_TOKEN": "",
        "LLM_PROVIDER": "",
        "LLM_BASE_URL": "",
        "LLM_API_KEY": "",
        "LLM_MODEL": "",
        "APP_BIND_HOST": "0.0.0.0",
        "APP_PORT": 38000,
    }
