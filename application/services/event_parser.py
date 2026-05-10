"""
LLM-based parser that converts free-form Russian Telegram messages into structured events.

Explicit times found in the message body take precedence over the message send timestamp.
"""
import json
import logging
import uuid
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ValidationError

from application.services.llm_client import LLMClient
from domain.event import (
    BottleContents,
    BreastSide,
    CryingReason,
    DiaperKind,
    DoctorVisitType,
    Event,
    EventType,
    SpitUpVolume,
    TemperatureMethod,
)
from settings import ParserSettings


_SYSTEM_PROMPT = """\
Ты — парсер дневника новорождённого. Твоя задача — преобразовать сообщение мамы из Telegram \
в JSON-список событий о жизни ребёнка.

## Типы событий и их поля

### Сон
| type | поля payload | когда использовать |
|---|---|---|
| sleep_start | {} | ребёнок заснул («Заснул», «Спит», «Уснул») |
| sleep_end | duration_min?: int | ребёнок проснулся («Проснулся», «Встал»). Если в скобках указано время сна — запиши в duration_min |
| sleep_interval | started_at: ISO8601, ended_at: ISO8601 | известен весь промежуток сна («спал на прогулке полтора часа», «спал с 13:00 до 15:30») |

### Кормление
| type | поля payload | когда использовать |
|---|---|---|
| feed_breast | side: "left"/"right", duration_min?: int | кормление грудью. «Левая»→left, «Правая»→right |
| feed_bottle | volume_ml?: int, contents: "formula"/"expressed" | кормление из бутылочки. «Смесь», «Бутылочка», «Сцеженное» |
| pump | volume_ml?: int, duration_min?: int | сцеживание («Сцедила», «Помпа», «Насос») |

### Подгузник
| type | поля payload | когда использовать |
|---|---|---|
| diaper | kind: "pee"/"poo"/"both"/"unknown" | смена подгузника. «Подгузник» без уточнения → unknown |

### Здоровье и измерения
| type | поля payload | когда использовать |
|---|---|---|
| weight | grams: int | взвешивание («Вес 4200г», «Взвесили — 4.2 кг» → 4200) |
| temperature | celsius: float, method: "rectal"/"axillary"/"forehead" | температура («Температура 37.2», «Термометр 38.1°») |
| medication | name: str, dose_ml?: float | лекарство/витамины («Витамин Д», «Д-дроп», «Бифидумбактерин») |
| vaccination | vaccine: str | прививка («Прививка от полиомиелита», «БЦЖ») |
| doctor_visit | type: "routine"/"sick", notes?: str | визит к врачу |

### Активности
| type | поля payload | когда использовать |
|---|---|---|
| bath | duration_min?: int | купание («Купали», «Ванна») |
| tummy_time | duration_min?: int | время на животике («На животике», «Лежал на животе») |
| walk | duration_min?: int | прогулка («Гуляли», «Прогулка»). НЕ создавай walk если в сообщении речь только о сне на прогулке — там используй sleep_interval |

### Симптомы
| type | поля payload | когда использовать |
|---|---|---|
| spit_up | volume: "small"/"large" | срыгивание («Срыгнул», «Срыгнул много/немного») |
| crying | duration_min?: int, reason: "hunger"/"gas"/"unknown" | плач/крик («Орёт», «Плачет», «Кричал 20 минут») |
| gas | {} | газики («Газики», «Пукнул», «Пукает», «Пердит») |

### Прочее
| type | поля payload | когда использовать |
|---|---|---|
| father_calming | duration_min?: int | «страдания папы» — папа успокаивает ребёнка |
| note | text: str | всё остальное, что не подходит под другие типы |

## Правила извлечения времени (ВАЖНО)

1. message_date передаётся в московском времени (UTC+3, смещение +03:00).
   Если в ТЕКСТЕ сообщения явно указано время (напр. «13:25», «в 19:26», «с 13:00 до 15:30») — \
используй ЕГО как occurred_at, взяв ДАТУ и СМЕЩЕНИЕ +03:00 из message_date.
2. Если явного времени нет — используй message_date как occurred_at.
3. Для sleep_interval: если написано «полтора часа» (1.5 ч) и нет явного начала, \
вычисли started_at = message_date - 90 минут, ended_at = message_date.
4. Все datetime в формате ISO 8601 со смещением +03:00.

## Правила разбора

- Одно сообщение может содержать несколько событий (верни список).
- «Подгузник» в строке означает смену подгузника. Если в той же строке или следующей стоит «Левая»/«Правая» — \
это ОТДЕЛЬНОЕ событие кормления.
- «Заснул?» (с вопросом) — если в recent_events нет активного sleep_start → создай sleep_start. Иначе игнорируй.
- Вернуть пустой список [], если в сообщении нет ничего, относящегося к активностям ребёнка.

## Формат ответа

Верни ТОЛЬКО валидный JSON без пояснений:
{"events": [{"type": "<тип>", "occurred_at": "<ISO8601>", "payload": {...}}]}

## Примеры

### Пример 1
message_date: "2026-05-09T11:19:19+03:00"
text: "Проснулся\\nПодгузник"
→ {"events": [
  {"type": "sleep_end", "occurred_at": "2026-05-09T11:19:19+03:00", "payload": {}},
  {"type": "diaper", "occurred_at": "2026-05-09T11:19:19+03:00", "payload": {"kind": "unknown"}}
]}

### Пример 2
message_date: "2026-05-09T18:16:06+03:00"
text: "Спал на прогулке полтора-два часа\\nБыла левая\\nПотом страдания папы\\nПравая"
→ {"events": [
  {"type": "sleep_interval", "occurred_at": "2026-05-09T18:16:06+03:00",
   "payload": {"started_at": "2026-05-09T16:46:06+03:00", "ended_at": "2026-05-09T18:16:06+03:00"}},
  {"type": "feed_breast", "occurred_at": "2026-05-09T18:16:06+03:00", "payload": {"side": "left"}},
  {"type": "father_calming", "occurred_at": "2026-05-09T18:16:06+03:00", "payload": {}},
  {"type": "feed_breast", "occurred_at": "2026-05-09T18:16:06+03:00", "payload": {"side": "right"}}
]}

### Пример 3
message_date: "2026-05-09T10:00:00+03:00"
text: "Вес 4350г\\nВитамин Д\\nСрыгнул немного"
→ {"events": [
  {"type": "weight", "occurred_at": "2026-05-09T10:00:00+03:00", "payload": {"grams": 4350}},
  {"type": "medication", "occurred_at": "2026-05-09T10:00:00+03:00", "payload": {"name": "Витамин Д"}},
  {"type": "spit_up", "occurred_at": "2026-05-09T10:00:00+03:00", "payload": {"volume": "small"}}
]}

### Пример 4
message_date: "2026-05-09T19:46:13+03:00"
text: "Проснулся (20 мин)"
→ {"events": [
  {"type": "sleep_end", "occurred_at": "2026-05-09T19:46:13+03:00", "payload": {"duration_min": 20}}
]}

### Пример 5
message_date: "2026-05-09T09:00:00+03:00"
text: "Купали\\nГазики\\nСцедила 80мл"
→ {"events": [
  {"type": "bath", "occurred_at": "2026-05-09T09:00:00+03:00", "payload": {}},
  {"type": "gas", "occurred_at": "2026-05-09T09:00:00+03:00", "payload": {}},
  {"type": "pump", "occurred_at": "2026-05-09T09:00:00+03:00", "payload": {"volume_ml": 80}}
]}
"""


# Enum value sets for validation
_VALID_BREAST_SIDES = {e.value for e in BreastSide}
_VALID_DIAPER_KINDS = {e.value for e in DiaperKind}
_VALID_BOTTLE_CONTENTS = {e.value for e in BottleContents}
_VALID_TEMP_METHODS = {e.value for e in TemperatureMethod}
_VALID_SPIT_UP_VOLUMES = {e.value for e in SpitUpVolume}
_VALID_CRYING_REASONS = {e.value for e in CryingReason}
_VALID_DOCTOR_TYPES = {e.value for e in DoctorVisitType}


def _normalise_payload(etype: EventType, payload: dict) -> dict:
    """Coerce and validate enum fields returned by the LLM."""
    p = dict(payload)

    if etype == EventType.feed_breast:
        side = p.get('side', '')
        p['side'] = side if side in _VALID_BREAST_SIDES else BreastSide.left.value

    elif etype == EventType.diaper:
        kind = p.get('kind', 'unknown')
        p['kind'] = kind if kind in _VALID_DIAPER_KINDS else DiaperKind.unknown.value

    elif etype == EventType.feed_bottle:
        contents = p.get('contents', 'formula')
        p['contents'] = contents if contents in _VALID_BOTTLE_CONTENTS else BottleContents.formula.value

    elif etype == EventType.temperature:
        method = p.get('method', 'axillary')
        p['method'] = method if method in _VALID_TEMP_METHODS else TemperatureMethod.axillary.value

    elif etype == EventType.spit_up:
        vol = p.get('volume', 'small')
        p['volume'] = vol if vol in _VALID_SPIT_UP_VOLUMES else SpitUpVolume.small.value

    elif etype == EventType.crying:
        reason = p.get('reason', 'unknown')
        p['reason'] = reason if reason in _VALID_CRYING_REASONS else CryingReason.unknown.value

    elif etype == EventType.doctor_visit:
        vtype = p.get('type', 'routine')
        p['type'] = vtype if vtype in _VALID_DOCTOR_TYPES else DoctorVisitType.routine.value

    return p


class _ParsedEvent(BaseModel):
    type: str
    occurred_at: datetime
    payload: dict


class _ParseResult(BaseModel):
    events: list[_ParsedEvent]


def _compact_event_summary(events: list[Event]) -> str:
    lines = []
    for e in events:
        dt = e.occurred_at.strftime('%H:%M')
        lines.append(f'{dt} {e.type} {json.dumps(e.payload, ensure_ascii=False)}')
    return '\n'.join(lines) if lines else '(нет)'


def _make_note(
    text: str,
    occurred_at: datetime,
    source_type: str,
    source_message_id: str | None,
    source_chat_id: int | None,
) -> Event:
    return Event(
        id=uuid.uuid4(),
        occurred_at=occurred_at,
        recorded_at=datetime.now(timezone.utc),
        type=EventType.note,
        payload={'text': text},
        raw_text=text,
        source_type=source_type,
        source_message_id=source_message_id,
        source_chat_id=source_chat_id,
        parser_version='llm-v1',
    )


logger = logging.getLogger(__name__)


class EventParser:

    def __init__(self, llm: LLMClient, parser_settings: ParserSettings) -> None:
        self._llm = llm
        self._settings = parser_settings
        self._tz = ZoneInfo(parser_settings.timezone)

    async def parse_message(
        self,
        text: str,
        message_date: datetime,
        recent_events: list[Event],
        source_type: str = 'telegram_live',
        source_message_id: str | None = None,
        source_chat_id: int | None = None,
    ) -> list[Event]:
        local_date = message_date.astimezone(self._tz)
        recent_summary = _compact_event_summary(recent_events)
        user_content = (
            f'message_date: "{local_date.isoformat()}"\n'
            f'text: {json.dumps(text, ensure_ascii=False)}\n'
            f'recent_events:\n{recent_summary}'
        )
        messages = [
            {'role': 'system', 'content': _SYSTEM_PROMPT},
            {'role': 'user', 'content': user_content},
        ]
        logger.debug('LLM prompt:\n%s', user_content)
        raw = await self._llm.chat_json(messages)
        logger.debug('LLM response:\n%s', json.dumps(raw, ensure_ascii=False, indent=2))

        try:
            result = _ParseResult.model_validate(raw)
        except (ValidationError, ValueError):
            return [_make_note(text, message_date, source_type, source_message_id, source_chat_id)]

        events = []
        for idx, parsed in enumerate(result.events):
            try:
                etype = EventType(parsed.type)
                payload = _normalise_payload(etype, parsed.payload)
                events.append(Event(
                    id=uuid.uuid4(),
                    occurred_at=parsed.occurred_at,
                    recorded_at=datetime.now(timezone.utc),
                    type=etype,
                    payload=payload,
                    raw_text=text,
                    source_type=source_type,
                    source_message_id=source_message_id,
                    source_chat_id=source_chat_id,
                    source_event_index=idx,
                    parser_version='llm-v1',
                ))
            except (ValueError, KeyError):
                events.append(_make_note(
                    text, parsed.occurred_at, source_type, source_message_id, source_chat_id,
                ))

        if not events:
            events.append(_make_note(text, message_date, source_type, source_message_id, source_chat_id))

        return events
