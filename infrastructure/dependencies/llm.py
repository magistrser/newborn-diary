from functools import lru_cache
from typing import Annotated

from fastapi import Depends

from application.services.event_parser import EventParser
from application.services.llm_client import LLMClient
from settings import settings


@lru_cache(maxsize=None)
def _get_llm_client_for_task(task: str) -> LLMClient:
    return LLMClient(settings.llm.for_task(task))


def get_parser_llm_client() -> LLMClient:
    return _get_llm_client_for_task('parser')


def get_router_llm_client() -> LLMClient:
    return _get_llm_client_for_task('router')


def get_narrative_qa_llm_client() -> LLMClient:
    return _get_llm_client_for_task('narrative_qa')


def get_agentic_qa_llm_client() -> LLMClient:
    return _get_llm_client_for_task('agentic_qa')


def get_llm_client() -> LLMClient:
    return _get_llm_client_for_task('parser')


@lru_cache(maxsize=1)
def _get_event_parser() -> EventParser:
    return EventParser(get_parser_llm_client(), settings.parser)


def get_event_parser() -> EventParser:
    return _get_event_parser()


LLMClientDep = Annotated[LLMClient, Depends(get_llm_client)]
EventParserDep = Annotated[EventParser, Depends(get_event_parser)]
