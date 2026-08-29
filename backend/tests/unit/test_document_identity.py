from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from app.db import connect
from app.document_identity import (
    document_relative_path,
    ensure_document_identity,
    normalize_document_title,
)
from app.repository import register_recording


def _recording(database_path: Path, directory: Path, index: int) -> str:
    source = directory / f"source-{index}.m4a"
    source.write_bytes(b"audio")
    return register_recording(database_path, source, f"{index:064x}", 5, 1000).recording_id


def test_document_title_normalizes_truncates_and_removes_reserved_characters() -> None:
    assert (
        normalize_document_title("  안녕\n\t하세요  반갑습니다 ", None) == "안녕 하세요 반갑습니다"
    )
    assert normalize_document_title("가" * 21, None) == "가" * 20
    assert normalize_document_title(" .<회의>:/\\|?*\x00. ", None) == "회의"


def test_document_title_falls_back_to_category_then_recording() -> None:
    assert normalize_document_title("<>/*", "일상 대화") == "일상-대화"
    assert normalize_document_title("<>/*", None) == "recording"


@pytest.mark.parametrize(
    ("sequence", "expected"), [(1, "0001_제목.md"), (42, "0042_제목.md"), (10_000, "10000_제목.md")]
)
def test_document_relative_path_is_flat(sequence: int, expected: str) -> None:
    assert document_relative_path(sequence, "제목") == Path(expected)


@pytest.mark.parametrize("title", ["../escape", "nested/path", "bad?"])
def test_document_relative_path_rejects_unsafe_title(title: str) -> None:
    with pytest.raises(ValueError):
        document_relative_path(1, title)


def test_identity_is_stable_and_deleted_sequence_is_not_reused(tmp_path: Path) -> None:
    database_path = tmp_path / "app.db"
    first = _recording(database_path, tmp_path, 1)
    with connect(database_path) as connection:
        connection.execute("UPDATE recordings SET category = '회의' WHERE id = ?", (first,))
    identity = ensure_document_identity(database_path, first)
    assert ensure_document_identity(database_path, first) == identity
    with connect(database_path) as connection:
        connection.execute("DELETE FROM recordings WHERE id = ?", (first,))
    second = _recording(database_path, tmp_path, 2)
    assert ensure_document_identity(database_path, second).sequence == identity.sequence + 1


def test_concurrent_identity_allocation_is_unique(tmp_path: Path) -> None:
    database_path = tmp_path / "app.db"
    recording_ids = [_recording(database_path, tmp_path, index) for index in range(1, 5)]
    with ThreadPoolExecutor(max_workers=4) as executor:
        identities = list(
            executor.map(
                lambda value: ensure_document_identity(database_path, value), recording_ids
            )
        )
    assert len({identity.sequence for identity in identities}) == len(recording_ids)
