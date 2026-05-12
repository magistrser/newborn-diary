import builtins
import uuid
from datetime import datetime, timezone
from typing import Any

import pytest

from application.dto import (
    FromTextCommand,
    ParserConfig,
    PatchEventCommand,
    PayloadValidationError,
)
from application.use_cases import EventUseCase
from domain.event import Event, EventType


class InMemoryEventRepository:
    def __init__(self, events: list[Event] | None = None) -> None:
        self.events = list(events or [])
        self.saved_many: list[Event] = []
        self.list_calls: list[dict[str, Any]] = []
        self.update_calls: list[dict[str, Any]] = []

    async def save(self, event: Event) -> Event:
        self.events.append(event)
        return event

    async def save_many(self, events: list[Event]) -> list[Event]:
        self.saved_many.extend(events)
        self.events.extend(events)
        return events

    async def get_by_id(self, event_id: uuid.UUID) -> Event | None:
        return next((event for event in self.events if event.id == event_id), None)

    async def update(
        self,
        event_id: uuid.UUID,
        *,
        occurred_at: datetime | None = None,
        event_type: EventType | None = None,
        payload: dict[str, Any] | None = None,
    ) -> Event | None:
        self.update_calls.append({
            'event_id': event_id,
            'occurred_at': occurred_at,
            'event_type': event_type,
            'payload': payload,
        })
        event = await self.get_by_id(event_id)
        if event is None:
            return None
        updated = event.model_copy(update={
            'occurred_at': occurred_at or event.occurred_at,
            'type': event_type or event.type,
            'payload': payload if payload is not None else event.payload,
        })
        self.events = [updated if item.id == event_id else item for item in self.events]
        return updated

    async def delete(self, event_id: uuid.UUID) -> bool:
        before = len(self.events)
        self.events = [event for event in self.events if event.id != event_id]
        return len(self.events) != before

    async def list(
        self,
        from_dt: datetime | None = None,
        to_dt: datetime | None = None,
        types: list[EventType] | None = None,
        limit: int = 200,
        order_asc: bool = True,
    ) -> builtins.list[Event]:
        self.list_calls.append({
            'from_dt': from_dt,
            'to_dt': to_dt,
            'types': types,
            'limit': limit,
            'order_asc': order_asc,
        })
        return self.events[:limit]

    async def exists_by_source(
        self,
        source_type: str,
        source_chat_id: int,
        source_message_id: str,
    ) -> bool:
        return bool([
            event for event in self.events
            if event.source_type == source_type
            and event.source_chat_id == source_chat_id
            and event.source_message_id == source_message_id
        ])

    async def list_by_source_message(
        self,
        source_chat_id: int,
        source_message_id: str,
    ) -> builtins.list[Event]:
        return [
            event for event in self.events
            if event.source_chat_id == source_chat_id
            and event.source_message_id == source_message_id
        ]


class StubParser:
    def __init__(self, parsed_events: list[Event] | None = None) -> None:
        self.parsed_events = parsed_events or []
        self.calls: list[dict[str, Any]] = []

    async def parse_message(
        self,
        text: str,
        message_date: datetime,
        recent_events: list[Event],
        source_type: str = 'telegram_live',
        source_message_id: str | None = None,
        source_chat_id: int | None = None,
    ) -> list[Event]:
        self.calls.append({
            'text': text,
            'message_date': message_date,
            'recent_events': recent_events,
            'source_type': source_type,
            'source_message_id': source_message_id,
            'source_chat_id': source_chat_id,
        })
        return self.parsed_events


class CountingTransaction:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


def _make_event(**overrides: Any) -> Event:
    data: dict[str, Any] = {
        'id': uuid.uuid4(),
        'occurred_at': datetime(2026, 5, 10, 10, tzinfo=timezone.utc),
        'recorded_at': datetime(2026, 5, 10, 10, tzinfo=timezone.utc),
        'type': EventType.sleep_start,
        'payload': {},
        'source_type': 'test',
    }
    data.update(overrides)
    return Event(**data)


async def test_from_text_returns_existing_message_events_without_parsing() -> None:
    existing = _make_event(
        source_type='telegram_export',
        source_chat_id=123,
        source_message_id='42',
    )
    repo = InMemoryEventRepository([existing])
    parser = StubParser()
    tx = CountingTransaction()
    use_case = EventUseCase(repo, parser, ParserConfig(), tx)  # type: ignore[arg-type]

    result = await use_case.create_events_from_text(FromTextCommand(
        text='Заснул',
        occurred_at=existing.occurred_at,
        source_type='telegram_live',
        source_chat_id=123,
        source_message_id='42',
    ))

    assert result == [existing]
    assert not parser.calls
    assert tx.commits == 0


async def test_from_text_passes_recent_context_window_to_parser() -> None:
    occurred_at = datetime(2026, 5, 10, 12, tzinfo=timezone.utc)
    recent = _make_event(occurred_at=datetime(2026, 5, 10, 11, tzinfo=timezone.utc))
    parsed = _make_event(occurred_at=occurred_at, source_type='telegram_live')
    repo = InMemoryEventRepository([recent])
    parser = StubParser([parsed])
    tx = CountingTransaction()
    use_case = EventUseCase(repo, parser, ParserConfig(context_window_hours=6), tx)  # type: ignore[arg-type]

    result = await use_case.create_events_from_text(FromTextCommand(
        text='Подгузник',
        occurred_at=occurred_at,
    ))

    assert result == [parsed]
    assert repo.list_calls[0]['from_dt'] == datetime(2026, 5, 10, 6, tzinfo=timezone.utc)
    assert parser.calls[0]['recent_events'] == [recent]
    assert tx.commits == 1


async def test_patch_rejects_invalid_payload_for_new_type_before_update() -> None:
    event = _make_event(type=EventType.sleep_start, payload={})
    repo = InMemoryEventRepository([event])
    parser = StubParser()
    tx = CountingTransaction()
    use_case = EventUseCase(repo, parser, ParserConfig(), tx)  # type: ignore[arg-type]

    with pytest.raises(PayloadValidationError):
        await use_case.patch_event(PatchEventCommand(
            event_id=event.id,
            event_type=EventType.feed_breast,
        ))

    assert not repo.update_calls
    assert tx.commits == 0
