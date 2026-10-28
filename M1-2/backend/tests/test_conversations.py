from copy import deepcopy
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.dependencies import get_conversation_repository
from app.models import ConversationCreate
from app.ports import NotFound, StorageUnavailable

class Snapshot:
    def __init__(self, key, data): self.id, self.data, self.exists = key, deepcopy(data), data is not None
    def to_dict(self): return deepcopy(self.data)
class Document:
    def __init__(self, client, key): self.client, self.id = client, key
    def create(self, data, **kw): self.client.data[self.id] = deepcopy(data)
    def get(self, transaction=None, **kw):
        if transaction:
            transaction.read_version = self.client.version
            self.client.reads += 1
        return Snapshot(self.id, self.client.data.get(self.id))
    def delete(self, **kw):
        from google.api_core.exceptions import NotFound as Missing
        if self.id not in self.client.data: raise Missing('missing')
        del self.client.data[self.id]
class Client:
    def __init__(self): self.data, self.version, self.race, self.reads = {}, 0, None, 0
    def collection(self, name): return self
    def document(self, key=None): return Document(self, key or str(len(self.data)+1))
    def stream(self, **kw): return [Snapshot(k,v) for k,v in self.data.items()]
    def write_option(self, **kw): return kw
    def transaction(self, **kw): return Transaction(self)
class Transaction:
    _read_only = False
    _id = b'transaction'
    _max_attempts = 3
    def __init__(self, client): self.client = client
    def update(self, ref, data): self.pending = (ref, deepcopy(data))
    def _begin(self, **kw): pass
    def _rollback(self, **kw): pass
    def _clean_up(self): pass
    def _commit(self):
        from google.api_core.exceptions import Aborted
        if self.client.race:
            race, self.client.race = self.client.race, None
            race(self.client)
            self.client.version += 1
        if self.read_version != self.client.version: raise Aborted('conflict')
        ref, data = self.pending
        self.client.data[ref.id].update(data)
        self.client.version += 1

def test_history_round_trip():
    from app.conversations.repository import FirestoreConversationRepository
    app = create_app()
    app.dependency_overrides[get_conversation_repository] = lambda: repo
    repo = FirestoreConversationRepository(Client())
    with TestClient(app) as c:
        r = c.post('/api/conversations', json={'title':'one','messages':[{'role':'user','content':'hello'}]})
        assert r.status_code == 201
        item = r.json()
        assert item['created_at'].endswith('Z')
        second = c.post('/api/conversations', json={'title':'two','messages':[]}).json()
        items = c.get('/api/conversations').json()['items']
        assert [x['id'] for x in items] == [second['id'],item['id']]
        assert 'messages' not in items[0]
        assert c.get('/api/conversations/'+item['id']).json()['messages'][0]['content'] == 'hello'
        assert c.post('/api/conversations',json={'title':'bad','messages':[{'role':'system','content':'bad'}]}).status_code == 422
        assert c.delete('/api/conversations/'+item['id']).status_code == 204
        assert c.get('/api/conversations/'+item['id']).status_code == 404

def test_append_preserves_existing_turns():
    from app.conversations.repository import FirestoreConversationRepository
    client = Client(); repo = FirestoreConversationRepository(client)
    item = repo.create(ConversationCreate(title='hi',messages=[]))
    def other(c): c.data[item.id]['messages'].append({'role':'user','content':'concurrent','created_at':item.created_at})
    client.race = other
    assert [m.content for m in repo.append_turn(item.id,'question','answer').messages] == ['concurrent','question','answer']
    assert client.reads == 2

def test_append_deleted_conversation():
    from app.conversations.repository import FirestoreConversationRepository
    client = Client(); repo = FirestoreConversationRepository(client)
    item = repo.create(ConversationCreate(title='hi',messages=[]))
    client.race = lambda c: c.data.pop(item.id)
    with pytest.raises(NotFound): repo.append_turn(item.id,'question','answer')
    assert item.id not in client.data
    assert client.reads == 2
    with pytest.raises(NotFound): repo.append_turn('missing','question','answer')

def test_bad_ids_and_storage_failure():
    from app.conversations.repository import FirestoreConversationRepository
    repo = FirestoreConversationRepository(Client())
    for key in ('a/b','.','..',''):
        with pytest.raises(NotFound): repo.get(key)
    repo.collection.stream = lambda **kw: (_ for _ in ()).throw(RuntimeError('secret'))
    with pytest.raises(StorageUnavailable,match='^Storage is temporarily unavailable.$'): repo.list_conversations()
