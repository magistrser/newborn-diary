import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from application.dto import AnswerResult, AssistantMessage, QAConfig
from application.ports import LLMPort, SqlExecutorPort
from application.services.schema_prompt import build_sql_system_prompt
from application.services.sql_tool import SqlValidationError, extract_uuid_ids, validate_select


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


def _assistant_msg_to_dict(msg: AssistantMessage) -> dict[str, Any]:
    d: dict = {'role': 'assistant', 'content': msg.content}
    if msg.tool_calls:
        d['tool_calls'] = [
            {
                'id': tc.id,
                'type': 'function',
                'function': {
                    'name': tc.function.name,
                    'arguments': tc.function.arguments,
                },
            }
            for tc in msg.tool_calls
        ]
    return d


class AgenticQAService:

    def __init__(
        self,
        llm: LLMPort,
        sql_executor: SqlExecutorPort,
        qa_settings: QAConfig,
    ) -> None:
        self._llm = llm
        self._sql_executor = sql_executor
        self._settings = qa_settings

    async def _execute_tool_call(
        self,
        call: Any,
        queries: list[str],
        sources: list[uuid.UUID],
    ) -> dict:
        try:
            args = json.loads(call.function.arguments)
        except (json.JSONDecodeError, AttributeError):
            args = {}
        sql = args.get('query', '')
        queries.append(sql)
        logger.debug('Agentic SQL query:\n%s', sql)
        try:
            validate_select(sql)
            result = await self._sql_executor.execute_select(
                sql,
                row_cap=self._settings.sql_row_cap,
                statement_timeout_ms=self._settings.sql_statement_timeout_ms,
            )
            sources.extend(extract_uuid_ids(result))
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
                messages, tools
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
        final = await self._llm.chat_text(messages)
        return AnswerResult(
            answer=final,
            used_window={'mode': 'agentic', 'iterations': self._settings.max_tool_iterations, 'queries': queries},
            sources=sources,
        )
