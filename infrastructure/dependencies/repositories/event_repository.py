from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from application.repositories.event_repository import AbstractEventRepository
from infrastructure.dependencies.db_session import get_db_session
from infrastructure.repositories.event_repository import SqlEventRepository


def get_event_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AbstractEventRepository:
    return SqlEventRepository(session)


EventRepositoryDep = Annotated[AbstractEventRepository, Depends(get_event_repository)]
