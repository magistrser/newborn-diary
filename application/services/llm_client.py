import json
import re
from typing import Any

from openai import AsyncOpenAI

from settings import LLMSettings

_THINK_RE = re.compile(r'<think>.*?</think>', re.DOTALL)


def _strip_thinking(text: str) -> str:
    return _THINK_RE.sub('', text).strip()


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
        messages: list[dict],
        max_tokens: int | None = None,
    ) -> Any:
        response = await self._client.chat.completions.create(
            model=self._settings.model,
            messages=messages,
            max_tokens=max_tokens or self._settings.parser_max_tokens,
            temperature=0.1,
        )
        content = _strip_thinking(response.choices[0].message.content or '{}')
        return json.loads(content or '{}')

    async def chat_text(
        self,
        messages: list[dict],
        max_tokens: int | None = None,
    ) -> str:
        response = await self._client.chat.completions.create(
            model=self._settings.model,
            messages=messages,
            max_tokens=max_tokens or self._settings.qa_max_tokens,
            temperature=0.3,
        )
        return _strip_thinking(response.choices[0].message.content or '')
