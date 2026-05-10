import json
import re
from typing import Any

from openai import APIConnectionError, AsyncOpenAI

from application.dto import AssistantMessage, ToolCall, ToolFunctionCall
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
        content = _extract_json(response.choices[0].message.content or '{}')
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
        return _strip_thinking(response.choices[0].message.content or '')

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
        msg = response.choices[0].message
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
