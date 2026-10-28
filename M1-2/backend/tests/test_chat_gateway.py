from types import SimpleNamespace as NS
import pytest
from app.chat.gateway import OpenAIChatGateway
from app.models import MessageInput
from app.ports import GenerationUnavailable
class Client:
    def __init__(self, response):
        self.response = response
        self.chat = NS(completions=NS(create=self.create))
    def create(self, **kwargs):
        self.kwargs = kwargs
        if isinstance(self.response, Exception): raise self.response
        return self.response
def result(content='answer', finish_reason='stop'):
    return NS(choices=[NS(message=NS(content=content, refusal=None), finish_reason=finish_reason)])
def test_chat_completions_omits_unsupported_reasoning_effort():
    client = Client(result())
    assert OpenAIChatGateway(client, 'gpt-5-mini', 512).complete('rules', [MessageInput(role='user', content='question')]) == 'answer'
    assert 'reasoning_effort' not in client.kwargs
    assert client.kwargs == dict(model='gpt-5-mini', max_completion_tokens=512,
        messages=[{'role':'system', 'content':'rules'}, {'role':'user', 'content':'question'}])
@pytest.mark.parametrize('response', [result(''), result('  '), result(None), result('partial', 'length'),
    result('blocked', 'content_filter'), NS(choices=[]), NS(), RuntimeError('secret'), result(['malformed'])])
def test_bad_generation_is_unavailable(response):
    with pytest.raises(GenerationUnavailable, match='Answer generation is temporarily unavailable'):
        OpenAIChatGateway(Client(response), 'gpt-5-mini', 512).complete('rules', [])
