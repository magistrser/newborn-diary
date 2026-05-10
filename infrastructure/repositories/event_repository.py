import builtins
from datetime import datetime
from uuid import UUID

from sqlalchemy import delete as sa_delete, select, update as sa_update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from application.repositories.event_repository import AbstractEventRepository
from domain.event import Event, EventType
from infrastructure.models.event import EventModel


def _to_domain(row: EventModel) -> Event:
    return Event.model_validate(row)


class SqlEventRepository(AbstractEventRepository):

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, event: Event) -> Event:
        row = EventModel(
            id=event.id,
            occurred_at=event.occurred_at,
            type=event.type,
            payload=event.payload,
            raw_text=event.raw_text,
            source_type=event.source_type,
            source_message_id=event.source_message_id,
            source_chat_id=event.source_chat_id,
            source_event_index=event.source_event_index,
            parser_version=event.parser_version,
        )
        self._session.add(row)
        await self._session.flush()
        await self._session.refresh(row)
        return _to_domain(row)

    async def save_many(self, events: list[Event]) -> list[Event]:
        if not events:
            return []
        stmt = (
            insert(EventModel)
            .values([
                dict(
                    id=e.id,
                    occurred_at=e.occurred_at,
                    type=e.type,
                    payload=e.payload,
                    raw_text=e.raw_text,
                    source_type=e.source_type,
                    source_message_id=e.source_message_id,
                    source_chat_id=e.source_chat_id,
                    source_event_index=e.source_event_index,
                    parser_version=e.parser_version,
                )
                for e in events
            ])
            .on_conflict_do_nothing(constraint='uq_events_source')
            .returning(EventModel)
        )
        result = await self._session.execute(stmt)
        return [_to_domain(row) for row in result.scalars()]

    async def get_by_id(self, event_id: UUID) -> Event | None:
        stmt = select(EventModel).where(EventModel.id == event_id)
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        return _to_domain(row) if row else None

    async def update(
        self,
        event_id: UUID,
        *,
        occurred_at: datetime | None = None,
        event_type: EventType | None = None,
        payload: dict | None = None,
    ) -> Event | None:
        values: dict = {}
        if occurred_at is not None:
            values['occurred_at'] = occurred_at
        if event_type is not None:
            values['type'] = event_type
        if payload is not None:
            values['payload'] = payload
        if not values:
            return await self.get_by_id(event_id)
        stmt = (
            sa_update(EventModel)
            .where(EventModel.id == event_id)
            .values(**values)
            .returning(EventModel)
        )
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        return _to_domain(row) if row else None

    async def delete(self, event_id: UUID) -> bool:
        stmt = sa_delete(EventModel).where(EventModel.id == event_id).returning(EventModel.id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def list(
        self,
        from_dt: datetime | None = None,
        to_dt: datetime | None = None,
        types: list[EventType] | None = None,
        limit: int = 200,
        order_asc: bool = True,
    ) -> list[Event]:
        stmt = select(EventModel)
        if from_dt is not None:
            stmt = stmt.where(EventModel.occurred_at >= from_dt)
        if to_dt is not None:
            stmt = stmt.where(EventModel.occurred_at <= to_dt)
        if types:
            stmt = stmt.where(EventModel.type.in_([t.value for t in types]))
        if order_asc:
            stmt = stmt.order_by(EventModel.occurred_at.asc())
        else:
            stmt = stmt.order_by(EventModel.occurred_at.desc())
        stmt = stmt.limit(limit)
        result = await self._session.execute(stmt)
        return [_to_domain(row) for row in result.scalars()]

    async def exists_by_source(
        self,
        source_type: str,
        source_chat_id: int,
        source_message_id: str,
    ) -> bool:
        stmt = select(EventModel.id).where(
            EventModel.source_type == source_type,
            EventModel.source_chat_id == source_chat_id,
            EventModel.source_message_id == source_message_id,
        ).limit(1)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def list_by_source_message(
        self,
        source_chat_id: int,
        source_message_id: str,
    ) -> builtins.list[Event]:
        stmt = (
            select(EventModel)
            .where(
                EventModel.source_chat_id == source_chat_id,
                EventModel.source_message_id == source_message_id,
            )
            .order_by(EventModel.source_event_index.asc())
        )
        result = await self._session.execute(stmt)
        return [_to_domain(row) for row in result.scalars()]
