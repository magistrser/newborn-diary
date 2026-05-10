from fastapi import Depends

from application.repositories.event_repository import AbstractEventRepository
from application.services.qa_service import QAService
from infrastructure.dependencies.llm import LLMClientDep
from infrastructure.dependencies.repositories.event_repository import get_event_repository
from infrastructure.endpoints.v1.router import router
from infrastructure.endpoints.v1.schemas import AskRequest, AskResponse
from settings import settings


def get_qa_service(
    llm: LLMClientDep,
    repo: AbstractEventRepository = Depends(get_event_repository),
) -> QAService:
    return QAService(llm, repo, settings.qa)


@router.post(
    '/ask',
    name='Ask Question',
    response_model=AskResponse,
)
async def ask_question(
    body: AskRequest,
    qa: QAService = Depends(get_qa_service),
) -> AskResponse:
    result = await qa.answer(body.question)
    return AskResponse(
        answer=result.answer,
        used_window=result.used_window,
        sources=result.sources,
    )
