from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from app.artifacts import safe_category_slug, write_artifact, write_summary_artifacts
from app.db import connect
from app.repository import register_recording


def _recording(tmp_path: Path) -> tuple[Path, Path, str]:
    source = tmp_path / "source.m4a"
    source.write_bytes(b"audio")
    root = tmp_path / "artifacts"
    root.mkdir()
    database_path = tmp_path / "app.db"
    result = register_recording(database_path, source, "d" * 64, 5, 1000)
    return database_path, root, result.recording_id


def test_artifact_write_is_atomic_and_idempotent(tmp_path: Path) -> None:
    database_path, root, recording_id = _recording(tmp_path)

    first = write_artifact(
        database_path,
        root,
        recording_id,
        "transcript_json",
        Path(recording_id) / "transcript.json",
        b"first",
        1,
    )
    second = write_artifact(
        database_path,
        root,
        recording_id,
        "transcript_json",
        Path(recording_id) / "transcript.json",
        b"second",
        1,
    )

    assert first.artifact_id == second.artifact_id
    assert second.path.read_bytes() == b"second"
    assert not list(root.rglob("*.tmp"))
    with connect(database_path) as connection:
        rows = connection.execute(
            "SELECT content_sha256 FROM artifacts WHERE kind = 'transcript_json'"
        ).fetchall()
    assert len(rows) == 1
    assert rows[0]["content_sha256"] == second.content_sha256


def test_file_failure_leaves_no_final_file_or_database_row(tmp_path: Path) -> None:
    database_path, root, recording_id = _recording(tmp_path)

    with pytest.raises(OSError, match="injected"):
        write_artifact(
            database_path,
            root,
            recording_id,
            "transcript_json",
            Path(recording_id) / "transcript.json",
            b"content",
            1,
            before_replace=lambda: (_ for _ in ()).throw(OSError("injected")),
        )

    assert not list(root.rglob("transcript.json"))
    assert not list(root.rglob("*.tmp"))
    with connect(database_path) as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM artifacts WHERE kind = 'transcript_json'"
            ).fetchone()[0]
            == 0
        )


def test_database_failure_is_recovered_by_retry(tmp_path: Path) -> None:
    database_path, root, recording_id = _recording(tmp_path)
    arguments = (
        database_path,
        root,
        recording_id,
        "transcript_json",
        Path(recording_id) / "transcript.json",
        b"content",
        1,
    )

    with pytest.raises(sqlite3.OperationalError, match="injected"):
        write_artifact(
            *arguments,
            before_register=lambda: (_ for _ in ()).throw(sqlite3.OperationalError("injected")),
        )
    assert (root / recording_id / "transcript.json").read_bytes() == b"content"

    write_artifact(*arguments)

    with connect(database_path) as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM artifacts WHERE kind = 'transcript_json'"
            ).fetchone()[0]
            == 1
        )


@pytest.mark.parametrize(
    "category", ["../회의", "회의/비밀", "\\server", "...", "회의\n비밀", "회의\x1f비밀"]
)
def test_category_slug_rejects_unsafe_paths(category: str) -> None:
    with pytest.raises(ValueError):
        safe_category_slug(category)


def test_korean_category_slug_is_readable() -> None:
    assert safe_category_slug("일상 대화") == "일상-대화"


def test_summary_pair_is_registered_only_after_both_files_are_published(tmp_path: Path) -> None:
    database_path, root, recording_id = _recording(tmp_path)

    results = write_summary_artifacts(
        database_path,
        root,
        recording_id,
        1,
        "회의",
        b"json",
        b"markdown",
    )

    assert [item.path.read_bytes() for item in results] == [b"json", b"markdown"]
    assert all(f"/{recording_id}/revisions/1." in str(item.path) for item in results)
    with connect(database_path) as connection:
        rows = connection.execute(
            "SELECT kind FROM artifacts WHERE kind LIKE 'summary_%' ORDER BY kind"
        ).fetchall()
    assert [row["kind"] for row in rows] == ["summary_json", "summary_markdown"]


@pytest.mark.parametrize("failed_kind", ["summary_json", "summary_markdown"])
def test_summary_pair_file_failure_never_registers_partial_success(
    tmp_path: Path, failed_kind: str
) -> None:
    database_path, root, recording_id = _recording(tmp_path)

    with pytest.raises(OSError, match="injected"):
        write_summary_artifacts(
            database_path,
            root,
            recording_id,
            1,
            "회의",
            b"json",
            b"markdown",
            before_replace=lambda kind: (
                (_ for _ in ()).throw(OSError("injected")) if kind == failed_kind else None
            ),
        )

    with connect(database_path) as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM artifacts WHERE kind LIKE 'summary_%'"
            ).fetchone()[0]
            == 0
        )
    assert not list(root.rglob("*.tmp"))


def test_summary_pair_database_failure_preserves_previous_category(tmp_path: Path) -> None:
    database_path, root, recording_id = _recording(tmp_path)
    first = write_summary_artifacts(
        database_path, root, recording_id, 1, "회의", b"old-json", b"old-markdown"
    )

    with pytest.raises(sqlite3.OperationalError, match="injected"):
        write_summary_artifacts(
            database_path,
            root,
            recording_id,
            2,
            "강의",
            b"new-json",
            b"new-markdown",
            before_register=lambda: (_ for _ in ()).throw(sqlite3.OperationalError("injected")),
        )

    assert all(item.path.is_file() for item in first)
    with connect(database_path) as connection:
        paths = connection.execute(
            "SELECT relative_path FROM artifacts WHERE kind LIKE 'summary_%'"
        ).fetchall()
    assert len(paths) == 2
    assert all(str(row["relative_path"]).startswith("회의/") for row in paths)


def test_new_category_cleanup_happens_after_successful_pair_registration(tmp_path: Path) -> None:
    database_path, root, recording_id = _recording(tmp_path)
    old = write_summary_artifacts(
        database_path, root, recording_id, 1, "회의", b"old-json", b"old-markdown"
    )

    new = write_summary_artifacts(
        database_path, root, recording_id, 2, "강의", b"new-json", b"new-markdown"
    )

    assert not any(item.path.exists() for item in old)
    assert all(item.path.exists() for item in new)
    with connect(database_path) as connection:
        paths = connection.execute(
            "SELECT relative_path FROM artifacts WHERE kind LIKE 'summary_%'"
        ).fetchall()
    assert len(paths) == 2
    assert all(str(row["relative_path"]).startswith("강의/") for row in paths)
