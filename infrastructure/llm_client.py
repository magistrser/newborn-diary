import json
import re
from typing import Any

from openai import APIConnectionError, AsyncOpenAI

from application.dto import AssistantMessage, LLMTokenLimitError, ToolCall, ToolFunctionCall
from settings import LLMSettings

_THINK_RE = re.compile(r'<think>.*?</think>|<\|channel>.*?<channel\|>', re.DOTALL)
_CODE_FENCE_RE = re.compile(r'^```[a-z]*\n?(.*?)\n?```$', re.DOTALL)


def _strip_thinking(text: str) -> str:
    return _THINK_RE.sub('', text).strip()


def _extract_json(text: str) -> str:
    text = _strip_thinking(text)
    match = _CODE_FENCE_RE.match(text)
    return match.group(1).strip() if match else text


class LLMClient:
    def __init__(self, llm_settings: LLMSettings) -> None:
        self._settings = llm_settings
        self._client = AsyncOpenAI(
            base_url=llm_settings.base_url,
            api_key=llm_settings.api_key,
            timeout=llm_settings.request_timeout_sec,
        )

    def _connection_error(self, exc: APIConnectionError) -> RuntimeError:
        return RuntimeError(
            'Could not connect to OpenAI-compatible API '
            f'at {self._settings.base_url!r} using model {self._settings.model!r}. '
            'Check that the local LLM server is running and reachable from this process.'
        )

    def _raise_if_token_limit_reached(
        self,
        finish_reason: str | None,
        *,
        max_tokens: int | None,
    ) -> None:
        if finish_reason != 'length':
            return
        effective_max_tokens = max_tokens or self._settings.max_tokens
        raise LLMTokenLimitError(
            'LLM response stopped because the max_tokens limit was exhausted '
            f'(model={self._settings.model!r}, max_tokens={effective_max_tokens}). '
            'Increase llm.max_tokens or the task-specific llm.tasks.<task>.max_tokens setting.'
        )

    async def chat_json(
        self,
        messages: list[dict[str, Any]],
        max_tokens: int | None = None,
    ) -> Any:
        try:
            response = await self._client.chat.completions.create(
                model=self._settings.model,
                messages=messages,  # type: ignore[arg-type]
                max_tokens=max_tokens or self._settings.max_tokens,
                temperature=0.1,
            )
        except APIConnectionError as exc:
            raise self._connection_error(exc) from exc
        choice = response.choices[0]
        self._raise_if_token_limit_reached(choice.finish_reason, max_tokens=max_tokens)
        content = _extract_json(choice.message.content or '{}')
        return json.loads(content or '{}')

    async def chat_text(
        self,
        messages: list[dict[str, Any]],
        max_tokens: int | None = None,
    ) -> str:
        try:
            response = await self._client.chat.completions.create(
                model=self._settings.model,
                messages=messages,  # type: ignore[arg-type]
                max_tokens=max_tokens or self._settings.max_tokens,
                temperature=0.3,
            )
        except APIConnectionError as exc:
            raise self._connection_error(exc) from exc
        choice = response.choices[0]
        self._raise_if_token_limit_reached(choice.finish_reason, max_tokens=max_tokens)
        return _strip_thinking(choice.message.content or '')

    async def chat_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        max_tokens: int | None = None,
    ) -> AssistantMessage:
        try:
            response = await self._client.chat.completions.create(  # type: ignore[call-overload]
                model=self._settings.model,
                messages=messages,  # type: ignore[arg-type]
                tools=tools,  # type: ignore[arg-type]
                tool_choice='auto',
                max_tokens=max_tokens or self._settings.max_tokens,
                temperature=0.2,
            )
        except APIConnectionError as exc:
            raise self._connection_error(exc) from exc
        choice = response.choices[0]
        self._raise_if_token_limit_reached(choice.finish_reason, max_tokens=max_tokens)
        msg = choice.message
        content = _strip_thinking(msg.content) if msg.content else None
        tool_calls = None
        if msg.tool_calls:
            tool_calls = [
                ToolCall(
                    id=call.id,
                    function=ToolFunctionCall(
                        name=call.function.name,  # type: ignore[union-attr]
                        arguments=call.function.arguments,  # type: ignore[union-attr]
                    ),
                )
                for call in msg.tool_calls
            ]
        return AssistantMessage(content=content, tool_calls=tool_calls)
