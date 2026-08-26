from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any

from app.api import create_app
from app.config import Settings

SCHEMA_PATH = Path("openapi.json")


def schema_text() -> str:
    with tempfile.TemporaryDirectory(prefix="voice-to-document-openapi-") as directory:
        root = Path(directory)
        paths = {
            name: root / name for name in ("inbox", "transcripts", "speakers", "documents", "app")
        }
        for path in paths.values():
            path.mkdir()
        settings = Settings.model_validate(
            {
                "RECORDING_INPUT_DIR": paths["inbox"],
                "TRANSCRIPT_ROOT": paths["transcripts"],
                "SPEAKER_ROOT": paths["speakers"],
                "SUMMARY_ROOT": paths["documents"],
                "APP_DATA_DIR": paths["app"],
                "SPEECH_MODE": "fake",
                "DOCUMENT_MODE": "fake",
                "SERVICE_NAME": "test",
            }
        )
        schema: dict[str, Any] = create_app(settings).openapi()
    return json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    rendered = schema_text()
    if arguments.write:
        SCHEMA_PATH.write_text(rendered, encoding="utf-8")
        return
    if not SCHEMA_PATH.is_file() or SCHEMA_PATH.read_text(encoding="utf-8") != rendered:
        raise SystemExit("OpenAPI snapshot differs; run `make api-schema`.")


if __name__ == "__main__":
    main()
