from unittest.mock import Mock
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.dependencies import get_data_repository
from app.models import Record
from app.ports import DuplicateRecord, NotFound, StorageUnavailable
from app.data.router import router


class MemoryRepository:
    def __init__(self): self.rows = {}
    def list_records(self): return list(self.rows.values())
    def create(self, payload):
        key = payload.date.isoformat()
        if key in self.rows: raise DuplicateRecord()
        self.rows[key] = Record(id=key, **payload.model_dump())
        return self.rows[key]
    def update(self, key, patch):
        if key not in self.rows: raise NotFound()
        self.rows[key] = Record(id=key, date=key, **patch.model_dump())
        return self.rows[key]
    def delete(self, key):
        if key not in self.rows: raise NotFound()
        del self.rows[key]


@pytest.fixture
def api():
    app = create_app()
    repo = MemoryRepository()
    app.dependency_overrides[get_data_repository] = lambda: repo
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, app


def test_data_crud(api):
    client, _ = api
    payload = {'date':'2026-01-02', 'value':5}
    response = client.post('/api/data', json=payload)
    assert response.status_code == 201
    assert response.json() == {'id':'2026-01-02', **payload, 'memo':''}
    assert client.post('/api/data', json=payload).status_code == 409
    client.post('/api/data', json={'date':'2026-01-01', 'value':0})
    assert [r['date'] for r in client.get('/api/data').json()['items']] == ['2026-01-01','2026-01-02']
    assert client.put('/api/data/2026-01-02', json={'value':8, 'memo':'changed'}).json() == {'id':'2026-01-02', 'date':'2026-01-02','value':8,'memo':'changed'}
    deleted = client.delete('/api/data/2026-01-02')
    assert deleted.status_code == 204 and deleted.content == b''
    assert client.delete('/api/data/2026-01-02').status_code == 404
    assert client.put('/api/data/2026-01-02', json={'value':8, 'memo':''}).status_code == 404


@pytest.mark.parametrize('payload', [{'value':1,'memo':'','date':'2026-01-03'}, {'value':True,'memo':''}, {'value':-1,'memo':''}])
def test_invalid_update_is_rejected(api, payload):
    client, _ = api
    assert client.put('/api/data/2026-01-02', json=payload).status_code == 422


def test_storage_error_safe_response(api):
    client, app = api
    repo = Mock()
    repo.list_records.side_effect = StorageUnavailable('private-key-secret')
    app.dependency_overrides[get_data_repository] = lambda: repo
    response = client.get('/api/data')
    assert response.status_code == 503
    assert 'private-key-secret' not in response.text
