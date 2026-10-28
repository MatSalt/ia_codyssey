"""Fixtures shared by subsequent API tests."""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch
from app import config

# Avoid loading local secrets even when the module-level ASGI app is imported.
with patch.object(config, "load_dotenv", return_value=False):
    from app.main import create_app


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
def client(app):
    with TestClient(app, raise_server_exceptions=False) as instance:
        yield instance


@pytest.fixture(autouse=True)
def isolate_external_configuration(monkeypatch):
    """Tests never consume user credentials from .env or the host environment."""
    monkeypatch.setattr(config, "load_dotenv", lambda *args, **kwargs: None)
    for name in ("GOOGLE_APPLICATION_CREDENTIALS", "FIREBASE_SERVICE_ACCOUNT_JSON",
                 "FIREBASE_PROJECT_ID", "OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_MODEL",
                 "ALLOWED_ORIGINS"):
        monkeypatch.delenv(name, raising=False)
