from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from settings import settings


ASYNC_SESSION = async_sessionmaker(settings.postgres.create_engine(), expire_on_commit=False)


async def get_db_session() -> AsyncGenerator[AsyncSession]:
    async with ASYNC_SESSION() as session:
        yield session
