import json
import re
from typing import Any

from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessage

from settings import LLMSettings

_THINK_RE = re.compile(r'<think>.*?</think>|<\|channel>.*?<channel\|>', re.DOTALL)
_CODE_FENCE_RE = re.compile(r'^```[a-z]*\n?(.*?)\n?```$', re.DOTALL)


def _strip_thinking(text: str) -> str:
    return _THINK_RE.sub('', text).strip()


def _extract_json(text: str) -> str:
    text = _strip_thinking(text)
    m = _CODE_FENCE_RE.match(text)
    return m.group(1).strip() if m else text


class LLMClient:

    def __init__(self, llm_settings: LLMSettings) -> None:
        self._settings = llm_settings
        self._client = AsyncOpenAI(
            base_url=llm_settings.base_url,
            api_key=llm_settings.api_key,
            timeout=llm_settings.request_timeout_sec,
        )

    async def chat_json(
        self,
        messages: list[dict[str, Any]],
        max_tokens: int | None = None,
    ) -> Any:
        response = await self._client.chat.completions.create(
            model=self._settings.model,
            messages=messages,  # type: ignore[arg-type]
            max_tokens=max_tokens or self._settings.max_tokens,
            temperature=0.1,
        )
        content = _extract_json(response.choices[0].message.content or '{}')
        return json.loads(content or '{}')

    async def chat_text(
        self,
        messages: list[dict[str, Any]],
        max_tokens: int | None = None,
    ) -> str:
        response = await self._client.chat.completions.create(
            model=self._settings.model,
            messages=messages,  # type: ignore[arg-type]
            max_tokens=max_tokens or self._settings.max_tokens,
            temperature=0.3,
        )
        return _strip_thinking(response.choices[0].message.content or '')

    async def chat_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        max_tokens: int | None = None,
    ) -> ChatCompletionMessage:
        response = await self._client.chat.completions.create(  # type: ignore[call-overload]
            model=self._settings.model,
            messages=messages,  # type: ignore[arg-type]
            tools=tools,  # type: ignore[arg-type]
            tool_choice='auto',
            max_tokens=max_tokens or self._settings.max_tokens,
            temperature=0.2,
        )
        msg = response.choices[0].message
        if msg.content:
            msg.content = _strip_thinking(msg.content)
        return msg
