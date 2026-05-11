from fastapi import HTTPException

from application.dto import LLMTokenLimitError
from infrastructure.dependencies.use_cases import AgenticQAServiceDep
from infrastructure.endpoints.v1.router import router
from infrastructure.endpoints.v1.schemas import AskRequest, AskResponse


@router.post(
    '/ask',
    name='Ask Question',
    response_model=AskResponse,
)
async def ask_question(
    body: AskRequest,
    qa: AgenticQAServiceDep,
) -> AskResponse:
    try:
        result = await qa.answer(body.question)
    except LLMTokenLimitError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return AskResponse(
        answer=result.answer,
        used_window=result.used_window,
        sources=result.sources,
    )
