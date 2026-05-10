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
    result = await qa.answer(body.question)
    return AskResponse(
        answer=result.answer,
        used_window=result.used_window,
        sources=result.sources,
    )
