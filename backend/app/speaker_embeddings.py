from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from importlib import import_module, metadata
from pathlib import Path
from statistics import median
from typing import Any, Protocol, cast

from pydantic import SecretStr

from app.config import Settings
from app.db import connect, migrate_database, utc_now
from app.speech_failures import is_model_access_denied, is_model_download_failure
from app.transcription import _is_out_of_memory

EMBEDDING_DIMENSION = 512
PREPROCESSING_VERSION = "mono-pcm-s16le-16khz-v1"
VECTOR_STORE = "sqlite-vec:0.1.9"
VECTOR_COLLECTION = "speaker_vectors_v1"


class SpeakerEmbeddingError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class EmbeddingResult:
    vector: tuple[float, ...]
    model_fingerprint: str


@dataclass(frozen=True)
class SpeakerFinalizationResult:
    revision: int
    auto_matched_speakers: tuple[str, ...] = ()
    stale: bool = False


@dataclass(frozen=True)
class _MatchCandidate:
    person_id: str
    profile_id: str
    score: float
    rejected: bool


@dataclass
class _MatchEvaluation:
    local_speaker_id: str
    model_fingerprint: str | None
    decision: str
    candidates: tuple[_MatchCandidate, ...] = ()

    @property
    def best_score(self) -> float:
        return self.candidates[0].score if self.candidates else 0.0

    @property
    def second_best_score(self) -> float:
        return self.candidates[1].score if len(self.candidates) > 1 else 0.0

    @property
    def margin(self) -> float:
        return max(0.0, min(1.0, self.best_score - self.second_best_score))


class SpeakerEmbeddingAdapter(Protocol):
    def embed(self, clip_path: Path) -> EmbeddingResult: ...


class FakeSpeakerEmbeddingAdapter:
    def embed(self, clip_path: Path) -> EmbeddingResult:
        digest = hashlib.sha256(clip_path.read_bytes()).digest()
        values = [((digest[index % len(digest)] / 255.0) * 2.0) - 1.0 for index in range(512)]
        return EmbeddingResult(
            vector=_normalized_vector(values),
            model_fingerprint=_fingerprint(
                model="fake-speaker-embedding",
                revision="v1",
                weights_sha256=hashlib.sha256(b"fake-speaker-embedding-v1").hexdigest(),
                pyannote_audio_version="fake",
            ),
        )


class PyannoteSpeakerEmbeddingAdapter:
    def __init__(
        self,
        *,
        model: str,
        revision: str,
        device: str,
        model_cache_root: Path,
        hf_token: SecretStr | None,
        runtime_loader: Callable[[], tuple[Any, Any, Any]] | None = None,
    ) -> None:
        self.model_name = model
        self.revision = revision
        self.device = device
        self.model_cache_root = model_cache_root
        self.hf_token = hf_token
        self.runtime_loader = runtime_loader or _load_pyannote_runtime
        self._inference: Any | None = None
        self._model_fingerprint: str | None = None

    def embed(self, clip_path: Path) -> EmbeddingResult:
        inference = self._get_inference()
        try:
            raw = inference(str(clip_path))
            values = cast(Any, raw).reshape(-1).tolist()
            vector = _normalized_vector(values)
        except SpeakerEmbeddingError:
            raise
        except Exception as error:
            if _is_out_of_memory(error):
                raise SpeakerEmbeddingError(
                    "MODEL_OOM", "speaker embedding ran out of GPU memory"
                ) from error
            raise SpeakerEmbeddingError(
                "SPEAKER_EMBEDDING_FAILED", "speaker embedding inference failed"
            ) from error
        assert self._model_fingerprint is not None
        return EmbeddingResult(vector=vector, model_fingerprint=self._model_fingerprint)

    def _get_inference(self) -> Any:
        if self._inference is not None:
            return self._inference
        try:
            model_class, inference_class, torch = self.runtime_loader()
            token = self.hf_token.get_secret_value() if self.hf_token is not None else None
            model = model_class.from_pretrained(
                self.model_name,
                revision=self.revision,
                token=token,
                cache_dir=str(self.model_cache_root),
            )
            weights_sha256 = _state_dict_sha256(model.state_dict())
            inference = inference_class(model, window="whole")
            inference.to(torch.device(self.device))
            version = metadata.version("pyannote.audio")
        except Exception as error:
            if _is_out_of_memory(error):
                raise SpeakerEmbeddingError(
                    "MODEL_OOM", "speaker embedding model ran out of GPU memory"
                ) from error
            if is_model_access_denied(error):
                raise SpeakerEmbeddingError(
                    "MODEL_ACCESS_DENIED",
                    "speaker embedding model access is not approved for the configured token",
                ) from error
            if is_model_download_failure(error):
                raise SpeakerEmbeddingError(
                    "MODEL_DOWNLOAD_FAILED", "speaker embedding model could not download"
                ) from error
            raise SpeakerEmbeddingError(
                "SPEAKER_EMBEDDING_MODEL_LOAD_FAILED", "speaker embedding model could not load"
            ) from error
        self._inference = inference
        self._model_fingerprint = _fingerprint(
            model=self.model_name,
            revision=self.revision,
            weights_sha256=weights_sha256,
            pyannote_audio_version=version,
        )
        return inference


def _load_pyannote_runtime() -> tuple[Any, Any, Any]:
    pyannote_audio = import_module("pyannote.audio")
    torch = import_module("torch")
    return pyannote_audio.Model, pyannote_audio.Inference, torch


def _state_dict_sha256(state_dict: Mapping[str, Any]) -> str:
    digest = hashlib.sha256()
    for name in sorted(state_dict):
        tensor = state_dict[name].detach().cpu().contiguous()
        digest.update(name.encode())
        digest.update(str(tensor.dtype).encode())
        digest.update(str(tuple(tensor.shape)).encode())
        digest.update(tensor.numpy().tobytes())
    return digest.hexdigest()


def _fingerprint(
    *, model: str, revision: str, weights_sha256: str, pyannote_audio_version: str
) -> str:
    return json.dumps(
        {
            "dimension": EMBEDDING_DIMENSION,
            "model": model,
            "preprocessing": PREPROCESSING_VERSION,
            "pyannote_audio": pyannote_audio_version,
            "revision": revision,
            "weights_sha256": weights_sha256,
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _normalized_vector(values: Sequence[float]) -> tuple[float, ...]:
    vector = tuple(float(value) for value in values)
    if len(vector) != EMBEDDING_DIMENSION or any(not math.isfinite(value) for value in vector):
        raise SpeakerEmbeddingError(
            "INVALID_SPEAKER_EMBEDDING", "speaker embedding has invalid values"
        )
    norm = math.sqrt(sum(value * value for value in vector))
    if not math.isfinite(norm) or norm <= 0:
        raise SpeakerEmbeddingError("INVALID_SPEAKER_EMBEDDING", "speaker embedding has zero norm")
    return tuple(value / norm for value in vector)


def finalize_speaker_embeddings(
    settings: Settings,
    recording_id: str,
    adapter: SpeakerEmbeddingAdapter,
    input_revision: int | None = None,
) -> SpeakerFinalizationResult:
    migrate_database(settings.database_path)
    current_revision = _current_recording_revision(settings.database_path, recording_id)
    expected_revision = input_revision or current_revision
    if current_revision != expected_revision:
        return SpeakerFinalizationResult(revision=current_revision, stale=True)
    candidates = _eligible_clips(settings.database_path, recording_id)
    for candidate in candidates:
        clip_path = _safe_clip_path(settings.speaker_root, str(candidate["relative_path"]))
        raw_result = adapter.embed(clip_path)
        if not raw_result.model_fingerprint.strip():
            raise SpeakerEmbeddingError(
                "INVALID_SPEAKER_EMBEDDING", "speaker embedding fingerprint is empty"
            )
        result = EmbeddingResult(
            vector=_normalized_vector(raw_result.vector),
            model_fingerprint=raw_result.model_fingerprint,
        )
        _register_embedding(settings.database_path, candidate, result)
    affected_person_ids = _recording_person_ids(settings.database_path, recording_id)
    rebuild_person_profiles(settings.database_path, affected_person_ids)
    evaluations = _evaluate_unresolved_speakers(
        settings,
        recording_id,
        expected_revision,
        adapter,
    )
    return _store_matches_and_apply(
        settings,
        recording_id,
        expected_revision,
        evaluations,
    )


def _current_recording_revision(database_path: Path, recording_id: str) -> int:
    with connect(database_path) as connection:
        row = connection.execute(
            "SELECT revision FROM recordings WHERE id = ?", (recording_id,)
        ).fetchone()
    if row is None:
        raise SpeakerEmbeddingError("RECORDING_NOT_FOUND", "recording is unavailable")
    return int(row["revision"])


def _evaluate_unresolved_speakers(
    settings: Settings,
    recording_id: str,
    input_revision: int,
    adapter: SpeakerEmbeddingAdapter,
) -> list[_MatchEvaluation]:
    with connect(settings.database_path) as connection:
        rows = connection.execute(
            """
            WITH latest AS (
                SELECT sc.*, ROW_NUMBER() OVER (
                    PARTITION BY sc.local_speaker_id, sc.clip_index
                    ORDER BY sc.revision DESC
                ) AS position
                FROM speaker_clips AS sc
                WHERE sc.recording_id = ?
            )
            SELECT rs.local_speaker_id, latest.clip_index, artifacts.relative_path
            FROM recording_speakers AS rs
            LEFT JOIN latest
              ON latest.local_speaker_id = rs.local_speaker_id AND latest.position = 1
            LEFT JOIN artifacts ON artifacts.id = latest.artifact_id
            WHERE rs.recording_id = ? AND rs.speaker_source = 'unresolved'
            ORDER BY rs.local_speaker_id, latest.clip_index
            """,
            (recording_id, recording_id),
        ).fetchall()
        profile_counts = connection.execute(
            """
            SELECT COUNT(*) AS total,
                   SUM(CASE WHEN status = 'eligible' THEN 1 ELSE 0 END) AS eligible
            FROM speaker_profiles
            """
        ).fetchone()
    paths: dict[str, list[str]] = {}
    for row in rows:
        speaker_id = str(row["local_speaker_id"])
        paths.setdefault(speaker_id, [])
        if row["relative_path"] is not None:
            paths[speaker_id].append(str(row["relative_path"]))

    total_profiles = int(profile_counts["total"] or 0)
    eligible_profiles = int(profile_counts["eligible"] or 0)
    evaluations: list[_MatchEvaluation] = []
    for speaker_id, relative_paths in paths.items():
        if len(relative_paths) < 2:
            evaluations.append(_MatchEvaluation(speaker_id, None, "insufficient_clips"))
            continue
        if total_profiles == 0:
            evaluations.append(_MatchEvaluation(speaker_id, None, "no_profiles"))
            continue
        if eligible_profiles == 0:
            evaluations.append(_MatchEvaluation(speaker_id, None, "insufficient_profiles"))
            continue
        if _current_recording_revision(settings.database_path, recording_id) != input_revision:
            return []
        embedded = [
            adapter.embed(_safe_clip_path(settings.speaker_root, relative_path))
            for relative_path in relative_paths
        ]
        fingerprints = {result.model_fingerprint for result in embedded}
        if len(fingerprints) != 1 or not next(iter(fingerprints), "").strip():
            raise SpeakerEmbeddingError(
                "INVALID_SPEAKER_EMBEDDING",
                "speaker match clips have inconsistent model fingerprints",
            )
        fingerprint = next(iter(fingerprints))
        clip_vectors = tuple(_normalized_vector(result.vector) for result in embedded)
        candidates = _profile_candidates(
            settings.database_path,
            recording_id,
            speaker_id,
            fingerprint,
            clip_vectors,
        )
        evaluations.append(
            _MatchEvaluation(
                speaker_id,
                fingerprint,
                "no_profiles" if not candidates else "auto_disabled",
                candidates,
            )
        )
    return evaluations


def _profile_candidates(
    database_path: Path,
    recording_id: str,
    local_speaker_id: str,
    model_fingerprint: str,
    clip_vectors: tuple[tuple[float, ...], ...],
) -> tuple[_MatchCandidate, ...]:
    with connect(database_path) as connection:
        rows = connection.execute(
            """
            SELECT sp.id AS profile_id, sp.person_id, sv.embedding
            FROM speaker_profiles AS sp
            JOIN speaker_profile_members AS members ON members.profile_id = sp.id
            JOIN speaker_embeddings AS se
              ON se.id = members.embedding_id AND se.status = 'active'
            JOIN speaker_vector_keys AS keys ON keys.vector_key = se.vector_key
            JOIN speaker_vectors AS sv ON sv.vector_id = keys.id
            WHERE sp.status = 'eligible' AND sp.model_fingerprint = ?
              AND se.model_fingerprint = sp.model_fingerprint
            ORDER BY sp.person_id, se.created_at, se.id
            """,
            (model_fingerprint,),
        ).fetchall()
        rejected_people = {
            str(row["person_id"])
            for row in connection.execute(
                """
                SELECT person_id FROM speaker_match_rejections
                WHERE recording_id = ? AND local_speaker_id = ? AND model_fingerprint = ?
                """,
                (recording_id, local_speaker_id, model_fingerprint),
            ).fetchall()
        }
    profiles: dict[tuple[str, str], list[tuple[float, ...]]] = {}
    for row in rows:
        key = (str(row["person_id"]), str(row["profile_id"]))
        profiles.setdefault(key, []).append(_float32_values(bytes(row["embedding"])))
    candidates = [
        _MatchCandidate(
            person_id=person_id,
            profile_id=profile_id,
            score=_median_similarity(clip_vectors, member_vectors),
            rejected=person_id in rejected_people,
        )
        for (person_id, profile_id), member_vectors in profiles.items()
    ]
    return tuple(sorted(candidates, key=lambda item: (-item.score, item.person_id)))


def _median_similarity(
    clip_vectors: Sequence[Sequence[float]],
    member_vectors: Sequence[Sequence[float]],
) -> float:
    similarities = [
        max(
            0.0,
            min(1.0, sum(left * right for left, right in zip(clip, member, strict=True))),
        )
        for clip in clip_vectors
        for member in member_vectors
    ]
    return float(median(similarities)) if similarities else 0.0


def _store_matches_and_apply(
    settings: Settings,
    recording_id: str,
    input_revision: int,
    evaluations: list[_MatchEvaluation],
) -> SpeakerFinalizationResult:
    with connect(settings.database_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        current = connection.execute(
            "SELECT revision FROM recordings WHERE id = ?", (recording_id,)
        ).fetchone()
        if current is None:
            raise SpeakerEmbeddingError("RECORDING_NOT_FOUND", "recording is unavailable")
        current_revision = int(current["revision"])
        if current_revision != input_revision:
            connection.commit()
            return SpeakerFinalizationResult(revision=current_revision, stale=True)

        unresolved = {
            str(row["local_speaker_id"])
            for row in connection.execute(
                """
                SELECT local_speaker_id FROM recording_speakers
                WHERE recording_id = ? AND speaker_source = 'unresolved'
                """,
                (recording_id,),
            ).fetchall()
        }
        evaluations = [item for item in evaluations if item.local_speaker_id in unresolved]
        _decide_auto_matches(connection, settings, recording_id, evaluations)
        timestamp = utc_now()
        for evaluation in evaluations:
            connection.execute(
                """
                INSERT INTO speaker_match_results(
                    recording_id, local_speaker_id, input_revision, model_fingerprint,
                    decision, best_score, second_best_score, margin, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(recording_id, local_speaker_id) DO UPDATE SET
                    input_revision = excluded.input_revision,
                    model_fingerprint = excluded.model_fingerprint,
                    decision = excluded.decision,
                    best_score = excluded.best_score,
                    second_best_score = excluded.second_best_score,
                    margin = excluded.margin,
                    updated_at = excluded.updated_at
                """,
                (
                    recording_id,
                    evaluation.local_speaker_id,
                    input_revision,
                    evaluation.model_fingerprint,
                    evaluation.decision,
                    evaluation.best_score,
                    evaluation.second_best_score,
                    evaluation.margin,
                    timestamp,
                ),
            )
            connection.execute(
                """
                DELETE FROM speaker_match_candidates
                WHERE recording_id = ? AND local_speaker_id = ?
                """,
                (recording_id, evaluation.local_speaker_id),
            )
            connection.executemany(
                """
                INSERT INTO speaker_match_candidates(
                    recording_id, local_speaker_id, person_id, profile_id,
                    rank, score, rejected
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        recording_id,
                        evaluation.local_speaker_id,
                        candidate.person_id,
                        candidate.profile_id,
                        rank,
                        candidate.score,
                        int(candidate.rejected),
                    )
                    for rank, candidate in enumerate(evaluation.candidates, start=1)
                ],
            )

        matched = [item for item in evaluations if item.decision == "auto_matched"]
        result_revision = input_revision
        if matched:
            result_revision += 1
            for evaluation in matched:
                best = evaluation.candidates[0]
                person = connection.execute(
                    "SELECT display_name FROM persons WHERE id = ?", (best.person_id,)
                ).fetchone()
                if person is None:
                    raise SpeakerEmbeddingError("PERSON_NOT_FOUND", "match person is unavailable")
                connection.execute(
                    """
                    UPDATE recording_speakers
                    SET person_id = ?, speaker_source = 'auto', speaker_score = ?,
                        revision = ?, updated_at = ?
                    WHERE recording_id = ? AND local_speaker_id = ?
                      AND speaker_source = 'unresolved'
                    """,
                    (
                        best.person_id,
                        best.score,
                        result_revision,
                        timestamp,
                        recording_id,
                        evaluation.local_speaker_id,
                    ),
                )
                connection.execute(
                    """
                    UPDATE segments
                    SET person_id = ?, speaker_name = ?, speaker_source = 'auto',
                        speaker_score = ?, revision = ?
                    WHERE recording_id = ? AND local_speaker_id = ?
                    """,
                    (
                        best.person_id,
                        str(person["display_name"]),
                        best.score,
                        result_revision,
                        recording_id,
                        evaluation.local_speaker_id,
                    ),
                )
            remaining = int(
                connection.execute(
                    """
                    SELECT COUNT(*) FROM recording_speakers
                    WHERE recording_id = ? AND speaker_source = 'unresolved'
                    """,
                    (recording_id,),
                ).fetchone()[0]
            )
            connection.execute(
                """
                UPDATE recordings
                SET revision = ?, needs_speaker_review = ?, updated_at = ?
                WHERE id = ?
                """,
                (result_revision, int(remaining > 0), timestamp, recording_id),
            )
            connection.execute(
                """
                INSERT INTO audit_events(id, recording_id, event_type, details_json, created_at)
                VALUES (?, ?, 'speaker_auto_matched', ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    recording_id,
                    json.dumps(
                        {
                            "local_speaker_ids": sorted(item.local_speaker_id for item in matched),
                            "previous_revision": input_revision,
                            "revision": result_revision,
                        },
                        sort_keys=True,
                    ),
                    timestamp,
                ),
            )
            connection.execute(
                """
                INSERT INTO jobs(
                    id, recording_id, kind, status, attempts, available_at,
                    created_at, updated_at, input_revision, settings_fingerprint
                ) VALUES (?, ?, 'render', 'queued', 0, ?, ?, ?, ?, 'speaker-auto-match-v1')
                """,
                (
                    str(uuid.uuid4()),
                    recording_id,
                    timestamp,
                    timestamp,
                    timestamp,
                    result_revision,
                ),
            )
        connection.commit()
    return SpeakerFinalizationResult(
        revision=result_revision,
        auto_matched_speakers=tuple(sorted(item.local_speaker_id for item in matched)),
    )


def _decide_auto_matches(
    connection: sqlite3.Connection,
    settings: Settings,
    recording_id: str,
    evaluations: list[_MatchEvaluation],
) -> None:
    used_people = {
        str(row["person_id"])
        for row in connection.execute(
            """
            SELECT person_id FROM recording_speakers
            WHERE recording_id = ? AND person_id IS NOT NULL
              AND speaker_source IN ('manual', 'auto')
            """,
            (recording_id,),
        ).fetchall()
    }
    threshold = settings.speaker_auto_match_threshold
    required_margin = settings.speaker_match_margin
    for evaluation in evaluations:
        if not evaluation.candidates:
            continue
        best = evaluation.candidates[0]
        if best.rejected:
            evaluation.decision = "rejected_candidate"
        elif best.person_id in used_people:
            evaluation.decision = "duplicate_person"
        elif not settings.speaker_auto_match_enabled:
            evaluation.decision = "auto_disabled"
        elif evaluation.best_score < cast(float, threshold):
            evaluation.decision = "below_threshold"
        elif evaluation.margin < cast(float, required_margin):
            evaluation.decision = "insufficient_margin"
        else:
            evaluation.decision = "auto_matched"

    contenders: dict[str, list[_MatchEvaluation]] = {}
    for evaluation in evaluations:
        if evaluation.decision == "auto_matched":
            contenders.setdefault(evaluation.candidates[0].person_id, []).append(evaluation)
    for conflicts in contenders.values():
        if len(conflicts) < 2:
            continue
        highest = max(item.best_score for item in conflicts)
        winners = [item for item in conflicts if item.best_score == highest]
        for evaluation in conflicts:
            if len(winners) != 1 or evaluation is not winners[0]:
                evaluation.decision = "duplicate_person"


def _recording_person_ids(database_path: Path, recording_id: str) -> set[str]:
    with connect(database_path) as connection:
        rows = connection.execute(
            """
            SELECT person_id FROM speaker_embeddings WHERE recording_id = ?
            UNION
            SELECT person_id FROM recording_speakers
            WHERE recording_id = ? AND person_id IS NOT NULL
            """,
            (recording_id, recording_id),
        ).fetchall()
    return {str(row["person_id"]) for row in rows if row["person_id"] is not None}


def _eligible_clips(database_path: Path, recording_id: str) -> list[sqlite3.Row]:
    with connect(database_path) as connection:
        return list(
            connection.execute(
                """
                WITH latest AS (
                    SELECT sc.*, ROW_NUMBER() OVER (
                        PARTITION BY sc.recording_id, sc.local_speaker_id, sc.clip_index
                        ORDER BY sc.revision DESC
                    ) AS rank
                    FROM speaker_clips AS sc WHERE sc.recording_id = ?
                )
                SELECT latest.id AS clip_id, latest.recording_id, latest.local_speaker_id,
                       latest.segment_id, rs.person_id, artifacts.relative_path
                FROM latest
                JOIN recording_speakers AS rs
                  ON rs.recording_id = latest.recording_id
                 AND rs.local_speaker_id = latest.local_speaker_id
                JOIN segments AS s ON s.id = latest.segment_id
                JOIN artifacts ON artifacts.id = latest.artifact_id
                WHERE latest.rank = 1
                  AND rs.person_id IS NOT NULL AND rs.speaker_source = 'manual'
                  AND s.person_id = rs.person_id AND s.speaker_source = 'manual'
                ORDER BY latest.local_speaker_id, latest.clip_index
                """,
                (recording_id,),
            ).fetchall()
        )


def _safe_clip_path(root: Path, relative_path: str) -> Path:
    try:
        resolved_root = root.resolve(strict=True)
        path = (resolved_root / relative_path).resolve(strict=True)
    except OSError as error:
        raise SpeakerEmbeddingError(
            "SPEAKER_CLIP_NOT_AVAILABLE", "speaker clip is unavailable"
        ) from error
    if not path.is_file() or not path.is_relative_to(resolved_root):
        raise SpeakerEmbeddingError("SPEAKER_CLIP_NOT_AVAILABLE", "speaker clip is unavailable")
    return path


def _register_embedding(
    database_path: Path, candidate: sqlite3.Row, result: EmbeddingResult
) -> str:
    fingerprint_hash = hashlib.sha256(result.model_fingerprint.encode()).hexdigest()
    embedding_id = str(
        uuid.uuid5(
            uuid.UUID(str(candidate["recording_id"])), f"{candidate['clip_id']}:{fingerprint_hash}"
        )
    )
    timestamp = utc_now()
    with connect(database_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        current = connection.execute(
            """
            SELECT 1
            FROM recording_speakers AS rs
            JOIN segments AS s ON s.id = ?
            JOIN speaker_clips AS sc ON sc.id = ? AND sc.segment_id = s.id
            WHERE rs.recording_id = ? AND rs.local_speaker_id = ?
              AND rs.person_id = ? AND rs.speaker_source = 'manual'
              AND s.person_id = rs.person_id AND s.speaker_source = 'manual'
            """,
            (
                candidate["segment_id"],
                candidate["clip_id"],
                candidate["recording_id"],
                candidate["local_speaker_id"],
                candidate["person_id"],
            ),
        ).fetchone()
        if current is None:
            raise SpeakerEmbeddingError(
                "SPEAKER_EMBEDDING_SOURCE_CHANGED", "speaker assignment changed during embedding"
            )
        connection.execute(
            """
            INSERT INTO speaker_embeddings(
                id, person_id, recording_id, local_speaker_id, segment_id,
                model_fingerprint, vector_store, collection_name, vector_key,
                status, invalidated_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', NULL, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                person_id = excluded.person_id, status = 'active', invalidated_at = NULL,
                updated_at = excluded.updated_at
            """,
            (
                embedding_id,
                candidate["person_id"],
                candidate["recording_id"],
                candidate["local_speaker_id"],
                candidate["segment_id"],
                result.model_fingerprint,
                VECTOR_STORE,
                VECTOR_COLLECTION,
                embedding_id,
                timestamp,
                timestamp,
            ),
        )
        _upsert_vector(connection, embedding_id, result.vector)
        connection.commit()
    return embedding_id


def _float32_bytes(values: Sequence[float]) -> bytes:
    import struct

    return struct.pack(f"{len(values)}f", *values)


def invalidate_embeddings(
    connection: sqlite3.Connection, recording_id: str, segment_ids: Sequence[str] | None = None
) -> set[str]:
    parameters: list[object] = [recording_id]
    condition = "recording_id = ?"
    if segment_ids is not None:
        if not segment_ids:
            return set()
        placeholders = ",".join("?" for _ in segment_ids)
        condition += f" AND segment_id IN ({placeholders})"
        parameters.extend(segment_ids)
    rows = connection.execute(
        f"SELECT id, person_id FROM speaker_embeddings WHERE {condition} AND status = 'active'",
        parameters,
    ).fetchall()
    if not rows:
        return set()
    timestamp = utc_now()
    ids = [str(row["id"]) for row in rows]
    placeholders = ",".join("?" for _ in ids)
    connection.execute(
        f"UPDATE speaker_embeddings SET status = 'invalidated', invalidated_at = ?, "
        f"updated_at = ? WHERE id IN ({placeholders})",
        (timestamp, timestamp, *ids),
    )
    vector_rows = connection.execute(
        f"SELECT id FROM speaker_vector_keys WHERE vector_key IN ({placeholders})", ids
    ).fetchall()
    connection.executemany(
        "DELETE FROM speaker_vectors WHERE vector_id = ?",
        [(int(row["id"]),) for row in vector_rows],
    )
    affected = {str(row["person_id"]) for row in rows}
    _invalidate_profiles(connection, affected)
    return affected


def _upsert_vector(connection: sqlite3.Connection, vector_key: str, vector: Sequence[float]) -> int:
    connection.execute(
        "INSERT OR IGNORE INTO speaker_vector_keys(vector_key) VALUES (?)", (vector_key,)
    )
    vector_id = int(
        connection.execute(
            "SELECT id FROM speaker_vector_keys WHERE vector_key = ?", (vector_key,)
        ).fetchone()["id"]
    )
    connection.execute("DELETE FROM speaker_vectors WHERE vector_id = ?", (vector_id,))
    connection.execute(
        "INSERT INTO speaker_vectors(vector_id, embedding) VALUES (?, ?)",
        (vector_id, sqlite3.Binary(_float32_bytes(vector))),
    )
    return vector_id


def _delete_vector(connection: sqlite3.Connection, vector_key: str | None) -> None:
    if vector_key is None:
        return
    row = connection.execute(
        "SELECT id FROM speaker_vector_keys WHERE vector_key = ?", (vector_key,)
    ).fetchone()
    if row is not None:
        connection.execute("DELETE FROM speaker_vectors WHERE vector_id = ?", (int(row["id"]),))


def _invalidate_profiles(connection: sqlite3.Connection, person_ids: set[str]) -> None:
    if not person_ids:
        return
    placeholders = ",".join("?" for _ in person_ids)
    rows = connection.execute(
        f"SELECT id, vector_key FROM speaker_profiles WHERE person_id IN ({placeholders})",
        sorted(person_ids),
    ).fetchall()
    for row in rows:
        _delete_vector(connection, cast(str | None, row["vector_key"]))
    profile_ids = [str(row["id"]) for row in rows]
    if profile_ids:
        profile_placeholders = ",".join("?" for _ in profile_ids)
        connection.execute(
            f"DELETE FROM speaker_profile_members WHERE profile_id IN ({profile_placeholders})",
            profile_ids,
        )
        timestamp = utc_now()
        connection.execute(
            f"""
            UPDATE speaker_profiles
            SET sample_count = 0, recording_count = 0, status = 'insufficient',
                vector_store = NULL, collection_name = NULL, vector_key = NULL, updated_at = ?
            WHERE id IN ({profile_placeholders})
            """,
            (timestamp, *profile_ids),
        )


def rebuild_person_profiles(database_path: Path, person_ids: set[str]) -> None:
    for person_id in sorted(person_ids):
        _rebuild_person_profiles(database_path, person_id)


def _rebuild_person_profiles(database_path: Path, person_id: str) -> None:
    with connect(database_path) as connection:
        fingerprints = {
            str(row["model_fingerprint"])
            for row in connection.execute(
                """
                SELECT model_fingerprint FROM speaker_embeddings WHERE person_id = ?
                UNION
                SELECT model_fingerprint FROM speaker_profiles WHERE person_id = ?
                """,
                (person_id, person_id),
            ).fetchall()
        }
    for fingerprint in sorted(fingerprints):
        _rebuild_profile(database_path, person_id, fingerprint)


def _rebuild_profile(database_path: Path, person_id: str, fingerprint: str) -> None:
    timestamp = utc_now()
    fingerprint_hash = hashlib.sha256(fingerprint.encode()).hexdigest()
    profile_id = str(
        uuid.uuid5(uuid.NAMESPACE_URL, f"speaker-profile:{person_id}:{fingerprint_hash}")
    )
    with connect(database_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        rows = connection.execute(
            """
            SELECT se.id, se.recording_id, sv.embedding
            FROM speaker_embeddings AS se
            JOIN recording_speakers AS rs
              ON rs.recording_id = se.recording_id
             AND rs.local_speaker_id = se.local_speaker_id
            JOIN segments AS s
              ON s.id = se.segment_id AND s.recording_id = se.recording_id
            JOIN speaker_vector_keys AS keys ON keys.vector_key = se.vector_key
            JOIN speaker_vectors AS sv ON sv.vector_id = keys.id
            WHERE se.person_id = ? AND se.model_fingerprint = ? AND se.status = 'active'
              AND rs.person_id = se.person_id AND rs.speaker_source = 'manual'
              AND s.person_id = se.person_id AND s.speaker_source = 'manual'
            ORDER BY se.created_at, se.id
            """,
            (person_id, fingerprint),
        ).fetchall()
        vectors = [_float32_values(bytes(row["embedding"])) for row in rows]
        sample_count = len(vectors)
        recording_count = len({str(row["recording_id"]) for row in rows})
        existing = connection.execute(
            "SELECT vector_key, created_at FROM speaker_profiles WHERE id = ?", (profile_id,)
        ).fetchone()
        if existing is not None:
            _delete_vector(connection, cast(str | None, existing["vector_key"]))
        centroid: tuple[float, ...] | None = None
        if sample_count >= 2:
            try:
                centroid = _normalized_vector(
                    [
                        sum(vector[index] for vector in vectors) / sample_count
                        for index in range(512)
                    ]
                )
            except SpeakerEmbeddingError:
                centroid = None
        eligible = centroid is not None
        vector_key = profile_id if eligible else None
        if centroid is not None:
            _upsert_vector(connection, profile_id, centroid)
        connection.execute(
            """
            INSERT INTO speaker_profiles(
                id, person_id, model_fingerprint, sample_count, recording_count, status,
                vector_store, collection_name, vector_key, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                sample_count = excluded.sample_count,
                recording_count = excluded.recording_count,
                status = excluded.status,
                vector_store = excluded.vector_store,
                collection_name = excluded.collection_name,
                vector_key = excluded.vector_key,
                updated_at = excluded.updated_at
            """,
            (
                profile_id,
                person_id,
                fingerprint,
                sample_count,
                recording_count,
                "eligible" if eligible else "insufficient",
                VECTOR_STORE if eligible else None,
                VECTOR_COLLECTION if eligible else None,
                vector_key,
                str(existing["created_at"]) if existing is not None else timestamp,
                timestamp,
            ),
        )
        connection.execute(
            "DELETE FROM speaker_profile_members WHERE profile_id = ?", (profile_id,)
        )
        connection.executemany(
            "INSERT INTO speaker_profile_members(profile_id, embedding_id) VALUES (?, ?)",
            [(profile_id, str(row["id"])) for row in rows],
        )
        connection.commit()


def _float32_values(value: bytes) -> tuple[float, ...]:
    import struct

    if len(value) != EMBEDDING_DIMENSION * 4:
        raise SpeakerEmbeddingError(
            "INVALID_SPEAKER_EMBEDDING", "stored speaker embedding has invalid dimension"
        )
    return tuple(struct.unpack(f"{EMBEDDING_DIMENSION}f", value))
