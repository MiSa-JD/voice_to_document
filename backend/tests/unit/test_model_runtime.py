from __future__ import annotations

import subprocess
from importlib import metadata
from types import SimpleNamespace
from typing import Any

import pytest
from app import model_runtime


class FakeCuda:
    def __init__(self, available: bool) -> None:
        self.available = available

    def is_available(self) -> bool:
        return self.available

    def device_count(self) -> int:
        return 1 if self.available else 0

    def get_device_name(self, device: int) -> str:
        assert device == 0
        return "Test GPU"


@pytest.mark.parametrize(
    ("available", "expected_status", "expected_devices"),
    [(True, "ready", ["Test GPU"]), (False, "unavailable", [])],
)
def test_runtime_report_distinguishes_cuda_availability(
    monkeypatch: pytest.MonkeyPatch,
    available: bool,
    expected_status: str,
    expected_devices: list[str],
) -> None:
    fake_torch = SimpleNamespace(
        __version__="2.8.0+cu128",
        version=SimpleNamespace(cuda="12.8"),
        cuda=FakeCuda(available),
    )
    monkeypatch.setattr(
        model_runtime,
        "import_module",
        lambda name: fake_torch if name == "torch" else None,
    )
    monkeypatch.setattr(metadata, "version", lambda name: f"{name}-version")
    monkeypatch.setattr(model_runtime, "_nvidia_driver_version", lambda: "580.00")

    report = model_runtime.runtime_report()

    assert report["status"] == expected_status
    assert report["devices"] == expected_devices
    assert "environment" not in report


def test_driver_probe_uses_argument_array_and_normalizes_versions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_run(arguments: list[str], **kwargs: object) -> SimpleNamespace:
        captured["arguments"] = arguments
        captured.update(kwargs)
        return SimpleNamespace(stdout="580.82.07\n580.82.07\n")

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert model_runtime._nvidia_driver_version() == "580.82.07"
    assert captured["arguments"] == [
        "nvidia-smi",
        "--query-gpu=driver_version",
        "--format=csv,noheader,nounits",
    ]
    assert captured["check"] is True
    assert captured["capture_output"] is True


def test_driver_probe_returns_none_when_nvidia_smi_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_arguments: object, **_kwargs: object) -> None:
        raise subprocess.TimeoutExpired("nvidia-smi", 10)

    monkeypatch.setattr(subprocess, "run", fail)

    assert model_runtime._nvidia_driver_version() is None
