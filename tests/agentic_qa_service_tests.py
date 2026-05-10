import json
import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.ext.asyncio import AsyncSession

from application.services.agentic_qa_service import AgenticQAService
from domain.event import Event, EventType
from infrastructure.repositories.event_repository import SqlEventRepository
from settings import QASettings


_DEFAULT_SETTINGS = QASettings(
    max_tool_iterations=5,
    sql_row_cap=10,
    sql_statement_timeout_ms=3000,
    user_timezone='Europe/Moscow',
    agent_max_tokens=512,
)


def _make_event(**kwargs: Any) -> Event:
    defaults: dict[str, Any] = dict(
        id=uuid.uuid4(),
        occurred_at=datetime(2026, 5, 10, 10, 0, 0, tzinfo=timezone.utc),
        recorded_at=datetime(2026, 5, 10, 10, 0, 0, tzinfo=timezone.utc),
        type=EventType.diaper,
        payload={'kind': 'pee'},
        source_type='test',
    )
    defaults.update(kwargs)
    return Event(**defaults)


def _tool_call_msg(query: str, call_id: str = 'call_1') -> MagicMock:
    tc = MagicMock()
    tc.id = call_id
    tc.function.name = 'execute_sql'
    tc.function.arguments = json.dumps({'query': query})
    msg = MagicMock()
    msg.content = None
    msg.tool_calls = [tc]
    return msg


def _text_msg(content: str) -> MagicMock:
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = None
    return msg


async def test_happy_path_aggregate(db_session: AsyncSession) -> None:
    """LLM issues one SQL call then returns a text answer."""
    repo = SqlEventRepository(db_session)
    event_id = uuid.uuid4()
    await repo.save(_make_event(id=event_id))

    llm = AsyncMock()
    llm.chat_with_tools = AsyncMock(side_effect=[
        _tool_call_msg("SELECT count(*) AS n FROM events WHERE type='diaper'"),
        _text_msg('Было 1 подгузник.'),
    ])

    service = AgenticQAService(llm, db_session, _DEFAULT_SETTINGS)
    result = await service.answer('сколько подгузников сегодня?')

    assert '1' in result.answer or 'подгузник' in result.answer
    assert result.used_window['mode'] == 'agentic'
    assert result.used_window['iterations'] == 2
    assert len(result.used_window['queries']) == 1
    assert result.sources == []


async def test_error_retry(db_session: AsyncSession) -> None:
    """LLM issues bad SQL, gets error back, fixes it, then answers."""
    llm = AsyncMock()
    llm.chat_with_tools = AsyncMock(side_effect=[
        _tool_call_msg("SELECT count(*) FROM nonexistent_table", 'call_1'),
        _tool_call_msg("SELECT count(*) FROM events", 'call_2'),
        _text_msg('Ответ: 0 событий.'),
    ])

    service = AgenticQAService(llm, db_session, _DEFAULT_SETTINGS)
    result = await service.answer('тест')

    assert result.used_window['iterations'] == 3
    assert len(result.used_window['queries']) == 2

    # Verify the error from the first call was passed back to the LLM
    call_args_list = llm.chat_with_tools.call_args_list
    second_call_messages = call_args_list[1][0][0]
    tool_result_msgs = [m for m in second_call_messages if m.get('role') == 'tool']
    assert tool_result_msgs
    content = json.loads(tool_result_msgs[0]['content'])
    assert 'error' in content


async def test_iteration_cap(db_session: AsyncSession) -> None:
    """When LLM keeps calling tools, service forces a text answer."""
    llm = AsyncMock()
    llm.chat_with_tools = AsyncMock(
        return_value=_tool_call_msg("SELECT 1 FROM events LIMIT 1")
    )
    llm.chat_text = AsyncMock(return_value='Не удалось ответить.')

    settings = QASettings(max_tool_iterations=2, sql_row_cap=10,
                          sql_statement_timeout_ms=3000,
                          user_timezone='Europe/Moscow', agent_max_tokens=256)
    service = AgenticQAService(llm, db_session, settings)
    result = await service.answer('тест')

    assert llm.chat_with_tools.call_count == 2
    assert llm.chat_text.call_count == 1
    assert result.used_window['iterations'] == 2


async def test_sources_populated_from_id_column(db_session: AsyncSession) -> None:
    """When LLM SELECTs id column, those UUIDs appear in sources."""
    repo = SqlEventRepository(db_session)
    event = await repo.save(_make_event())

    llm = AsyncMock()
    llm.chat_with_tools = AsyncMock(side_effect=[
        _tool_call_msg(f"SELECT id, occurred_at FROM events WHERE id = '{event.id}'"),
        _text_msg('Вот события.'),
    ])

    service = AgenticQAService(llm, db_session, _DEFAULT_SETTINGS)
    result = await service.answer('покажи подгузники')

    assert event.id in result.sources


async def test_sql_validation_rejection_returned_as_error(db_session: AsyncSession) -> None:
    """A query rejected by the validator is returned as {error: ...} to LLM."""
    rejected_sql = "DELETE FROM events"
    captured_messages: list[list[dict[str, Any]]] = []

    async def side_effect(messages: list[dict[str, Any]], _tools: list[Any], **_kwargs: Any) -> MagicMock:
        captured_messages.append(list(messages))
        if len(captured_messages) == 1:
            return _tool_call_msg(rejected_sql)
        return _text_msg('Done.')

    llm = AsyncMock()
    llm.chat_with_tools = AsyncMock(side_effect=side_effect)

    service = AgenticQAService(llm, db_session, _DEFAULT_SETTINGS)
    await service.answer('удали всё')

    second_call_messages = captured_messages[1]
    tool_msgs = [m for m in second_call_messages if m.get('role') == 'tool']
    assert tool_msgs
    content = json.loads(tool_msgs[0]['content'])
    assert 'error' in content
    assert 'rejected' in content['error']
