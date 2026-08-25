from __future__ import annotations

from pathlib import Path

from app.discovery import StabilityTracker


class FakeClock:
    def __init__(self) -> None:
        self.value = 100.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def test_only_stable_m4a_is_returned(tmp_path: Path) -> None:
    clock = FakeClock()
    tracker = StabilityTracker(30, clock)
    audio = tmp_path / "nested" / "녹음.M4A"
    audio.parent.mkdir()
    audio.write_bytes(b"first")

    assert tracker.scan(tmp_path) == []
    clock.advance(29)
    assert tracker.scan(tmp_path) == []
    clock.advance(1)
    assert tracker.scan(tmp_path) == [audio.resolve()]


def test_size_or_mtime_change_restarts_stability_window(tmp_path: Path) -> None:
    clock = FakeClock()
    tracker = StabilityTracker(10, clock)
    audio = tmp_path / "copying.m4a"
    audio.write_bytes(b"part")

    tracker.scan(tmp_path)
    clock.advance(9)
    audio.write_bytes(b"complete")
    assert tracker.scan(tmp_path) == []
    clock.advance(9)
    assert tracker.scan(tmp_path) == []
    clock.advance(1)
    assert tracker.scan(tmp_path) == [audio.resolve()]


def test_symlinks_and_temporary_patterns_are_ignored(tmp_path: Path) -> None:
    clock = FakeClock()
    tracker = StabilityTracker(1, clock)
    outside = tmp_path.parent / "outside.m4a"
    outside.write_bytes(b"outside")
    (tmp_path / "link.m4a").symlink_to(outside)
    for name in (
        ".syncthing.recording.m4a.tmp",
        "recording.m4a.part",
        "recording.m4a.partial",
        "recording.m4a.download",
        "~recording.m4a",
        "note.txt",
    ):
        (tmp_path / name).write_bytes(b"ignored")

    tracker.scan(tmp_path)
    clock.advance(1)

    assert tracker.scan(tmp_path) == []


def test_disappeared_file_observation_is_removed(tmp_path: Path) -> None:
    clock = FakeClock()
    tracker = StabilityTracker(1, clock)
    audio = tmp_path / "later.m4a"
    audio.write_bytes(b"first")
    tracker.scan(tmp_path)
    audio.unlink()
    tracker.scan(tmp_path)
    audio.write_bytes(b"second")
    clock.advance(5)

    assert tracker.scan(tmp_path) == []
