import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from domain.event import EventType


@dataclass(frozen=True)
class ParserConfig:
    context_window_hours: int = 12
    authors: list[str] | None = None
    import_concurrency: int = 4
    timezone: str = 'Europe/Moscow'


@dataclass(frozen=True)
class QAConfig:
    max_tool_iterations: int = 5
    sql_row_cap: int = 200
    sql_statement_timeout_ms: int = 3000
    user_timezone: str = 'Europe/Moscow'


@dataclass(frozen=True)
class CreateEventCommand:
    occurred_at: datetime
    event_type: EventType
    payload: dict[str, Any]
    raw_text: str | None = None
    source_type: str = 'api'
    source_message_id: str | None = None
    source_chat_id: int | None = None


@dataclass(frozen=True)
class ListEventsQuery:
    from_dt: datetime | None = None
    to_dt: datetime | None = None
    event_types: list[EventType] | None = None
    limit: int = 200
    order_asc: bool = True


@dataclass(frozen=True)
class PatchEventCommand:
    event_id: uuid.UUID
    occurred_at: datetime | None = None
    event_type: EventType | None = None
    payload: dict[str, Any] | None = None


@dataclass(frozen=True)
class FromTextCommand:
    text: str
    occurred_at: datetime
    source_type: str = 'telegram_live'
    source_message_id: str | None = None
    source_chat_id: int | None = None


@dataclass(frozen=True)
class ImportResult:
    messages_seen: int
    events_created: int
    skipped_duplicates: int
    parse_failures: int


@dataclass(frozen=True)
class AnswerResult:
    answer: str
    used_window: dict[str, Any]
    sources: list[uuid.UUID]


@dataclass(frozen=True)
class ToolFunctionCall:
    name: str
    arguments: str


@dataclass(frozen=True)
class ToolCall:
    id: str
    function: ToolFunctionCall


@dataclass(frozen=True)
class AssistantMessage:
    content: str | None = None
    tool_calls: list[ToolCall] | None = None


class ApplicationError(Exception):
    pass


class LLMTokenLimitError(ApplicationError):
    pass


class EventNotFoundError(ApplicationError):
    pass


class PayloadValidationError(ApplicationError):
    def __init__(self, errors: list[dict[str, Any]]) -> None:
        super().__init__('Invalid event payload')
        self.errors = errors
