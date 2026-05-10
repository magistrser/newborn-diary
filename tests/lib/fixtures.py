from typing import AsyncGenerator, Generator
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from infrastructure.models import Base
from main import app


@pytest.fixture(scope='session')
def application_client() -> Generator[TestClient, None, None]:
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
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    from settings import settings
    engine = create_async_engine(settings.postgres.get_async_url(), echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
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
