from __future__ import annotations

import json
import math
import uuid
from pathlib import Path
from typing import Any

import pytest
from app.config import Settings
from app.db import connect, migrate_database, utc_now
from app.speaker_embeddings import (
    EMBEDDING_DIMENSION,
    EmbeddingResult,
    FakeSpeakerEmbeddingAdapter,
    PyannoteSpeakerEmbeddingAdapter,
    SpeakerEmbeddingError,
    finalize_speaker_embeddings,
    invalidate_embeddings,
    rebuild_person_profiles,
)


def _seed_sources(settings: Settings) -> tuple[str, str, list[str]]:
    migrate_database(settings.database_path)
    recording_id = str(uuid.uuid4())
    person_id = str(uuid.uuid4())
    segment_ids = [str(uuid.uuid4()), str(uuid.uuid4())]
    timestamp = utc_now()
    relative_paths = [
        Path(recording_id) / "SPEAKER_00" / "0.wav",
        Path(recording_id) / "SPEAKER_00" / "1.wav",
    ]
    for index, relative_path in enumerate(relative_paths):
        path = settings.speaker_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"fake-clean-clip-{index}".encode())
    with connect(settings.database_path) as connection:
        connection.execute(
            """
            INSERT INTO recordings(
                id, content_sha256, source_path, original_name, size_bytes, duration_ms,
                status, revision, created_at, updated_at
            ) VALUES (?, ?, ?, 'sample.m4a', 1, 10000, 'SPEAKER_REVIEW', 2, ?, ?)
            """,
            (
                recording_id,
                "a" * 64,
                str(settings.recording_input_dir / "sample.m4a"),
                timestamp,
                timestamp,
            ),
        )
        connection.execute(
            """
            INSERT INTO persons(id, display_name, revision, created_at, updated_at)
            VALUES (?, 'Person', 1, ?, ?)
            """,
            (person_id, timestamp, timestamp),
        )
        connection.execute(
            """
            INSERT INTO recording_speakers(
                recording_id, local_speaker_id, person_id, speaker_source, revision,
                clip_status, created_at, updated_at
            ) VALUES (?, 'SPEAKER_00', ?, 'manual', 2, 'ready', ?, ?)
            """,
            (recording_id, person_id, timestamp, timestamp),
        )
        for index, segment_id in enumerate(segment_ids):
            artifact_id = str(uuid.uuid4())
            connection.execute(
                """
                INSERT INTO segments(
                    id, recording_id, start_ms, end_ms, text, local_speaker_id,
                    assignment_status, person_id, speaker_name, speaker_source, revision
                ) VALUES (?, ?, ?, ?, 'private', 'SPEAKER_00', 'assigned', ?,
                          'Person', 'manual', 2)
                """,
                (segment_id, recording_id, index * 3000, index * 3000 + 2000, person_id),
            )
            connection.execute(
                """
                INSERT INTO artifacts(
                    id, recording_id, kind, relative_path, content_sha256,
                    schema_version, revision, created_at
                ) VALUES (?, ?, ?, ?, ?, 1, 1, ?)
                """,
                (
                    artifact_id,
                    recording_id,
                    f"speaker_clip:SPEAKER_00:{index}",
                    str(relative_paths[index]),
                    str(index) * 64,
                    timestamp,
                ),
            )
            connection.execute(
                """
                INSERT INTO speaker_clips(
                    id, recording_id, local_speaker_id, segment_id, artifact_id,
                    revision, clip_index, start_ms, end_ms, silence_ratio, created_at
                ) VALUES (?, ?, 'SPEAKER_00', ?, ?, 1, ?, ?, ?, 0.0, ?)
                """,
                (
                    str(uuid.uuid4()),
                    recording_id,
                    segment_id,
                    artifact_id,
                    index,
                    index * 3000,
                    index * 3000 + 2000,
                    timestamp,
                ),
            )
    return recording_id, person_id, segment_ids


def test_manual_clean_clips_create_versioned_normalized_vectors(
    settings_values: dict[str, Any],
) -> None:
    settings = Settings(**settings_values)
    recording_id, person_id, _segment_ids = _seed_sources(settings)

    first = finalize_speaker_embeddings(settings, recording_id, FakeSpeakerEmbeddingAdapter())
    second = finalize_speaker_embeddings(settings, recording_id, FakeSpeakerEmbeddingAdapter())

    assert first == second
    assert len(first) == 2
    with connect(settings.database_path) as connection:
        rows = connection.execute(
            """
            SELECT se.person_id, se.model_fingerprint, se.vector_store, se.collection_name,
                   vec_length(sv.embedding) AS dimension,
                   vec_distance_cosine(sv.embedding, sv.embedding) AS self_distance
            FROM speaker_embeddings AS se
            JOIN speaker_vector_keys AS keys ON keys.vector_key = se.vector_key
            JOIN speaker_vectors AS sv ON sv.vector_id = keys.id
            ORDER BY se.id
            """
        ).fetchall()
    assert len(rows) == 2
    assert {str(row["person_id"]) for row in rows} == {person_id}
    assert {int(row["dimension"]) for row in rows} == {EMBEDDING_DIMENSION}
    assert all(math.isclose(float(row["self_distance"]), 0.0, abs_tol=1e-6) for row in rows)
    fingerprint = json.loads(str(rows[0]["model_fingerprint"]))
    assert fingerprint["preprocessing"] == "mono-pcm-s16le-16khz-v1"
    assert fingerprint["dimension"] == EMBEDDING_DIMENSION
    assert rows[0]["vector_store"] == "sqlite-vec:0.1.9"
    assert rows[0]["collection_name"] == "speaker_vectors_v1"


class _FixedAdapter:
    def __init__(self, fingerprint: str, value: float = 1.0) -> None:
        self.fingerprint = fingerprint
        self.value = value

    def embed(self, _clip_path: Path) -> EmbeddingResult:
        return EmbeddingResult(
            vector=tuple([self.value] + [0.0] * (EMBEDDING_DIMENSION - 1)),
            model_fingerprint=self.fingerprint,
        )


def test_incompatible_fingerprints_are_stored_separately(
    settings_values: dict[str, Any],
) -> None:
    settings = Settings(**settings_values)
    recording_id, _person_id, _segment_ids = _seed_sources(settings)

    finalize_speaker_embeddings(settings, recording_id, _FixedAdapter("model:a"))
    finalize_speaker_embeddings(settings, recording_id, _FixedAdapter("model:b"))

    with connect(settings.database_path) as connection:
        counts = connection.execute(
            """
            SELECT model_fingerprint, COUNT(*) AS count
            FROM speaker_embeddings GROUP BY model_fingerprint ORDER BY model_fingerprint
            """
        ).fetchall()
    assert [(row["model_fingerprint"], row["count"]) for row in counts] == [
        ("model:a", 2),
        ("model:b", 2),
    ]
    with connect(settings.database_path) as connection:
        profiles = connection.execute(
            """
            SELECT model_fingerprint, status, sample_count
            FROM speaker_profiles ORDER BY model_fingerprint
            """
        ).fetchall()
    assert [tuple(row) for row in profiles] == [
        ("model:a", "eligible", 2),
        ("model:b", "eligible", 2),
    ]


def test_reassignment_invalidation_removes_vectors_but_keeps_audit_metadata(
    settings_values: dict[str, Any],
) -> None:
    settings = Settings(**settings_values)
    recording_id, person_id, segment_ids = _seed_sources(settings)
    finalize_speaker_embeddings(settings, recording_id, FakeSpeakerEmbeddingAdapter())

    with connect(settings.database_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        affected = invalidate_embeddings(connection, recording_id, [segment_ids[0]])
        connection.commit()
        statuses = connection.execute(
            "SELECT status, invalidated_at FROM speaker_embeddings ORDER BY segment_id"
        ).fetchall()
        vector_count = connection.execute("SELECT COUNT(*) FROM speaker_vectors").fetchone()[0]

    assert affected == {person_id}
    assert [row["status"] for row in statuses].count("invalidated") == 1
    assert all(
        row["invalidated_at"] is not None for row in statuses if row["status"] == "invalidated"
    )
    assert vector_count == 1
    with connect(settings.database_path) as connection:
        profile = connection.execute(
            "SELECT status, sample_count, vector_key FROM speaker_profiles"
        ).fetchone()
        member_count = connection.execute(
            "SELECT COUNT(*) FROM speaker_profile_members"
        ).fetchone()[0]
    assert dict(profile) == {
        "status": "insufficient",
        "sample_count": 0,
        "vector_key": None,
    }
    assert member_count == 0

    rebuild_person_profiles(settings.database_path, {person_id})
    with connect(settings.database_path) as connection:
        rebuilt = connection.execute(
            "SELECT status, sample_count, recording_count, vector_key FROM speaker_profiles"
        ).fetchone()
        rebuilt_members = connection.execute(
            "SELECT COUNT(*) FROM speaker_profile_members"
        ).fetchone()[0]
    assert dict(rebuilt) == {
        "status": "insufficient",
        "sample_count": 1,
        "recording_count": 1,
        "vector_key": None,
    }
    assert rebuilt_members == 1


def test_invalid_vector_is_rejected(settings_values: dict[str, Any]) -> None:
    settings = Settings(**settings_values)
    recording_id, _person_id, _segment_ids = _seed_sources(settings)

    with pytest.raises(SpeakerEmbeddingError, match="invalid values"):
        finalize_speaker_embeddings(
            settings,
            recording_id,
            _FixedAdapter("model:bad", value=float("nan")),
        )


def test_gated_embedding_model_is_a_non_retryable_access_error(
    settings_values: dict[str, Any],
) -> None:
    settings = Settings(**settings_values)

    def denied_runtime() -> tuple[Any, Any, Any]:
        raise PermissionError("403 gated repo access denied")

    adapter = PyannoteSpeakerEmbeddingAdapter(
        model="pyannote/embedding",
        revision="main",
        device="cuda",
        model_cache_root=settings.model_cache_root,
        hf_token=None,
        runtime_loader=denied_runtime,
    )

    with pytest.raises(SpeakerEmbeddingError) as captured:
        adapter._get_inference()
    assert captured.value.code == "MODEL_ACCESS_DENIED"


def test_profile_aggregates_members_and_persists_normalized_centroid(
    settings_values: dict[str, Any],
) -> None:
    settings = Settings(**settings_values)
    recording_id, person_id, _segment_ids = _seed_sources(settings)

    finalize_speaker_embeddings(settings, recording_id, FakeSpeakerEmbeddingAdapter())

    with connect(settings.database_path) as connection:
        profile = connection.execute(
            """
            SELECT sp.person_id, sp.status, sp.sample_count, sp.recording_count,
                   vec_length(sv.embedding) AS dimension,
                   vec_distance_cosine(sv.embedding, sv.embedding) AS self_distance
            FROM speaker_profiles AS sp
            JOIN speaker_vector_keys AS keys ON keys.vector_key = sp.vector_key
            JOIN speaker_vectors AS sv ON sv.vector_id = keys.id
            """
        ).fetchone()
        members = connection.execute("SELECT COUNT(*) FROM speaker_profile_members").fetchone()[0]

    assert dict(profile) == {
        "person_id": person_id,
        "status": "eligible",
        "sample_count": 2,
        "recording_count": 1,
        "dimension": EMBEDDING_DIMENSION,
        "self_distance": pytest.approx(0.0, abs=1e-6),
    }
    assert members == 2


def test_one_clean_sample_keeps_profile_ineligible(settings_values: dict[str, Any]) -> None:
    settings = Settings(**settings_values)
    recording_id, person_id, segment_ids = _seed_sources(settings)
    with connect(settings.database_path) as connection:
        connection.execute("UPDATE segments SET person_id = NULL WHERE id = ?", (segment_ids[1],))

    finalize_speaker_embeddings(settings, recording_id, FakeSpeakerEmbeddingAdapter())

    with connect(settings.database_path) as connection:
        profile = connection.execute(
            """
            SELECT person_id, status, sample_count, recording_count, vector_key
            FROM speaker_profiles
            """
        ).fetchone()
        vector_count = connection.execute("SELECT COUNT(*) FROM speaker_vectors").fetchone()[0]
    assert dict(profile) == {
        "person_id": person_id,
        "status": "insufficient",
        "sample_count": 1,
        "recording_count": 1,
        "vector_key": None,
    }
    assert vector_count == 1
