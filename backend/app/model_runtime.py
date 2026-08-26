from __future__ import annotations

import json
import subprocess
from importlib import import_module, metadata
from typing import Protocol, cast


class CudaRuntime(Protocol):
    def is_available(self) -> bool: ...

    def device_count(self) -> int: ...

    def get_device_name(self, device: int) -> str: ...


class TorchVersion(Protocol):
    cuda: str | None


class TorchModule(Protocol):
    __version__: str
    cuda: CudaRuntime
    version: TorchVersion


def runtime_report() -> dict[str, object]:
    torch = cast(TorchModule, cast(object, import_module("torch")))
    cuda_available = torch.cuda.is_available()
    device_count = torch.cuda.device_count() if cuda_available else 0
    devices = [torch.cuda.get_device_name(index) for index in range(device_count)]
    driver_version = _nvidia_driver_version()
    return {
        "status": "ready" if cuda_available and device_count else "unavailable",
        "cuda_available": cuda_available,
        "cuda_runtime": torch.version.cuda,
        "driver_version": driver_version,
        "device_count": device_count,
        "devices": devices,
        "packages": {
            "torch": torch.__version__,
            "whisperx": metadata.version("whisperx"),
            "pyannote-audio": metadata.version("pyannote-audio"),
        },
    }


def _nvidia_driver_version() -> str | None:
    try:
        completed = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=driver_version",
                "--format=csv,noheader,nounits",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return None
    values = {line.strip() for line in completed.stdout.splitlines() if line.strip()}
    return ",".join(sorted(values)) or None


def main() -> None:
    report = runtime_report()
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    if report["status"] != "ready":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
