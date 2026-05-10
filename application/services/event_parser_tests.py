from datetime import datetime, timezone
from unittest.mock import AsyncMock

from application.services.event_parser import EventParser
from domain.event import EventType


_TS = datetime(2026, 5, 9, 11, 42, 56, tzinfo=timezone.utc)


async def test_parse_feed_breast_right(event_parser: EventParser, mock_llm_fixture: AsyncMock) -> None:
    mock_llm_fixture.chat_json = AsyncMock(return_value={
        'events': [{'type': 'feed_breast', 'occurred_at': '2026-05-09T11:42:56Z', 'payload': {'side': 'right'}}]
    })
    events = await event_parser.parse_message('Правая', _TS, [])
    assert len(events) == 1
    assert events[0].type == EventType.feed_breast
    assert events[0].payload['side'] == 'right'


async def test_parse_diaper_and_feed(event_parser: EventParser, mock_llm_fixture: AsyncMock) -> None:
    mock_llm_fixture.chat_json = AsyncMock(return_value={
        'events': [
            {'type': 'diaper', 'occurred_at': '2026-05-09T13:07:48Z', 'payload': {'kind': 'unknown'}},
            {'type': 'feed_breast', 'occurred_at': '2026-05-09T13:07:48Z', 'payload': {'side': 'left'}},
        ]
    })
    events = await event_parser.parse_message('Подгузник\nЛевая', _TS, [])
    assert len(events) == 2
    assert events[0].type == EventType.diaper
    assert events[1].type == EventType.feed_breast


async def test_llm_invalid_json_falls_back_to_note(event_parser: EventParser, mock_llm_fixture: AsyncMock) -> None:
    mock_llm_fixture.chat_json = AsyncMock(return_value={'invalid': True})
    events = await event_parser.parse_message('некий текст', _TS, [])
    assert len(events) == 1
    assert events[0].type == EventType.note


async def test_llm_empty_events_returns_note(event_parser: EventParser, mock_llm_fixture: AsyncMock) -> None:
    mock_llm_fixture.chat_json = AsyncMock(return_value={'events': []})
    events = await event_parser.parse_message('привет', _TS, [])
    assert len(events) == 1
    assert events[0].type == EventType.note
