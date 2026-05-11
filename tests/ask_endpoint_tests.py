from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from application.dto import LLMTokenLimitError
from infrastructure.dependencies.use_cases import get_agentic_qa_service
from main import app


def test_ask_returns_bad_gateway_for_llm_token_limit(
    application_client: TestClient,
) -> None:
    service = AsyncMock()
    service.answer = AsyncMock(
        side_effect=LLMTokenLimitError('LLM response stopped because max_tokens=1024 was exhausted')
    )
    app.dependency_overrides[get_agentic_qa_service] = lambda: service
    try:
        response = application_client.post('/api/v1/ask', json={'question': 'test'})
    finally:
        app.dependency_overrides.pop(get_agentic_qa_service, None)

    assert response.status_code == 502
    assert 'max_tokens' in response.json()['detail']
