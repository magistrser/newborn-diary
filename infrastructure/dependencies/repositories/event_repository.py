from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from application.ports import EventRepositoryPort
from infrastructure.dependencies.db_session import get_db_session
from infrastructure.repositories.event_repository import SqlEventRepository


def get_event_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> EventRepositoryPort:
    return SqlEventRepository(session)


EventRepositoryDep = Annotated[EventRepositoryPort, Depends(get_event_repository)]
