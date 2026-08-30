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
    return created


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
        connection.execute(
            "INSERT OR IGNORE INTO speaker_vector_keys(vector_key) VALUES (?)", (embedding_id,)
        )
        vector_id = int(
            connection.execute(
                "SELECT id FROM speaker_vector_keys WHERE vector_key = ?", (embedding_id,)
            ).fetchone()["id"]
        )
        connection.execute("DELETE FROM speaker_vectors WHERE vector_id = ?", (vector_id,))
        connection.execute(
            "INSERT INTO speaker_vectors(vector_id, embedding) VALUES (?, ?)",
            (vector_id, sqlite3.Binary(_float32_bytes(result.vector))),
        )
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
    return {str(row["person_id"]) for row in rows}
