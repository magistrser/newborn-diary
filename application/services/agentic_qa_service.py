import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from openai.types.chat import ChatCompletionMessage
from sqlalchemy.ext.asyncio import AsyncSession

from application.services.llm_client import LLMClient
from application.services.schema_prompt import build_sql_system_prompt
from application.services.sql_tool import SqlValidationError, _extract_uuid_ids, execute_select, validate_select
from settings import QASettings


@dataclass
class AnswerResult:
    answer: str
    used_window: dict
    sources: list[uuid.UUID]


logger = logging.getLogger(__name__)

_EXECUTE_SQL_TOOL = {
    'type': 'function',
    'function': {
        'name': 'execute_sql',
        'description': (
            'Run a single read-only SELECT statement against the events table. '
            'Returns {columns, rows, truncated} on success, or {error} on failure. '
            'On error, fix the query and call again.'
        ),
        'parameters': {
            'type': 'object',
            'properties': {
                'query': {
                    'type': 'string',
                    'description': 'A valid PostgreSQL SELECT statement',
                },
            },
            'required': ['query'],
        },
    },
}


def _assistant_msg_to_dict(msg: ChatCompletionMessage) -> dict[str, Any]:
    d: dict = {'role': 'assistant', 'content': msg.content}
    if msg.tool_calls:
        d['tool_calls'] = [
            {
                'id': tc.id,
                'type': 'function',
                'function': {
                    'name': tc.function.name,  # type: ignore[union-attr]
                    'arguments': tc.function.arguments,  # type: ignore[union-attr]
                },
            }
            for tc in msg.tool_calls
        ]
    return d


class AgenticQAService:

    def __init__(
        self,
        llm: LLMClient,
        session: AsyncSession,
        qa_settings: QASettings,
    ) -> None:
        self._llm = llm
        self._session = session
        self._settings = qa_settings

    async def _execute_tool_call(
        self,
        call: Any,
        queries: list[str],
        sources: list[uuid.UUID],
    ) -> dict:
        try:
            args = json.loads(call.function.arguments)  # type: ignore[union-attr]
        except (json.JSONDecodeError, AttributeError):
            args = {}
        sql = args.get('query', '')
        queries.append(sql)
        logger.debug('Agentic SQL query:\n%s', sql)
        try:
            validate_select(sql)
            result = await execute_select(
                self._session,
                sql,
                row_cap=self._settings.sql_row_cap,
                statement_timeout_ms=self._settings.sql_statement_timeout_ms,
            )
            sources.extend(_extract_uuid_ids(result))
        except SqlValidationError as exc:
            result = {'error': f'rejected: {exc}'}
        logger.debug('SQL result: %s', result)
        return result

    async def answer(self, question: str) -> AnswerResult:
        now = datetime.now(timezone.utc)
        system_prompt = build_sql_system_prompt(
            now=now,
            tz=self._settings.user_timezone,
            row_cap=self._settings.sql_row_cap,
            statement_timeout_ms=self._settings.sql_statement_timeout_ms,
        )
        messages: list[dict] = [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': question},
        ]
        tools = [_EXECUTE_SQL_TOOL]
        sources: list[uuid.UUID] = []
        queries: list[str] = []

        for iteration in range(self._settings.max_tool_iterations):
            msg = await self._llm.chat_with_tools(
                messages, tools, max_tokens=self._settings.agent_max_tokens
            )
            messages.append(_assistant_msg_to_dict(msg))

            if not msg.tool_calls:
                logger.debug('Agentic QA done in %d iteration(s)', iteration + 1)
                return AnswerResult(
                    answer=msg.content or '',
                    used_window={'mode': 'agentic', 'iterations': iteration + 1, 'queries': queries},
                    sources=sources,
                )

            for call in msg.tool_calls:
                result = await self._execute_tool_call(call, queries, sources)
                messages.append({
                    'role': 'tool',
                    'tool_call_id': call.id,
                    'content': json.dumps(result, default=str)[:8000],
                })

        # Iteration cap reached — force a final text answer
        messages.append({'role': 'user', 'content': 'Answer now based only on the data already gathered above.'})
        final = await self._llm.chat_text(messages, max_tokens=self._settings.agent_max_tokens)
        return AnswerResult(
            answer=final,
            used_window={'mode': 'agentic', 'iterations': self._settings.max_tool_iterations, 'queries': queries},
            sources=sources,
        )
