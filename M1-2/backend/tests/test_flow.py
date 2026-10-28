from app.dependencies import get_data_repository, get_conversation_repository, get_chat_gateway
from flow_fakes import MemoryData, MemoryConversations, SummaryGateway


def test_full_api_flow_uses_changed_data_and_restores_saved_turns(app, client):
    data, conversations, gateway = MemoryData(), MemoryConversations(), SummaryGateway()
    app.dependency_overrides.update({get_data_repository:lambda:data, get_conversation_repository:lambda:conversations, get_chat_gateway:lambda:gateway})
    assert client.post('/api/data',json={'date':'2026-01-01','value':0}).status_code == 201
    assert client.post('/api/data',json={'date':'2026-01-02','value':4}).status_code == 201
    summary = client.get('/api/data/summary').json()
    assert summary['comparison']['change_percent'] is None
    first = client.post('/api/chat',json={'message':'총 열람 횟수는? '})
    assert first.status_code == 200
    key = first.json()['conversation_id']
    assert '4회' in first.json()['answer']
    assert client.get('/api/conversations').json()['items'][0]['id'] == key
    restored = client.get('/api/conversations/'+key).json()
    assert len(restored['messages']) == 2
    assert client.put('/api/data/2026-01-02',json={'value':9,'memo':'<script>bad()</script>'}).status_code == 200
    second = client.post('/api/chat',json={'message':'바뀐 합계는?','conversation_id':key})
    assert second.status_code == 200
    assert second.json()['conversation_id'] == key
    assert '9회' in second.json()['answer']
    assert len(gateway.calls[-1][1]) == 3
    assert len(client.get('/api/conversations/'+key).json()['messages']) == 4
    assert client.delete('/api/conversations/'+key).status_code == 204
    assert client.get('/api/conversations/'+key).status_code == 404
    assert client.delete('/api/data/2026-01-02').status_code == 204
    assert client.get('/api/data/summary').json()['metrics']['total'] == 0
