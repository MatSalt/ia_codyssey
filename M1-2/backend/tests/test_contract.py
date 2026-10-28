from datetime import date
import importlib.util

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from pydantic import ValidationError


def contracts():
    assert importlib.util.find_spec('app') is not None, 'API foundation is missing'
    from app import models
    return models


@pytest.mark.parametrize('value', [-1, True, 1.5, '1'])
def test_record_rejects_non_count_values(value):
    with pytest.raises(ValidationError):
        contracts().RecordCreate(date='2026-01-01', value=value)


@pytest.mark.parametrize('day', ['2026-02-30', '20260101', '2026-1-01', '2026-01-01T00:00:00', 1767225600])
def test_record_rejects_non_iso_dates(day):
    with pytest.raises(ValidationError):
        contracts().RecordCreate(date=day, value=1)


def test_record_defaults_and_internal_date():
    model = contracts().RecordCreate(date='2026-01-01', value=0)
    assert model.memo == ''
    assert model.date == date(2026, 1, 1)
    assert model.model_dump(mode='json')['date'] == '2026-01-01'
    assert contracts().RecordCreate(date=date(2026, 1, 1), value=2).value == 2


@pytest.mark.parametrize('name,payload', [
    ('RecordCreate', dict(date='2026-01-01', value=1, extra='bad')),
    ('RecordUpdate', dict(date='2026-01-01', value=1, memo='')),
    ('MessageInput', dict(role='system', content='bad')),
    ('MessageInput', dict(role='user', content='q', created_at='2026-01-01T00:00:00Z')),
    ('ChatRequest', dict(message='  ')),
    ('ChatRequest', dict(message='x' * 4001)),
])
def test_input_boundaries(name, payload):
    with pytest.raises(ValidationError):
        getattr(contracts(), name)(**payload)


def make_app(monkeypatch):
    contracts()
    monkeypatch.setenv('ALLOWED_ORIGINS', 'https://allowed.example')
    from app.main import create_app
    return create_app()


def test_app_without_secrets(monkeypatch):
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    monkeypatch.delenv('FIREBASE_PROJECT_ID', raising=False)
    app = make_app(monkeypatch)
    with TestClient(app) as client:
        assert client.get('/docs').status_code == 200
        assert client.get('/openapi.json').status_code == 200


@pytest.mark.parametrize('origin,status', [('https://allowed.example', 200), ('https://blocked.example', 400)])
def test_cors_allowlist(monkeypatch, origin, status):
    with TestClient(make_app(monkeypatch)) as client:
        response = client.options('/api/data', headers={'Origin': origin, 'Access-Control-Request-Method': 'POST'})
        assert response.status_code == status
        assert response.headers.get('access-control-allow-origin') == (origin if status == 200 else None)


@pytest.mark.parametrize('error,status', [('DuplicateRecord', 409), ('NotFound', 404), ('StorageUnavailable', 503), ('GenerationUnavailable', 502), ('RuntimeError', 500)])
def test_errors_do_not_leak_exception_details(monkeypatch, error, status):
    app = make_app(monkeypatch)
    from app import ports
    exception = RuntimeError if error == 'RuntimeError' else getattr(ports, error)
    @app.get('/test-error')
    def fail():
        raise exception('sensitive-api-key-and-credentials')
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get('/test-error')
        assert response.status_code == status
        assert response.json()['detail']
        assert 'sensitive' not in response.text


@pytest.mark.parametrize('provider,status', [('get_data_repository', 503), ('get_conversation_repository', 503), ('get_chat_gateway', 502)])
def test_unconfigured_dependencies_fail_safely_and_can_be_overridden(monkeypatch, provider, status):
    app = make_app(monkeypatch)
    from app import dependencies
    dependency = getattr(dependencies, provider)
    @app.get('/test-dependency')
    def probe(value=Depends(dependency)):
        if provider == 'get_chat_gateway' and hasattr(value, 'complete'):
            value.complete('rules', [])
        return {'configured': value is not None}
    with TestClient(app, raise_server_exceptions=False) as client:
        assert client.get('/test-dependency').status_code == status
        app.dependency_overrides[dependency] = lambda: object()
        assert client.get('/test-dependency').json() == {'configured': True}


def test_unexpected_error_keeps_cors_headers(monkeypatch):
    app = make_app(monkeypatch)
    @app.get('/test-cors-error')
    def fail():
        raise RuntimeError('sensitive credential')
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get('/test-cors-error', headers={'Origin': 'https://allowed.example'})
        assert response.status_code == 500
        assert response.headers.get('access-control-allow-origin') == 'https://allowed.example'
        assert 'sensitive' not in response.text
