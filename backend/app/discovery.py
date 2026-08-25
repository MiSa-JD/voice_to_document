from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FileSnapshot:
    size: int
    mtime_ns: int
    unchanged_since: float
    emitted: bool = False


class StabilityTracker:
    def __init__(
        self,
        stable_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.stable_seconds = stable_seconds
        self.clock = clock
        self._snapshots: dict[Path, FileSnapshot] = {}

    def scan(self, input_root: Path) -> list[Path]:
        root = input_root.resolve(strict=True)
        now = self.clock()
        seen: set[Path] = set()
        stable: list[Path] = []

        for candidate in root.rglob("*"):
            if not _is_candidate(candidate, root):
                continue
            resolved = candidate.resolve(strict=True)
            seen.add(resolved)
            stat = candidate.stat()
            previous = self._snapshots.get(resolved)
            if previous is None or (previous.size, previous.mtime_ns) != (
                stat.st_size,
                stat.st_mtime_ns,
            ):
                self._snapshots[resolved] = FileSnapshot(
                    size=stat.st_size,
                    mtime_ns=stat.st_mtime_ns,
                    unchanged_since=now,
                )
                continue
            if now - previous.unchanged_since >= self.stable_seconds and not previous.emitted:
                stable.append(resolved)
                self._snapshots[resolved] = FileSnapshot(
                    size=previous.size,
                    mtime_ns=previous.mtime_ns,
                    unchanged_since=previous.unchanged_since,
                    emitted=True,
                )

        self._snapshots = {
            path: snapshot for path, snapshot in self._snapshots.items() if path in seen
        }
        return sorted(stable)


def _is_candidate(candidate: Path, root: Path) -> bool:
    if candidate.is_symlink() or not candidate.is_file():
        return False
    if candidate.suffix.lower() != ".m4a" or _is_temporary_name(candidate.name):
        return False
    try:
        candidate.resolve(strict=True).relative_to(root)
    except ValueError:
        return False
    return True


def _is_temporary_name(name: str) -> bool:
    lowered = name.lower()
    return (
        lowered.startswith(".syncthing.")
        or lowered.startswith("~")
        or lowered.endswith((".tmp", ".part", ".partial", ".download"))
    )
