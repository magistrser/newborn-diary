import logging

from application.services.agentic_qa_service import AgenticQAService
from application.services.llm_client import LLMClient
from application.services.qa_service import AnswerResult, QAService


logger = logging.getLogger(__name__)

_ROUTE_SYSTEM = """\
Classify the user's question as 'stats' or 'narrative'.
- stats: the user wants a count, sum, total, average, comparison, ranking, frequency,
  or uses phrases like how many, how much, how often, average, total.
- narrative: the user wants to know what happened, recall specific events,
  see a timeline, or describe behavior.
Return ONLY JSON: {"mode": "stats" | "narrative"}"""


class QARouter:

    def __init__(
        self,
        llm: LLMClient,
        narrative: QAService,
        agentic: AgenticQAService,
    ) -> None:
        self._llm = llm
        self._narrative = narrative
        self._agentic = agentic

    async def answer(self, question: str) -> AnswerResult:
        messages = [
            {'role': 'system', 'content': _ROUTE_SYSTEM},
            {'role': 'user', 'content': question},
        ]
        try:
            raw = await self._llm.chat_json(messages, max_tokens=64)
            mode = raw.get('mode', 'narrative')
        except Exception:
            mode = 'narrative'

        if mode not in ('stats', 'narrative'):
            mode = 'narrative'

        logger.debug('QARouter routed %r → %s', question[:60], mode)

        if mode == 'stats':
            result = await self._agentic.answer(question)
            result.used_window['route'] = 'stats'
            return result

        result = await self._narrative.answer(question)
        result.used_window['route'] = 'narrative'
        return result
