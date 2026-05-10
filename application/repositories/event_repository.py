import builtins
from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from domain.event import Event, EventType


class AbstractEventRepository(ABC):

    @abstractmethod
    async def save(self, event: Event) -> Event:
        raise NotImplementedError

    @abstractmethod
    async def save_many(self, events: list[Event]) -> list[Event]:
        raise NotImplementedError

    @abstractmethod
    async def get_by_id(self, event_id: UUID) -> Event | None:
        raise NotImplementedError

    @abstractmethod
    async def update(
        self,
        event_id: UUID,
        *,
        occurred_at: datetime | None = None,
        event_type: EventType | None = None,
        payload: dict | None = None,
    ) -> Event | None:
        raise NotImplementedError

    @abstractmethod
    async def delete(self, event_id: UUID) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def list(
        self,
        from_dt: datetime | None = None,
        to_dt: datetime | None = None,
        types: list[EventType] | None = None,
        limit: int = 200,
        order_asc: bool = True,
    ) -> list[Event]:
        raise NotImplementedError

    @abstractmethod
    async def exists_by_source(
        self,
        source_type: str,
        source_chat_id: int,
        source_message_id: str,
    ) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def list_by_source_message(
        self,
        source_chat_id: int,
        source_message_id: str,
    ) -> builtins.list[Event]:
        """Return all events for the given Telegram (chat_id, message_id) pair,
        regardless of source_type, ordered by source_event_index."""
        raise NotImplementedError
