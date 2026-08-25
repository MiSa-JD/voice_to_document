from __future__ import annotations

from pathlib import Path
from typing import Any

from app.api import create_app
from app.config import Settings
from fastapi.testclient import TestClient


def test_liveness_does_not_depend_on_readiness(settings_values: dict[str, Any]) -> None:
    def failing_probe(_: Path) -> None:
        raise OSError("/private/sensitive/database/path")

    client = TestClient(create_app(Settings(**settings_values), database_probe=failing_probe))

    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "live"}


def test_readiness_checks_database_and_paths(settings_values: dict[str, Any]) -> None:
    client = TestClient(create_app(Settings(**settings_values)))

    response = client.get("/health/ready")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["checks"]["database"] == {"status": "ok"}
    assert all(check["status"] == "ok" for check in payload["checks"].values())


def test_readiness_redacts_database_path(settings_values: dict[str, Any]) -> None:
    def failing_probe(_: Path) -> None:
        raise OSError("/private/sensitive/database/path")

    client = TestClient(create_app(Settings(**settings_values), database_probe=failing_probe))

    response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["checks"]["database"] == {
        "status": "error",
        "message": "database path is unavailable",
    }
    assert "/private/sensitive" not in response.text


def test_readiness_detects_path_removed_after_start(settings_values: dict[str, Any]) -> None:
    settings = Settings(**settings_values)
    settings.transcript_root.rmdir()
    client = TestClient(create_app(settings))

    response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["checks"]["transcript_root"]["status"] == "error"
