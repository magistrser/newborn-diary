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
