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


def _seed_sources(settings: Settings, marker: str = "a") -> tuple[str, str, list[str]]:
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
        path.write_bytes(f"fake-clean-clip-{marker}-{index}".encode())
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
                marker * 64,
                str(settings.recording_input_dir / "sample.m4a"),
                timestamp,
                timestamp,
            ),
        )
        connection.execute(
            """
            INSERT INTO persons(id, display_name, revision, created_at, updated_at)
            VALUES (?, ?, 1, ?, ?)
            """,
            (person_id, f"Person {marker}", timestamp, timestamp),
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
                          ?, 'manual', 2)
                """,
                (
                    segment_id,
                    recording_id,
                    index * 3000,
                    index * 3000 + 2000,
                    person_id,
                    f"Person {marker}",
                ),
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
    assert first.revision == second.revision == 2
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


class _NeverAdapter:
    def embed(self, _clip_path: Path) -> EmbeddingResult:
        raise AssertionError("embedding model must not load")


def _seed_unresolved(
    settings: Settings,
    marker: str,
    *,
    speaker_count: int = 1,
    clip_count: int = 2,
) -> str:
    migrate_database(settings.database_path)
    recording_id = str(uuid.uuid4())
    timestamp = utc_now()
    with connect(settings.database_path) as connection:
        connection.execute(
            """
            INSERT INTO recordings(
                id, content_sha256, source_path, original_name, size_bytes, duration_ms,
                status, needs_speaker_review, revision, created_at, updated_at
            ) VALUES (?, ?, ?, 'target.m4a', 1, 20000, 'SPEAKER_REVIEW', 1, 1, ?, ?)
            """,
            (
                recording_id,
                marker * 64,
                str(settings.recording_input_dir / "target.m4a"),
                timestamp,
                timestamp,
            ),
        )
        for speaker_index in range(speaker_count):
            speaker_id = f"SPEAKER_{speaker_index:02d}"
            connection.execute(
                """
                INSERT INTO recording_speakers(
                    recording_id, local_speaker_id, speaker_source, revision,
                    clip_status, created_at, updated_at
                ) VALUES (?, ?, 'unresolved', 1, 'ready', ?, ?)
                """,
                (recording_id, speaker_id, timestamp, timestamp),
            )
            for clip_index in range(clip_count):
                segment_id = str(uuid.uuid4())
                artifact_id = str(uuid.uuid4())
                relative_path = Path(recording_id) / speaker_id / f"{clip_index}.wav"
                path = settings.speaker_root / relative_path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(f"target-{marker}-{speaker_id}-{clip_index}".encode())
                start_ms = speaker_index * 6000 + clip_index * 2500
                connection.execute(
                    """
                    INSERT INTO segments(
                        id, recording_id, start_ms, end_ms, text, local_speaker_id,
                        assignment_status, speaker_source, revision
                    ) VALUES (?, ?, ?, ?, 'private', ?, 'assigned', 'unresolved', 1)
                    """,
                    (segment_id, recording_id, start_ms, start_ms + 2000, speaker_id),
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
                        f"speaker_clip:{speaker_id}:{clip_index}",
                        str(relative_path),
                        f"{speaker_index}{clip_index}" * 32,
                        timestamp,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO speaker_clips(
                        id, recording_id, local_speaker_id, segment_id, artifact_id,
                        revision, clip_index, start_ms, end_ms, silence_ratio, created_at
                    ) VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, 0.0, ?)
                    """,
                    (
                        str(uuid.uuid4()),
                        recording_id,
                        speaker_id,
                        segment_id,
                        artifact_id,
                        clip_index,
                        start_ms,
                        start_ms + 2000,
                        timestamp,
                    ),
                )
    return recording_id


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


def test_candidate_scores_use_member_median_and_stable_ranking_without_auto_assignment(
    settings_values: dict[str, Any],
) -> None:
    settings = Settings(**settings_values)
    first_recording, first_person, _ = _seed_sources(settings, "a")
    second_recording, second_person, _ = _seed_sources(settings, "b")
    finalize_speaker_embeddings(settings, first_recording, _FixedAdapter("model:v1", 1.0))
    second_vector = tuple([0.8, 0.6] + [0.0] * (EMBEDDING_DIMENSION - 2))

    class SecondAdapter:
        def embed(self, _clip_path: Path) -> EmbeddingResult:
            return EmbeddingResult(vector=second_vector, model_fingerprint="model:v1")

    finalize_speaker_embeddings(settings, second_recording, SecondAdapter())
    target = _seed_unresolved(settings, "c")

    result = finalize_speaker_embeddings(settings, target, _FixedAdapter("model:v1"), 1)

    assert result.revision == 1
    assert result.auto_matched_speakers == ()
    with connect(settings.database_path) as connection:
        match = connection.execute(
            """
            SELECT decision, best_score, second_best_score, margin, input_revision
            FROM speaker_match_results WHERE recording_id = ?
            """,
            (target,),
        ).fetchone()
        candidates = connection.execute(
            """
            SELECT person_id, rank, score FROM speaker_match_candidates
            WHERE recording_id = ? ORDER BY rank
            """,
            (target,),
        ).fetchall()
        speaker = connection.execute(
            "SELECT person_id, speaker_source FROM recording_speakers WHERE recording_id = ?",
            (target,),
        ).fetchone()
    assert dict(match) == {
        "decision": "auto_disabled",
        "best_score": pytest.approx(1.0),
        "second_best_score": pytest.approx(0.8, abs=1e-6),
        "margin": pytest.approx(0.2, abs=1e-6),
        "input_revision": 1,
    }
    assert [row["person_id"] for row in candidates] == [first_person, second_person]
    assert [row["rank"] for row in candidates] == [1, 2]
    assert dict(speaker) == {"person_id": None, "speaker_source": "unresolved"}


def test_confident_match_updates_speaker_segments_audit_and_render_atomically(
    settings_values: dict[str, Any],
) -> None:
    settings_values.update(
        {
            "SPEAKER_AUTO_MATCH_ENABLED": True,
            "SPEAKER_AUTO_MATCH_THRESHOLD": 0.9,
            "SPEAKER_MATCH_MARGIN": 0.1,
        }
    )
    settings = Settings(**settings_values)
    profile_recording, person_id, _ = _seed_sources(settings, "a")
    finalize_speaker_embeddings(settings, profile_recording, _FixedAdapter("model:v1"))
    target = _seed_unresolved(settings, "b")

    result = finalize_speaker_embeddings(settings, target, _FixedAdapter("model:v1"), 1)

    assert result.revision == 2
    assert result.auto_matched_speakers == ("SPEAKER_00",)
    with connect(settings.database_path) as connection:
        recording = connection.execute(
            "SELECT revision, needs_speaker_review FROM recordings WHERE id = ?", (target,)
        ).fetchone()
        speaker = connection.execute(
            """
            SELECT person_id, speaker_source, speaker_score, revision
            FROM recording_speakers WHERE recording_id = ?
            """,
            (target,),
        ).fetchone()
        segments = connection.execute(
            """
            SELECT DISTINCT person_id, speaker_source, speaker_score, revision
            FROM segments WHERE recording_id = ?
            """,
            (target,),
        ).fetchall()
        event = connection.execute(
            "SELECT details_json FROM audit_events WHERE recording_id = ?", (target,)
        ).fetchone()
        render = connection.execute(
            "SELECT kind, input_revision FROM jobs WHERE recording_id = ?", (target,)
        ).fetchone()
    assert dict(recording) == {"revision": 2, "needs_speaker_review": 0}
    assert dict(speaker) == {
        "person_id": person_id,
        "speaker_source": "auto",
        "speaker_score": pytest.approx(1.0),
        "revision": 2,
    }
    assert [dict(row) for row in segments] == [
        {
            "person_id": person_id,
            "speaker_source": "auto",
            "speaker_score": pytest.approx(1.0),
            "revision": 2,
        }
    ]
    assert json.loads(event["details_json"])["local_speaker_ids"] == ["SPEAKER_00"]
    assert dict(render) == {"kind": "render", "input_revision": 2}


def test_missing_inputs_record_reasons_without_loading_model(
    settings_values: dict[str, Any],
) -> None:
    settings = Settings(**settings_values)
    no_clips = _seed_unresolved(settings, "a", clip_count=1)
    no_profiles = _seed_unresolved(settings, "b")

    finalize_speaker_embeddings(settings, no_clips, _NeverAdapter(), 1)
    finalize_speaker_embeddings(settings, no_profiles, _NeverAdapter(), 1)

    with connect(settings.database_path) as connection:
        decisions = {
            str(row["recording_id"]): str(row["decision"])
            for row in connection.execute(
                "SELECT recording_id, decision FROM speaker_match_results"
            ).fetchall()
        }
    assert decisions == {
        no_clips: "insufficient_clips",
        no_profiles: "no_profiles",
    }


def test_insufficient_profile_does_not_load_target_model(
    settings_values: dict[str, Any],
) -> None:
    settings = Settings(**settings_values)
    profile_recording, _person_id, segment_ids = _seed_sources(settings, "a")
    with connect(settings.database_path) as connection:
        connection.execute("UPDATE segments SET person_id = NULL WHERE id = ?", (segment_ids[1],))
    finalize_speaker_embeddings(settings, profile_recording, _FixedAdapter("model:v1"))
    target = _seed_unresolved(settings, "b")

    finalize_speaker_embeddings(settings, target, _NeverAdapter(), 1)

    with connect(settings.database_path) as connection:
        decision = connection.execute(
            "SELECT decision FROM speaker_match_results WHERE recording_id = ?", (target,)
        ).fetchone()[0]
    assert decision == "insufficient_profiles"


def test_equal_speakers_competing_for_one_person_are_both_left_for_review(
    settings_values: dict[str, Any],
) -> None:
    settings_values.update(
        {
            "SPEAKER_AUTO_MATCH_ENABLED": True,
            "SPEAKER_AUTO_MATCH_THRESHOLD": 0.9,
            "SPEAKER_MATCH_MARGIN": 0.1,
        }
    )
    settings = Settings(**settings_values)
    profile_recording, _person_id, _ = _seed_sources(settings, "a")
    finalize_speaker_embeddings(settings, profile_recording, _FixedAdapter("model:v1"))
    target = _seed_unresolved(settings, "b", speaker_count=2)

    result = finalize_speaker_embeddings(settings, target, _FixedAdapter("model:v1"), 1)

    assert result.revision == 1
    with connect(settings.database_path) as connection:
        decisions = connection.execute(
            """
            SELECT decision FROM speaker_match_results
            WHERE recording_id = ? ORDER BY local_speaker_id
            """,
            (target,),
        ).fetchall()
        sources = connection.execute(
            """
            SELECT speaker_source FROM recording_speakers
            WHERE recording_id = ? ORDER BY local_speaker_id
            """,
            (target,),
        ).fetchall()
    assert [row["decision"] for row in decisions] == ["duplicate_person", "duplicate_person"]
    assert [row["speaker_source"] for row in sources] == ["unresolved", "unresolved"]


def test_stale_finalization_does_not_replace_assignment_or_results(
    settings_values: dict[str, Any],
) -> None:
    settings = Settings(**settings_values)
    target = _seed_unresolved(settings, "a")
    with connect(settings.database_path) as connection:
        connection.execute("UPDATE recordings SET revision = 2 WHERE id = ?", (target,))

    result = finalize_speaker_embeddings(settings, target, _NeverAdapter(), 1)

    assert result.stale is True
    assert result.revision == 2
    with connect(settings.database_path) as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM speaker_match_results WHERE recording_id = ?", (target,)
        ).fetchone()[0]
    assert count == 0


def test_rejected_candidate_is_ranked_but_never_auto_matched(
    settings_values: dict[str, Any],
) -> None:
    settings_values.update(
        {
            "SPEAKER_AUTO_MATCH_ENABLED": True,
            "SPEAKER_AUTO_MATCH_THRESHOLD": 0.9,
            "SPEAKER_MATCH_MARGIN": 0.1,
        }
    )
    settings = Settings(**settings_values)
    profile_recording, person_id, _ = _seed_sources(settings, "a")
    finalize_speaker_embeddings(settings, profile_recording, _FixedAdapter("model:v1"))
    target = _seed_unresolved(settings, "b")
    with connect(settings.database_path) as connection:
        connection.execute(
            """
            INSERT INTO speaker_match_rejections(
                id, recording_id, local_speaker_id, person_id, model_fingerprint, created_at
            ) VALUES (?, ?, 'SPEAKER_00', ?, 'model:v1', ?)
            """,
            (str(uuid.uuid4()), target, person_id, utc_now()),
        )

    result = finalize_speaker_embeddings(settings, target, _FixedAdapter("model:v1"), 1)

    assert result.revision == 1
    with connect(settings.database_path) as connection:
        match = connection.execute(
            """
            SELECT results.decision, candidates.rejected
            FROM speaker_match_results AS results
            JOIN speaker_match_candidates AS candidates
              ON candidates.recording_id = results.recording_id
             AND candidates.local_speaker_id = results.local_speaker_id
            WHERE results.recording_id = ? AND candidates.rank = 1
            """,
            (target,),
        ).fetchone()
    assert dict(match) == {"decision": "rejected_candidate", "rejected": 1}


def test_threshold_margin_and_existing_person_fail_closed(
    settings_values: dict[str, Any],
) -> None:
    settings_values.update(
        {
            "SPEAKER_AUTO_MATCH_ENABLED": True,
            "SPEAKER_AUTO_MATCH_THRESHOLD": 0.9,
            "SPEAKER_MATCH_MARGIN": 0.1,
        }
    )
    settings = Settings(**settings_values)
    first_recording, first_person, _ = _seed_sources(settings, "a")
    finalize_speaker_embeddings(settings, first_recording, _FixedAdapter("model:v1"))

    class VectorAdapter:
        def __init__(self, left: float, right: float) -> None:
            self.vector = tuple([left, right] + [0.0] * (EMBEDDING_DIMENSION - 2))

        def embed(self, _clip_path: Path) -> EmbeddingResult:
            return EmbeddingResult(vector=self.vector, model_fingerprint="model:v1")

    below = _seed_unresolved(settings, "b")
    finalize_speaker_embeddings(settings, below, VectorAdapter(0.8, 0.6), 1)

    second_recording, _second_person, _ = _seed_sources(settings, "c")
    finalize_speaker_embeddings(settings, second_recording, VectorAdapter(0.95, 0.3122499))
    margin = _seed_unresolved(settings, "d")
    finalize_speaker_embeddings(settings, margin, _FixedAdapter("model:v1"), 1)

    duplicate = _seed_unresolved(settings, "e")
    with connect(settings.database_path) as connection:
        connection.execute(
            """
            INSERT INTO recording_speakers(
                recording_id, local_speaker_id, person_id, speaker_source,
                revision, created_at, updated_at
            ) VALUES (?, 'SPEAKER_99', ?, 'manual', 1, ?, ?)
            """,
            (duplicate, first_person, utc_now(), utc_now()),
        )
    finalize_speaker_embeddings(settings, duplicate, _FixedAdapter("model:v1"), 1)

    with connect(settings.database_path) as connection:
        decisions = {
            str(row["recording_id"]): str(row["decision"])
            for row in connection.execute(
                """
                SELECT recording_id, decision FROM speaker_match_results
                WHERE recording_id IN (?, ?, ?) AND local_speaker_id = 'SPEAKER_00'
                """,
                (below, margin, duplicate),
            ).fetchall()
        }
    assert decisions == {
        below: "below_threshold",
        margin: "insufficient_margin",
        duplicate: "duplicate_person",
    }
