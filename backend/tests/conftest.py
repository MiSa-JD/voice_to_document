from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest


@pytest.fixture
def settings_values(tmp_path: Path) -> dict[str, Any]:
    names = ["inbox", "transcripts", "speakers", "documents", "app"]
    paths = {name: tmp_path / name for name in names}
    for path in paths.values():
        path.mkdir()
    return {
        "RECORDING_INPUT_DIR": paths["inbox"],
        "TRANSCRIPT_ROOT": paths["transcripts"],
        "SPEAKER_ROOT": paths["speakers"],
        "SUMMARY_ROOT": paths["documents"],
        "APP_DATA_DIR": paths["app"],
        "AI_MODE": "fake",
    }
