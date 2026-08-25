from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from app.schema import Classification, MeetingSummary, Segment, Transcript


class FakeFixtureNotFoundError(ValueError):
    pass


class FakeAdapters:
    def __init__(self, fixture_root: Path | None = None) -> None:
        self.fixture_root = fixture_root or Path(__file__).parents[1] / "tests" / "fixtures"
        manifest = self._read_json(self.fixture_root / "manifest.json")
        if manifest.get("schema_version") != 1 or not isinstance(manifest.get("fixtures"), dict):
            raise ValueError("unsupported fake fixture manifest")
        self.fixtures: dict[str, Any] = manifest["fixtures"]

    def transcribe(
        self,
        recording_id: str,
        content_sha256: str,
        revision: int,
    ) -> Transcript:
        expected = self._expected(content_sha256)
        raw_segments = expected.get("segments")
        if not isinstance(raw_segments, list):
            raise ValueError("fake speech fixture has no segments")
        namespace = uuid.UUID(recording_id)
        segments = [
            Segment.model_validate(
                {
                    **raw,
                    "id": uuid.uuid5(namespace, f"segment:{index}"),
                }
            )
            for index, raw in enumerate(raw_segments)
        ]
        return Transcript(
            recording_id=namespace,
            content_sha256=content_sha256,
            revision=revision,
            language=str(expected["language"]),
            needs_speaker_review=bool(expected["needs_speaker_review"]),
            segments=segments,
        )

    def classify(self, content_sha256: str) -> Classification:
        value = self._expected(content_sha256).get("classification")
        if value is None:
            raise ValueError("fake document fixture has no classification")
        return Classification.model_validate(value)

    def summarize(self, content_sha256: str) -> MeetingSummary:
        value = self._expected(content_sha256).get("summary")
        if value is None:
            raise ValueError("fake document fixture has no summary")
        return MeetingSummary.model_validate(value)

    def _expected(self, content_sha256: str) -> dict[str, Any]:
        fixture = self.fixtures.get(content_sha256)
        if not isinstance(fixture, dict):
            raise FakeFixtureNotFoundError(f"no fake fixture for SHA-256 {content_sha256}")
        relative_path = fixture.get("expected")
        if not isinstance(relative_path, str):
            raise ValueError("fake fixture has no expected result path")
        path = (self.fixture_root / relative_path).resolve()
        if not path.is_relative_to(self.fixture_root.resolve()):
            raise ValueError("fake fixture path leaves fixture root")
        return self._read_json(path)

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError(f"expected a JSON object in {path.name}")
        return value
