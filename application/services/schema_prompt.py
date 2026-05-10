from datetime import datetime
from enum import Enum
from typing import Union, get_args, get_origin

from pydantic import BaseModel

from domain.event import (
    BathPayload,
    CryingPayload,
    DiaperPayload,
    DoctorVisitPayload,
    EventType,
    FatherCalmingPayload,
    FeedBottlePayload,
    FeedBreastPayload,
    GasPayload,
    MedicationPayload,
    NotePayload,
    PumpPayload,
    SleepEndPayload,
    SleepIntervalPayload,
    SleepStartPayload,
    SpitUpPayload,
    TemperaturePayload,
    TummyTimePayload,
    VaccinationPayload,
    WalkPayload,
    WeightPayload,
)


_PAYLOAD_BY_TYPE: dict[EventType, type[BaseModel]] = {
    EventType.sleep_start: SleepStartPayload,
    EventType.sleep_end: SleepEndPayload,
    EventType.sleep_interval: SleepIntervalPayload,
    EventType.feed_breast: FeedBreastPayload,
    EventType.feed_bottle: FeedBottlePayload,
    EventType.pump: PumpPayload,
    EventType.diaper: DiaperPayload,
    EventType.weight: WeightPayload,
    EventType.temperature: TemperaturePayload,
    EventType.medication: MedicationPayload,
    EventType.vaccination: VaccinationPayload,
    EventType.doctor_visit: DoctorVisitPayload,
    EventType.bath: BathPayload,
    EventType.tummy_time: TummyTimePayload,
    EventType.walk: WalkPayload,
    EventType.spit_up: SpitUpPayload,
    EventType.crying: CryingPayload,
    EventType.gas: GasPayload,
    EventType.father_calming: FatherCalmingPayload,
    EventType.note: NotePayload,
}


def _annotation_to_sql(annotation: object) -> str:
    origin = get_origin(annotation)
    if origin is Union:
        non_none = [a for a in get_args(annotation) if a is not type(None)]
        if non_none:
            return _annotation_to_sql(non_none[0])

    # Python 3.10+ union syntax (int | None)
    try:
        import types as _types
        if isinstance(annotation, _types.UnionType):
            non_none = [a for a in get_args(annotation) if a is not type(None)]
            if non_none:
                return _annotation_to_sql(non_none[0])
    except AttributeError:
        pass

    if annotation is int:
        return 'INTEGER'
    if annotation is float:
        return 'FLOAT'
    if annotation is str:
        return 'TEXT'
    if annotation is datetime:
        return 'TIMESTAMPTZ'
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        values = '|'.join(str(e.value) for e in annotation)
        return f'TEXT ({values})'
    return 'TEXT'


def _describe_payload(payload_cls: type[BaseModel]) -> str:
    fields = payload_cls.model_fields
    if not fields:
        return '  (no payload fields)'
    lines = []
    for name, field_info in fields.items():
        sql_type = _annotation_to_sql(field_info.annotation)
        lines.append(f'  {name}: {sql_type}')
    return '\n'.join(lines)


def build_sql_system_prompt(now: datetime, tz: str, row_cap: int, statement_timeout_ms: int) -> str:
    type_list = ', '.join(t.value for t in EventType)

    payload_sections = []
    for event_type, payload_cls in _PAYLOAD_BY_TYPE.items():
        payload_sections.append(
            f'  {event_type.value}:\n{_describe_payload(payload_cls)}'
        )
    payload_table = '\n'.join(payload_sections)

    return f"""\
Ты — аналитик дневника новорождённого. Отвечай на вопросы, используя инструмент execute_sql.

## Таблица events (PostgreSQL)

```sql
CREATE TABLE events (
    id              UUID PRIMARY KEY,
    occurred_at     TIMESTAMPTZ NOT NULL,  -- когда произошло событие (используй для фильтрации)
    recorded_at     TIMESTAMPTZ NOT NULL,  -- когда было записано
    type            VARCHAR(50) NOT NULL,  -- тип события (см. ниже)
    payload         JSONB NOT NULL,        -- данные события (зависят от типа)
    raw_text        TEXT,
    source_type     VARCHAR(50) NOT NULL,
    source_chat_id  BIGINT,
    source_message_id VARCHAR(255)
);
-- Индексы: ix_events_occurred_at, ix_events_type
```

## Типы событий

{type_list}

## Поля payload по типу события

Доступ к полям: `payload->>'field_name'` (возвращает text), приведение: `(payload->>'field_name')::INTEGER`.

{payload_table}

## Правила

- Только SELECT (никакого INSERT/UPDATE/DELETE/DDL).
- Текущее время UTC: {now.isoformat()}.
- Часовой пояс пользователя: {tz} — используй `AT TIME ZONE '{tz}'` если нужно показать локальное время.
- Возвращается не более {row_cap} строк (если truncated=true — увеличь агрегацию).
- Таймаут запроса: {statement_timeout_ms} мс.
- Если запрос вернул ошибку — исправь SQL и повтори.
- Когда перечисляешь конкретные события — включай колонку `id` (UUID) в SELECT.
- После получения данных — дай итоговый ответ на языке вопроса."""
