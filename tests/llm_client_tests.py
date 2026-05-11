from types import SimpleNamespace
from typing import Any

import pytest

from application.dto import LLMTokenLimitError
from infrastructure.llm_client import LLMClient
from settings import LLMSettings


class _FakeCompletions:
    def __init__(self, response: Any) -> None:
        self._response = response
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return self._response


class _FakeOpenAIClient:
    def __init__(self, response: Any) -> None:
        self.completions = _FakeCompletions(response)
        self.chat = SimpleNamespace(completions=self.completions)


def _response(
    *,
    finish_reason: str,
    content: str = '',
    tool_calls: list[Any] | None = None,
) -> Any:
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    choice = SimpleNamespace(finish_reason=finish_reason, message=message)
    return SimpleNamespace(choices=[choice])


def _client(response: Any, max_tokens: int = 4096) -> tuple[LLMClient, _FakeOpenAIClient]:
    client = LLMClient(
        LLMSettings(
            base_url='http://llm.local/v1',
            api_key='not-needed',
            model='test-model',
            max_tokens=max_tokens,
        )
    )
    fake = _FakeOpenAIClient(response)
    client._client = fake  # type: ignore[assignment]  # pylint: disable=protected-access
    return client, fake


async def test_chat_text_raises_when_model_exhausts_default_token_limit() -> None:
    client, _fake = _client(_response(finish_reason='length'), max_tokens=4096)

    with pytest.raises(LLMTokenLimitError, match='max_tokens=4096'):
        await client.chat_text([{'role': 'user', 'content': 'hello'}])


async def test_chat_with_tools_raises_when_model_exhausts_explicit_token_limit() -> None:
    client, _fake = _client(_response(finish_reason='length'), max_tokens=4096)

    with pytest.raises(LLMTokenLimitError, match='max_tokens=128'):
        await client.chat_with_tools(
            [{'role': 'user', 'content': 'hello'}],
            [],
            max_tokens=128,
        )


async def test_chat_json_returns_content_when_finish_reason_is_not_length() -> None:
    client, fake = _client(_response(finish_reason='stop', content='{"ok": true}'))

    result = await client.chat_json([{'role': 'user', 'content': 'hello'}])

    assert result == {'ok': True}
    assert fake.completions.calls[0]['max_tokens'] == 4096
