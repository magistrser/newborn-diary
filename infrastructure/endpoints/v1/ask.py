from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from application.repositories.event_repository import AbstractEventRepository
from application.services.agentic_qa_service import AgenticQAService
from application.services.qa_router import QARouter
from application.services.qa_service import QAService
from infrastructure.dependencies.db_session import get_db_session
from infrastructure.dependencies.llm import LLMClientDep
from infrastructure.dependencies.repositories.event_repository import get_event_repository
from infrastructure.endpoints.v1.router import router
from infrastructure.endpoints.v1.schemas import AskRequest, AskResponse
from settings import settings


def get_qa_router(
    llm: LLMClientDep,
    repo: AbstractEventRepository = Depends(get_event_repository),
    session: AsyncSession = Depends(get_db_session),
) -> QARouter:
    narrative = QAService(llm, repo, settings.qa)
    agentic = AgenticQAService(llm, session, settings.qa)
    return QARouter(llm, narrative, agentic)


@router.post(
    '/ask',
    name='Ask Question',
    response_model=AskResponse,
)
async def ask_question(
    body: AskRequest,
    qa: QARouter = Depends(get_qa_router),
) -> AskResponse:
    result = await qa.answer(body.question)
    return AskResponse(
        answer=result.answer,
        used_window=result.used_window,
        sources=result.sources,
    )
