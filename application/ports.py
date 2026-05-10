from __future__ import annotations

import builtins
import uuid
from datetime import datetime
from typing import Any, Protocol

from application.dto import AssistantMessage
from domain.event import Event, EventType


class EventRepositoryPort(Protocol):
    async def save(self, event: Event) -> Event:
        ...

    async def save_many(self, events: list[Event]) -> list[Event]:
        ...

    async def get_by_id(self, event_id: uuid.UUID) -> Event | None:
        ...

    async def update(
        self,
        event_id: uuid.UUID,
        *,
        occurred_at: datetime | None = None,
        event_type: EventType | None = None,
        payload: dict[str, Any] | None = None,
    ) -> Event | None:
        ...

    async def delete(self, event_id: uuid.UUID) -> bool:
        ...

    async def list(
        self,
        from_dt: datetime | None = None,
        to_dt: datetime | None = None,
        types: list[EventType] | None = None,
        limit: int = 200,
        order_asc: bool = True,
    ) -> list[Event]:
        ...

    async def exists_by_source(
        self,
        source_type: str,
        source_chat_id: int,
        source_message_id: str,
    ) -> bool:
        ...

    async def list_by_source_message(
        self,
        source_chat_id: int,
        source_message_id: str,
    ) -> builtins.list[Event]:
        ...


class LLMPort(Protocol):
    async def chat_json(
        self,
        messages: list[dict[str, Any]],
        max_tokens: int | None = None,
    ) -> Any:
        ...

    async def chat_text(
        self,
        messages: list[dict[str, Any]],
        max_tokens: int | None = None,
    ) -> str:
        ...

    async def chat_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        max_tokens: int | None = None,
    ) -> AssistantMessage:
        ...


class SqlExecutorPort(Protocol):
    async def execute_select(
        self,
        sql: str,
        *,
        row_cap: int,
        statement_timeout_ms: int,
    ) -> dict[str, Any]:
        ...


class TransactionPort(Protocol):
    async def commit(self) -> None:
        ...

    async def rollback(self) -> None:
        ...
