from typing import Annotated

from fastapi import Depends

from application.services.event_parser import EventParser
from infrastructure.composition import NewbornDiaryApplicationFactory
from infrastructure.llm_client import LLMClient


def get_parser_llm_client() -> LLMClient:
    return NewbornDiaryApplicationFactory.llm_client_for_task('parser')


def get_agentic_qa_llm_client() -> LLMClient:
    return NewbornDiaryApplicationFactory.llm_client_for_task('agentic_qa')


def get_llm_client() -> LLMClient:
    return get_parser_llm_client()


def get_event_parser() -> EventParser:
    return NewbornDiaryApplicationFactory.event_parser()


LLMClientDep = Annotated[LLMClient, Depends(get_llm_client)]
EventParserDep = Annotated[EventParser, Depends(get_event_parser)]
