from functools import lru_cache
from typing import Annotated

from fastapi import Depends

from application.services.event_parser import EventParser
from application.services.llm_client import LLMClient
from settings import settings


@lru_cache(maxsize=1)
def _get_llm_client() -> LLMClient:
    return LLMClient(settings.llm)


@lru_cache(maxsize=1)
def _get_event_parser() -> EventParser:
    return EventParser(_get_llm_client(), settings.parser)


def get_llm_client() -> LLMClient:
    return _get_llm_client()


def get_event_parser() -> EventParser:
    return _get_event_parser()


LLMClientDep = Annotated[LLMClient, Depends(get_llm_client)]
EventParserDep = Annotated[EventParser, Depends(get_event_parser)]
