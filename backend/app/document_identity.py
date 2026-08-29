from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from app.categories import category_slug
from app.db import connect, migrate_database, utc_now

_FORBIDDEN_FILENAME_CHARACTERS = frozenset('<>:"/\\|?*')


@dataclass(frozen=True)
class DocumentIdentity:
    sequence: int
    title: str

    @property
    def relative_path(self) -> Path:
        return Path(f"{self.sequence:04d}_{self.title}.md")


def normalize_document_title(first_utterance: str | None, category: str | None) -> str:
    normalized = re.sub(r"\s+", " ", first_utterance or "").strip()[:20]
    cleaned = "".join(
        character
        for character in normalized
        if character not in _FORBIDDEN_FILENAME_CHARACTERS
        and unicodedata.category(character) != "Cc"
    ).strip(" .")
    if cleaned:
        return cleaned
    if category:
        try:
            fallback = category_slug(category).strip(" .")
        except ValueError:
            fallback = ""
        if fallback:
            return fallback
    return "recording"


def document_relative_path(sequence: int, title: str) -> Path:
    if sequence <= 0:
        raise ValueError("document sequence must be positive")
    if normalize_document_title(title, None) != title:
        raise ValueError("document title must already be normalized")
    path = Path(f"{sequence:04d}_{title}.md")
    if len(path.parts) != 1 or path.name != str(path):
        raise ValueError("document path must be flat")
    return path


def ensure_document_identity(database_path: Path, recording_id: str) -> DocumentIdentity:
    migrate_database(database_path)
    with connect(database_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        try:
            recording = connection.execute(
                """
                SELECT document_sequence, document_title, category
                FROM recordings WHERE id = ?
                """,
                (recording_id,),
            ).fetchone()
            if recording is None:
                raise KeyError(recording_id)

            sequence = recording["document_sequence"]
            title = recording["document_title"]
            if sequence is None:
                row = connection.execute(
                    """
                    UPDATE document_sequence_counter
                    SET last_value = last_value + 1
                    WHERE singleton = 1
                    RETURNING last_value
                    """
                ).fetchone()
                if row is None:
                    raise RuntimeError("document sequence counter is missing")
                sequence = int(row["last_value"])
            if title is None:
                segment = connection.execute(
                    """
                    SELECT text FROM segments
                    WHERE recording_id = ? AND length(trim(text)) > 0
                    ORDER BY start_ms, end_ms, id LIMIT 1
                    """,
                    (recording_id,),
                ).fetchone()
                first_utterance = str(segment["text"]) if segment is not None else None
                title = normalize_document_title(first_utterance, recording["category"])

            connection.execute(
                """
                UPDATE recordings
                SET document_sequence = ?, document_title = ?, updated_at = ?
                WHERE id = ?
                """,
                (sequence, title, utc_now(), recording_id),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    return DocumentIdentity(int(sequence), str(title))
