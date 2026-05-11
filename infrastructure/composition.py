import logging
import logging.config
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from functools import lru_cache
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession

from application.dto import ParserConfig, QAConfig
from application.ports import EventRepositoryPort
from application.services.agentic_qa_service import AgenticQAService
from application.services.event_parser import EventParser
from application.services.telegram_export_importer import TelegramExportImporter
from application.use_cases import EventUseCase
from infrastructure.llm_client import LLMClient
from infrastructure.repositories.event_repository import SqlEventRepository
from infrastructure.sql_executor import SqlAlchemySqlExecutor
from settings import ParserSettings, QASettings, settings


def _configure_verbose_logging() -> None:
    logging.config.dictConfig({
        'version': 1,
        'disable_existing_loggers': False,
        'formatters': {
            'verbose': {'format': '%(levelname)s %(name)s %(message)s'},
        },
        'handlers': {
            'verbose_stdout': {
                'class': 'logging.StreamHandler',
                'stream': 'ext://sys.stdout',
                'level': 'DEBUG',
                'formatter': 'verbose',
            },
        },
        'loggers': {
            'application': {
                'handlers': ['verbose_stdout'],
                'level': 'DEBUG',
                'propagate': False,
            },
        },
    })
    logging.getLogger('application').debug('Verbose logging enabled')


class SessionTransaction:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def commit(self) -> None:
        await self._session.commit()

    async def rollback(self) -> None:
        await self._session.rollback()


def parser_config_from_settings(parser_settings: ParserSettings) -> ParserConfig:
    return ParserConfig(
        context_window_hours=parser_settings.context_window_hours,
        authors=parser_settings.authors,
        import_concurrency=parser_settings.import_concurrency,
        timezone=parser_settings.timezone,
    )


def qa_config_from_settings(qa_settings: QASettings) -> QAConfig:
    return QAConfig(
        max_tool_iterations=qa_settings.max_tool_iterations,
        sql_row_cap=qa_settings.sql_row_cap,
        sql_statement_timeout_ms=qa_settings.sql_statement_timeout_ms,
        user_timezone=qa_settings.user_timezone,
        agent_max_tokens=qa_settings.agent_max_tokens,
    )


class NewbornDiaryApplicationFactory:
    @staticmethod
    def create_fastapi_app() -> FastAPI:
        from infrastructure.endpoints import root_router

        app = FastAPI(lifespan=NewbornDiaryApplicationFactory.lifespan)
        app.add_middleware(
            CORSMiddleware,
            allow_origins=['http://localhost:8000'],
            allow_methods=['*'],
            allow_headers=['*'],
        )
        app.include_router(root_router)
        return app

    @staticmethod
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncGenerator[dict[str, Any], None]:
        if settings.verbose:
            _configure_verbose_logging()
        yield {}

    @staticmethod
    @lru_cache(maxsize=None)
    def llm_client_for_task(task: str) -> LLMClient:
        return LLMClient(settings.llm.for_task(task))

    @staticmethod
    @lru_cache(maxsize=1)
    def event_parser() -> EventParser:
        return EventParser(
            NewbornDiaryApplicationFactory.llm_client_for_task('parser'),
            parser_config_from_settings(settings.parser),
        )

    @staticmethod
    def event_use_case(
        session: AsyncSession,
        parser: EventParser | None = None,
    ) -> EventUseCase:
        return EventUseCase(
            repo=SqlEventRepository(session),
            parser=parser or NewbornDiaryApplicationFactory.event_parser(),
            parser_config=parser_config_from_settings(settings.parser),
            transaction=SessionTransaction(session),
        )

    @staticmethod
    def agentic_qa_service(session: AsyncSession) -> AgenticQAService:
        return AgenticQAService(
            NewbornDiaryApplicationFactory.llm_client_for_task('agentic_qa'),
            SqlAlchemySqlExecutor(session),
            qa_config_from_settings(settings.qa),
        )

    @staticmethod
    def telegram_export_importer(parser: EventParser) -> TelegramExportImporter:
        from infrastructure.dependencies.db_session import ASYNC_SESSION

        @asynccontextmanager
        async def repo_factory() -> AsyncGenerator[EventRepositoryPort, None]:
            async with ASYNC_SESSION() as session:
                try:
                    yield SqlEventRepository(session)
                    await session.commit()
                except Exception:
                    await session.rollback()
                    raise

        return TelegramExportImporter(
            parser,
            repo_factory,
            parser_config_from_settings(settings.parser),
        )
