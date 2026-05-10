from unittest.mock import AsyncMock, MagicMock

import pytest

from application.services.qa_router import QARouter
from application.services.qa_service import AnswerResult


def _make_result(answer: str = 'ok') -> AnswerResult:
    import uuid
    return AnswerResult(answer=answer, used_window={}, sources=[])


async def test_routes_stats_to_agentic() -> None:
    llm = AsyncMock()
    llm.chat_json = AsyncMock(return_value={'mode': 'stats'})

    narrative = AsyncMock()
    agentic = AsyncMock()
    agentic.answer = AsyncMock(return_value=_make_result('stats answer'))

    router = QARouter(llm, narrative, agentic)
    result = await router.answer('сколько кормлений вчера?')

    agentic.answer.assert_called_once()
    narrative.answer.assert_not_called()
    assert result.used_window.get('route') == 'stats'


async def test_routes_narrative_to_qa_service() -> None:
    llm = AsyncMock()
    llm.chat_json = AsyncMock(return_value={'mode': 'narrative'})

    narrative = AsyncMock()
    narrative.answer = AsyncMock(return_value=_make_result('narrative answer'))
    agentic = AsyncMock()

    router = QARouter(llm, narrative, agentic)
    result = await router.answer('что было вчера вечером?')

    narrative.answer.assert_called_once()
    agentic.answer.assert_not_called()
    assert result.used_window.get('route') == 'narrative'


async def test_unknown_mode_falls_back_to_narrative() -> None:
    llm = AsyncMock()
    llm.chat_json = AsyncMock(return_value={'mode': 'unknown_value'})

    narrative = AsyncMock()
    narrative.answer = AsyncMock(return_value=_make_result())
    agentic = AsyncMock()

    router = QARouter(llm, narrative, agentic)
    await router.answer('вопрос')

    narrative.answer.assert_called_once()
    agentic.answer.assert_not_called()


async def test_classifier_error_falls_back_to_narrative() -> None:
    llm = AsyncMock()
    llm.chat_json = AsyncMock(side_effect=Exception('LLM error'))

    narrative = AsyncMock()
    narrative.answer = AsyncMock(return_value=_make_result())
    agentic = AsyncMock()

    router = QARouter(llm, narrative, agentic)
    await router.answer('вопрос')

    narrative.answer.assert_called_once()
    agentic.answer.assert_not_called()
