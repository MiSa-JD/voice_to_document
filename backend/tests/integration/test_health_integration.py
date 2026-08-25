from __future__ import annotations

from typing import Any

from app.api import create_app
from app.config import Settings
from fastapi.testclient import TestClient


def test_health_uses_real_temporary_database(settings_values: dict[str, Any]) -> None:
    settings = Settings(**settings_values)

    response = TestClient(create_app(settings)).get("/health/ready")

    assert response.status_code == 200
    assert settings.database_path.is_file()
