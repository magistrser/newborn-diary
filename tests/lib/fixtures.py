from typing import AsyncGenerator, Generator
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from infrastructure.models import Base
from main import app
from settings import PostgresSettings, settings

# pylint: disable=redefined-outer-name,unused-argument


def _assert_test_database(postgres: PostgresSettings) -> None:
    if 'test' not in postgres.db_name:
        raise RuntimeError(f'Refusing to prepare non-test database {postgres.db_name!r}')


def _create_database_if_missing(postgres: PostgresSettings) -> None:
    maintenance_postgres = postgres.model_copy(update={'db_name': 'postgres'})
    engine = create_engine(
        maintenance_postgres.get_sync_url(),
        isolation_level='AUTOCOMMIT',
    )
    try:
        with engine.connect() as conn:
            exists = conn.execute(
                text('SELECT 1 FROM pg_database WHERE datname = :db_name'),
                {'db_name': postgres.db_name},
            ).scalar_one_or_none()
            if exists is not None:
                return

            db_name = engine.dialect.identifier_preparer.quote(postgres.db_name)
            conn.execute(text(f'CREATE DATABASE {db_name}'))
    finally:
        engine.dispose()


@pytest.fixture(scope='session')
def test_database() -> Generator[None, None, None]:
    _assert_test_database(settings.postgres)
    _create_database_if_missing(settings.postgres)

    engine = create_engine(settings.postgres.get_sync_url())
    try:
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
        yield
    finally:
        engine.dispose()


@pytest.fixture(scope='session')
def application_client(test_database: None) -> Generator[TestClient, None, None]:
    with TestClient(app) as client:
        yield client


@pytest.fixture(scope='session')
def from_text_client(application_client: TestClient) -> Generator[tuple[TestClient, AsyncMock], None, None]:
    """Reuses the session-scoped application_client TestClient (same BlockingPortal event loop)
    with the EventParser dependency replaced by an AsyncMock.
    Yields ``(client, mock_parser)`` so tests can assert on parser calls.
    Tests must call ``mock_parser.reset_mock()`` before asserting call counts."""
    from infrastructure.dependencies.llm import get_event_parser

    mock_parser = AsyncMock()
    mock_parser.parse_message = AsyncMock(return_value=[])
    app.dependency_overrides[get_event_parser] = lambda: mock_parser
    yield application_client, mock_parser
    app.dependency_overrides.pop(get_event_parser, None)


@pytest.fixture
async def db_session(test_database: None) -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine(settings.postgres.get_async_url(), echo=False)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            yield session
            await session.rollback()
    await engine.dispose()


@pytest.fixture
def mock_llm_client() -> AsyncMock:
    mock = AsyncMock()
    mock.chat_json = AsyncMock(return_value={'events': []})
    mock.chat_text = AsyncMock(return_value='Test answer')
    return mock
