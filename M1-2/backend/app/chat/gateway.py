"""Small synchronous adapter for Chat Completions."""
from ..models import MessageInput
from ..ports import GenerationUnavailable


class OpenAIChatGateway:
    def __init__(self, client, model: str, max_output_tokens: int):
        self.client = client
        self.model = model
        self.max_output_tokens = max_output_tokens

    def complete(self, system: str, messages: list[MessageInput]) -> str:
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                max_completion_tokens=self.max_output_tokens,
                messages=[{'role': 'system', 'content': system}] +
                         [m.model_dump() for m in messages],
            )
            choice = response.choices[0]
            answer = choice.message.content
            if (choice.finish_reason != 'stop' or getattr(choice.message, 'refusal', None)
                    or not isinstance(answer, str) or not answer.strip()):
                raise ValueError('Incomplete response')
            return answer
        except Exception:
            raise GenerationUnavailable('Answer generation is temporarily unavailable.') from None
