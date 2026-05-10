from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from application.services.agentic_qa_service import AgenticQAService
from application.services.llm_client import LLMClient
from infrastructure.dependencies.db_session import get_db_session
from infrastructure.dependencies.llm import get_agentic_qa_llm_client
from infrastructure.endpoints.v1.router import router
from infrastructure.endpoints.v1.schemas import AskRequest, AskResponse
from settings import settings


def get_agentic_qa_service(
    session: AsyncSession = Depends(get_db_session),
    agentic_llm: LLMClient = Depends(get_agentic_qa_llm_client),
) -> AgenticQAService:
    return AgenticQAService(agentic_llm, session, settings.qa)


@router.post(
    '/ask',
    name='Ask Question',
    response_model=AskResponse,
)
async def ask_question(
    body: AskRequest,
    qa: AgenticQAService = Depends(get_agentic_qa_service),
) -> AskResponse:
    result = await qa.answer(body.question)
    return AskResponse(
        answer=result.answer,
        used_window=result.used_window,
        sources=result.sources,
    )
