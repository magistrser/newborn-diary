import os
from unittest.mock import AsyncMock

import pytest

from application.dto import ParserConfig
from application.services.event_parser import EventParser

os.environ['ENVIRONMENT'] = 'TEST'


@pytest.fixture
def mock_llm_fixture() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def event_parser(mock_llm_fixture: AsyncMock) -> EventParser:
    return EventParser(mock_llm_fixture, ParserConfig(context_window_hours=12, authors=['Mila']))
