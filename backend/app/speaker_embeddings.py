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
) -> list[str]:
    migrate_database(settings.database_path)
    candidates = _eligible_clips(settings.database_path, recording_id)
    created: list[str] = []
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
        created.append(_register_embedding(settings.database_path, candidate, result))
    affected_person_ids = _recording_person_ids(settings.database_path, recording_id)
    rebuild_person_profiles(settings.database_path, affected_person_ids)
    return created


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
