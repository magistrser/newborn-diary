import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from pydantic import ValidationError

from application.dto import (
    CreateEventCommand,
    EventNotFoundError,
    FromTextCommand,
    ListEventsQuery,
    ParserConfig,
    PatchEventCommand,
    PayloadValidationError,
)
from application.ports import EventRepositoryPort, TransactionPort
from application.services.event_parser import EventParser
from domain.event import Event, validate_payload_for_type


class EventUseCase:
    def __init__(
        self,
        repo: EventRepositoryPort,
        parser: EventParser,
        parser_config: ParserConfig,
        transaction: TransactionPort | None = None,
        id_factory: Callable[[], uuid.UUID] = uuid.uuid4,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repo = repo
        self._parser = parser
        self._parser_config = parser_config
        self._transaction = transaction
        self._id_factory = id_factory
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    async def create_event(self, command: CreateEventCommand) -> Event:
        event = Event(
            id=self._id_factory(),
            occurred_at=command.occurred_at,
            recorded_at=self._clock(),
            type=command.event_type,
            payload=command.payload,
            raw_text=command.raw_text,
            source_type=command.source_type,
            source_message_id=command.source_message_id,
            source_chat_id=command.source_chat_id,
            parser_version='manual',
        )
        saved = await self._repo.save(event)
        await self._commit()
        return saved

    async def list_events(self, query: ListEventsQuery) -> list[Event]:
        return await self._repo.list(
            from_dt=query.from_dt,
            to_dt=query.to_dt,
            types=query.event_types,
            limit=query.limit,
            order_asc=query.order_asc,
        )

    async def get_event(self, event_id: uuid.UUID) -> Event:
        event = await self._repo.get_by_id(event_id)
        if event is None:
            raise EventNotFoundError('Event not found')
        return event

    async def patch_event(self, command: PatchEventCommand) -> Event:
        existing = await self._repo.get_by_id(command.event_id)
        if existing is None:
            raise EventNotFoundError('Event not found')

        new_type = command.event_type if command.event_type is not None else existing.type
        new_payload = command.payload if command.payload is not None else existing.payload
        try:
            validate_payload_for_type(new_type, new_payload)
        except ValidationError as exc:
            errors: list[dict[str, Any]] = [dict(error) for error in exc.errors()]
            raise PayloadValidationError(errors) from exc

        persist_payload = (
            new_payload
            if command.payload is not None or command.event_type is not None
            else None
        )
        updated = await self._repo.update(
            command.event_id,
            occurred_at=command.occurred_at,
            event_type=command.event_type,
            payload=persist_payload,
        )
        if updated is None:
            raise EventNotFoundError('Event not found')
        await self._commit()
        return updated

    async def delete_event(self, event_id: uuid.UUID) -> None:
        deleted = await self._repo.delete(event_id)
        if not deleted:
            raise EventNotFoundError('Event not found')
        await self._commit()

    async def create_events_from_text(self, command: FromTextCommand) -> list[Event]:
        if command.source_chat_id is not None and command.source_message_id is not None:
            existing = await self._repo.list_by_source_message(
                source_chat_id=command.source_chat_id,
                source_message_id=command.source_message_id,
            )
            if existing:
                return existing

        context_window_start = command.occurred_at - timedelta(
            hours=self._parser_config.context_window_hours
        )
        recent = await self._repo.list(
            from_dt=context_window_start,
            to_dt=command.occurred_at,
            limit=50,
            order_asc=True,
        )
        events = await self._parser.parse_message(
            text=command.text,
            message_date=command.occurred_at,
            recent_events=recent,
            source_type=command.source_type,
            source_message_id=command.source_message_id,
            source_chat_id=command.source_chat_id,
        )
        saved = await self._repo.save_many(events)
        await self._commit()
        return saved

    async def _commit(self) -> None:
        if self._transaction is not None:
            await self._transaction.commit()
