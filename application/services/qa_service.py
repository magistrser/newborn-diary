"""
Two-step QA pipeline:
1. Intent classification — determine relevant time window and event types.
2. Answer generation — render a timeline and ask the LLM for a natural-language answer.
"""
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel

from application.repositories.event_repository import AbstractEventRepository
from application.services.llm_client import LLMClient
from domain.event import Event, EventType
from settings import QASettings


_INTENT_SYSTEM = """\
Ты — ассистент для анализа дневника новорождённого.
Тебе зададут вопрос на русском или английском языке о событиях из жизни ребёнка.
Твоя задача — определить, какой временной интервал и типы событий нужны для ответа.

Верни ТОЛЬКО JSON:
{
  "window_days": <int>,
  "types": [<список типов из: sleep_start, sleep_end, sleep_interval, feed_breast, feed_bottle, pump, diaper, weight, temperature, medication, vaccination, doctor_visit, bath, tummy_time, walk, spit_up, crying, gas, father_calming, note> или пустой список для всех],
  "reason": "<краткое пояснение>"
}

Типичные интерпретации:
- «вчера» → window_days=2
- «последние 2 недели» → window_days=14
- «сегодня» → window_days=1
- «последний раз» → window_days=7 (возьмём последние 7 дней)
- Если нет явного периода → window_days=14

Типы:
- Вопрос про сон → sleep_start, sleep_end, sleep_interval
- Вопрос про кормление/грудь → feed_breast
- Вопрос про кормление из бутылочки/смесь → feed_bottle
- Вопрос про сцеживание → pump
- Вопрос про подгузник/пописал/покакал → diaper
- Вопрос про вес → weight
- Вопрос про температуру → temperature
- Вопрос про лекарства/витамины → medication
- Вопрос про прививки → vaccination
- Вопрос про врача → doctor_visit
- Вопрос про купание/ванну → bath
- Вопрос про животик/tummy time → tummy_time
- Вопрос про прогулку → walk
- Вопрос про срыгивание → spit_up
- Вопрос про плач/крик → crying
- Вопрос про газики → gas
- Вопрос про папу → father_calming
- Общий вопрос → [] (все типы)
"""

_ANSWER_SYSTEM = """\
Ты — ассистент для анализа дневника новорождённого.
Тебе дан список событий за определённый период и вопрос.
Ответь кратко и по существу на основе этих событий.
Если данных недостаточно — скажи об этом.
Если вопрос на русском — отвечай на русском. Если на английском — на английском.
"""


logger = logging.getLogger(__name__)


class _IntentResult(BaseModel):
    window_days: int = 14
    types: list[str] = []
    reason: str = ''


def _render_timeline(events: list[Event]) -> str:
    lines = []
    for e in events:
        dt = e.occurred_at.strftime('%Y-%m-%d %H:%M')
        payload_str = json.dumps(e.payload, ensure_ascii=False)
        lines.append(f'{dt}  {e.type}  {payload_str}')
    return '\n'.join(lines) if lines else '(нет событий за указанный период)'


@dataclass
class AnswerResult:
    answer: str
    used_window: dict
    sources: list[uuid.UUID]


class QAService:

    def __init__(
        self,
        llm: LLMClient,
        repo: AbstractEventRepository,
        qa_settings: QASettings,
    ) -> None:
        self._llm = llm
        self._repo = repo
        self._settings = qa_settings

    async def answer(self, question: str) -> AnswerResult:
        now = datetime.now(timezone.utc)

        # Step 1: classify intent
        intent_messages = [
            {'role': 'system', 'content': _INTENT_SYSTEM},
            {'role': 'user', 'content': question},
        ]
        logger.debug('Intent prompt:\n%s', intent_messages[-1]['content'])
        raw_intent = await self._llm.chat_json(intent_messages, max_tokens=256)
        logger.debug('Intent response:\n%s', json.dumps(raw_intent, ensure_ascii=False, indent=2))
        try:
            intent = _IntentResult.model_validate(raw_intent)
        except Exception:
            intent = _IntentResult()

        window_days = min(max(intent.window_days, 1), 90)
        from_dt = now - timedelta(days=window_days)

        types: list[EventType] | None = None
        if intent.types:
            types = []
            for t in intent.types:
                try:
                    types.append(EventType(t))
                except ValueError:
                    pass
            if not types:
                types = None

        # Step 2: fetch events
        events = await self._repo.list(
            from_dt=from_dt,
            to_dt=now,
            types=types,
            limit=500,
            order_asc=True,
        )

        timeline = _render_timeline(events)
        answer_messages = [
            {'role': 'system', 'content': _ANSWER_SYSTEM},
            {
                'role': 'user',
                'content': (
                    f'Период: {from_dt.strftime("%Y-%m-%d")} — {now.strftime("%Y-%m-%d")}\n\n'
                    f'События:\n{timeline}\n\n'
                    f'Вопрос: {question}'
                ),
            },
        ]
        logger.debug('Answer prompt:\n%s', answer_messages[-1]['content'])
        answer_text = await self._llm.chat_text(answer_messages)
        logger.debug('Answer response:\n%s', answer_text)

        return AnswerResult(
            answer=answer_text,
            used_window={'from': from_dt.isoformat(), 'to': now.isoformat()},
            sources=[e.id for e in events],
        )
