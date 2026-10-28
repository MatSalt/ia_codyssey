from types import SimpleNamespace

import pytest

from app import dependencies
from app.config import Settings
from app.ports import StorageUnavailable


def test_data_repository_uses_configured_project_and_key_path(monkeypatch):
    assert hasattr(dependencies, "_build_firestore_client"), "Lazy client factory missing"
    calls = []
    def client_factory(project, path):
        calls.append((project, path))
        return SimpleNamespace(collection=lambda name: "fake-data-collection" if name == "data" else None)
    monkeypatch.setattr(dependencies, "get_settings", lambda: Settings(allowed_origins=(), firebase_project_id="test-project", google_application_credentials="/fake/key.json"))
    monkeypatch.setattr(dependencies, "_build_firestore_client", client_factory)
    repository = dependencies.get_data_repository()
    assert repository.collection == "fake-data-collection"
    assert calls == [("test-project", "/fake/key.json")]


def test_client_initialization_failure_is_sanitized(monkeypatch):
    assert hasattr(dependencies, "_build_firestore_client"), "Lazy client factory missing"
    monkeypatch.setattr(dependencies, "get_settings", lambda: Settings(allowed_origins=(), firebase_project_id="test-project", google_application_credentials="/fake/key.json"))
    def fail(*args):
        raise ValueError("private-key-marker")
    monkeypatch.setattr(dependencies, "_build_firestore_client", fail)
    with pytest.raises(StorageUnavailable) as error:
        dependencies.get_data_repository()
    assert "private-key-marker" not in str(error.value)
