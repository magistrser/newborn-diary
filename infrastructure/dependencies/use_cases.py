from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from application.services.agentic_qa_service import AgenticQAService
from application.use_cases import EventUseCase
from infrastructure.composition import NewbornDiaryApplicationFactory
from infrastructure.dependencies.db_session import get_db_session
from infrastructure.dependencies.llm import EventParserDep


def get_event_use_case(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    parser: EventParserDep,
) -> EventUseCase:
    return NewbornDiaryApplicationFactory.event_use_case(session, parser)


def get_agentic_qa_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AgenticQAService:
    return NewbornDiaryApplicationFactory.agentic_qa_service(session)


EventUseCaseDep = Annotated[EventUseCase, Depends(get_event_use_case)]
AgenticQAServiceDep = Annotated[AgenticQAService, Depends(get_agentic_qa_service)]
