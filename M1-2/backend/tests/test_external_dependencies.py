from types import SimpleNamespace as NS
from unittest.mock import Mock
import pytest
from app import dependencies
from app.config import Settings
from app.ports import GenerationUnavailable


def test_openai_client_is_lazy_bounded_and_closed(monkeypatch):
    import openai
    client = Mock()
    client.chat.completions.create.return_value = NS(choices=[NS(finish_reason='stop', message=NS(content='answer', refusal=None))])
    constructor = Mock(return_value=client)
    monkeypatch.setattr(openai, 'OpenAI', constructor)
    monkeypatch.setattr(dependencies, 'get_settings', lambda: Settings(allowed_origins=(), openai_api_key='test-key', openai_base_url='https://gateway.example/v1', openai_model='gpt-5-mini'))
    gateway = dependencies.get_chat_gateway()
    constructor.assert_not_called()
    assert gateway.complete('rules', []) == 'answer'
    assert client.chat.completions.create.call_args.kwargs['max_completion_tokens'] == 2048
    constructor.assert_called_once_with(api_key='test-key', base_url='https://gateway.example/v1', timeout=45, max_retries=0)
    client.close.assert_called_once_with()


def test_gateway_factory_error_hides_secret(monkeypatch):
    import openai
    monkeypatch.setattr(dependencies, 'get_settings', lambda: Settings(allowed_origins=(), openai_api_key='test-key', openai_model='gpt-5-mini'))
    constructor = Mock(side_effect=ValueError('SECRET'))
    monkeypatch.setattr(openai, 'OpenAI', constructor)
    gateway = dependencies.get_chat_gateway()
    with pytest.raises(GenerationUnavailable) as error:
        gateway.complete('rules', [])
    assert 'SECRET' not in str(error.value)


def test_failed_generation_also_closes_client(monkeypatch):
    import openai
    client = Mock()
    client.chat.completions.create.side_effect = RuntimeError('SECRET')
    monkeypatch.setattr(openai, 'OpenAI', Mock(return_value=client))
    monkeypatch.setattr(dependencies, 'get_settings', lambda: Settings(allowed_origins=(), openai_api_key='test-key', openai_model='gpt-5-mini'))
    with pytest.raises(GenerationUnavailable): dependencies.get_chat_gateway().complete('rules', [])
    client.close.assert_called_once_with()


@pytest.mark.parametrize('has_key', [False, True])
def test_empty_data_chat_saves_without_gateway_configuration(app, client, monkeypatch, has_key):
    import openai
    constructor = Mock(side_effect=RuntimeError('SECRET'))
    monkeypatch.setattr(openai, 'OpenAI', constructor)
    monkeypatch.setattr(dependencies, 'get_settings', lambda: Settings(allowed_origins=(), openai_api_key='test-key' if has_key else None, openai_model='gpt-5-mini'))
    saved = []
    def create(payload):
        saved.append(payload)
        return NS(id='saved')
    app.dependency_overrides.update({
        dependencies.get_data_repository: lambda: NS(list_records=lambda: []),
        dependencies.get_conversation_repository: lambda: NS(create=create),
    })
    response = client.post('/api/chat', json={'message': '질문'})
    assert response.status_code == 200
    assert response.json() == {'conversation_id': 'saved', 'answer': '데이터가 없습니다. 일별 기록을 추가해주세요.'}
    assert saved[0].messages[1].content == response.json()['answer']
    constructor.assert_not_called()


def test_configured_conversation_provider_reuses_firestore_factory(monkeypatch):
    from app.conversations.repository import FirestoreConversationRepository
    client = Mock()
    factory = Mock(return_value=client)
    monkeypatch.setattr(dependencies, '_build_firestore_client', factory)
    monkeypatch.setattr(dependencies, 'get_settings', lambda: Settings(allowed_origins=(), firebase_project_id='test-project', google_application_credentials='/test/path'))
    repository = dependencies.get_conversation_repository()
    assert isinstance(repository, FirestoreConversationRepository)
    assert repository.client is client
    factory.assert_called_once_with('test-project', '/test/path')
    client.collection.assert_called_once_with('conversations')


def test_conversation_provider_factory_failure_is_sanitized(monkeypatch):
    from app.ports import StorageUnavailable
    monkeypatch.setattr(dependencies, '_build_firestore_client', Mock(side_effect=ValueError('SECRET')))
    monkeypatch.setattr(dependencies, 'get_settings', lambda: Settings(allowed_origins=(), firebase_project_id='test-project', google_application_credentials='/test/path'))
    with pytest.raises(StorageUnavailable) as error: dependencies.get_conversation_repository()
    assert 'SECRET' not in str(error.value)
