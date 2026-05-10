from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession


class SqlAlchemySqlExecutor:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def execute_select(
        self,
        sql: str,
        *,
        row_cap: int,
        statement_timeout_ms: int,
    ) -> dict[str, Any]:
        await self._session.execute(
            text(f"SET LOCAL statement_timeout = '{statement_timeout_ms}ms'")
        )
        savepoint = await self._session.begin_nested()
        columns: list[str] = []
        rows: list[list[Any]] = []
        truncated = False
        error: str | None = None
        try:
            result = await self._session.execute(text(sql))
            columns = list(result.keys())
            all_rows = result.fetchmany(row_cap + 1)
            truncated = len(all_rows) > row_cap
            rows = [list(row) for row in all_rows[:row_cap]]
        except DBAPIError as exc:
            error = str(exc.orig)[:500]
        finally:
            await savepoint.rollback()

        if error is not None:
            return {'error': error}
        return {'columns': columns, 'rows': rows, 'truncated': truncated}
