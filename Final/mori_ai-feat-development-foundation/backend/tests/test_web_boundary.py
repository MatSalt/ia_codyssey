from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.main import create_app


@pytest.fixture
def client(tmp_path: Path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("console.log('foundation');")
    (tmp_path / "index.html").write_text("<!doctype html><title>Mori foundation</title>")
    return TestClient(create_app(static_dir=tmp_path))


def test_health_ok(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.parametrize("path", ["/api", "/api/v1", "/api/v1/absent"])
def test_missing_api_is_404(client, path):
    response = client.get(path)
    assert response.status_code == 404
    assert "text/html" not in response.headers["content-type"]


@pytest.mark.parametrize("path", ["/assets", "/assets/missing.js", "/favicon.ico", "/missing.css"])
def test_missing_static_asset_is_404(client, path):
    response = client.get(path)
    assert response.status_code == 404
    assert "text/html" not in response.headers["content-type"]


@pytest.mark.parametrize("path", ["/", "/albums", "/albums/abc/edit"])
def test_spa_route_serves_index(client, path):
    response = client.get(path)
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Mori foundation" in response.text


def test_existing_static_asset_is_served(client):
    response = client.get("/assets/app.js")
    assert response.status_code == 200
    assert response.text == "console.log('foundation');"


def test_no_build_does_not_claim_spa_ready(tmp_path):
    assert TestClient(create_app(static_dir=tmp_path)).get("/albums").status_code == 404


def test_settings_reject_missing_database_url(monkeypatch):
    from backend.settings import Settings
    from pydantic import ValidationError

    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


@pytest.mark.parametrize("values", [
    {"database_url": "sqlite:///local.db"},
    {"database_url": "postgresql+asyncpg://localhost/db", "worker_poll_seconds": 0},
    {"database_url": "postgresql+asyncpg://localhost/db", "worker_poll_seconds": float("inf")},
    {"database_url": "postgresql+asyncpg://localhost/db", "storage_mode": "r2"},
    {"database_url": "postgresql+asyncpg://localhost/db", "storage_root": "relative"},
])
def test_settings_reject_invalid_configuration(values):
    from backend.settings import Settings
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Settings(_env_file=None, **values)


def test_settings_accept_explicit_local_configuration():
    from backend.settings import Settings

    settings = Settings(_env_file=None, database_url="postgresql+asyncpg://localhost/db")
    assert settings.storage_mode == "local"
    assert settings.storage_root.is_absolute()
    assert settings.worker_poll_seconds == 1


def test_web_startup_validates_configuration(tmp_path, monkeypatch):
    from pydantic import ValidationError

    monkeypatch.setenv("DATABASE_URL", "sqlite:///wrong.db")
    with pytest.raises(ValidationError):
        with TestClient(create_app(static_dir=tmp_path)):
            pass
