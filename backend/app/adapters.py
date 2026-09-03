from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from app.schema import (
    CategorySummary,
    Classification,
    Segment,
    Transcript,
    validate_summary_evidence,
)


class FakeFixtureNotFoundError(ValueError):
    pass


class FakeAdapters:
    def __init__(self, fixture_root: Path | None = None) -> None:
        self.fixture_root = fixture_root or Path(__file__).parents[1] / "tests" / "fixtures"
        manifest = self._read_json(self.fixture_root / "manifest.json")
        if manifest.get("schema_version") != 1 or not isinstance(manifest.get("fixtures"), dict):
            raise ValueError("unsupported fake fixture manifest")
        self.fixtures: dict[str, Any] = manifest["fixtures"]
        self.last_transcription_options: dict[str, str | None] = {}

    def transcribe(
        self,
        recording_id: str,
        content_sha256: str,
        revision: int,
        *,
        language: str | None = None,
        initial_prompt: str | None = None,
    ) -> Transcript:
        self.last_transcription_options = {
            "language": language,
            "initial_prompt": initial_prompt,
        }
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
            language=language or str(expected["language"]),
            needs_speaker_review=bool(expected["needs_speaker_review"]),
            segments=segments,
        )

    def classify(self, content_sha256: str) -> Classification:
        value = self.classification_response(content_sha256)
        return Classification.model_validate(value)

    def classification_response(self, content_sha256: str) -> object:
        value = self._expected(content_sha256).get("classification")
        if value is None:
            raise ValueError("fake document fixture has no classification")
        return value

    @property
    def fingerprint(self) -> dict[str, object]:
        return {"provider": "fake", "model": "fixture-summary-v2"}

    def summarize(self, transcript: Transcript, category: str) -> CategorySummary:
        value = self._expected(transcript.content_sha256).get("summary")
        if value is None:
            raise ValueError("fake document fixture has no summary")
        summary: CategorySummary = TypeAdapter(CategorySummary).validate_python(value)
        by_time = {(item.start_ms, item.end_ms): item.id for item in transcript.segments}
        payload = summary.model_dump(mode="json")
        for item in _evidence_values(payload):
            segment_id = by_time.get((int(str(item["start_ms"])), int(str(item["end_ms"]))))
            if segment_id is None:
                raise ValueError("fake summary evidence does not match transcript")
            item["segment_id"] = str(segment_id)
        result: CategorySummary = TypeAdapter(CategorySummary).validate_python(payload)
        validate_summary_evidence(result, transcript)
        return result

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


def _evidence_values(value: object) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "evidence" and isinstance(item, list):
                results.extend(entry for entry in item if isinstance(entry, dict))
            else:
                results.extend(_evidence_values(item))
    elif isinstance(value, list):
        for item in value:
            results.extend(_evidence_values(item))
    return results
