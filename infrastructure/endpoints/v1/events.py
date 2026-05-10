import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import Depends, HTTPException, Query
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from domain.event import Event, EventType
from infrastructure.dependencies.db_session import get_db_session
from infrastructure.dependencies.llm import EventParserDep
from infrastructure.dependencies.repositories.event_repository import EventRepositoryDep
from infrastructure.endpoints.v1.router import router
from infrastructure.endpoints.v1.schemas import (
    EventCreateRequest,
    EventPatchRequest,
    EventResponse,
    FromTextRequest,
    FromTextResponse,
    _TYPE_TO_PAYLOAD_MODEL,
)

SessionDep = Annotated[AsyncSession, Depends(get_db_session)]


@router.post(
    '/events',
    name='Create Event',
    response_model=EventResponse,
    status_code=201,
)
async def create_event(
    body: EventCreateRequest,
    repo: EventRepositoryDep,
    session: SessionDep,
) -> EventResponse:
    event = Event(
        id=uuid.uuid4(),
        occurred_at=body.occurred_at,
        recorded_at=datetime.now(timezone.utc),
        type=body.type,
        payload=body.payload.model_dump(exclude_none=True),
        raw_text=body.raw_text,
        source_type=body.source_type,
        source_message_id=body.source_message_id,
        source_chat_id=body.source_chat_id,
        parser_version='manual',
    )
    saved = await repo.save(event)
    await session.commit()
    return EventResponse.model_validate(saved)


@router.get(
    '/events',
    name='List Events',
    response_model=list[EventResponse],
)
async def list_events(
    repo: EventRepositoryDep,
    from_dt: Annotated[datetime | None, Query(alias='from')] = None,
    to_dt: Annotated[datetime | None, Query(alias='to')] = None,
    event_type: Annotated[list[EventType] | None, Query(alias='type')] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
    order: Annotated[str, Query(pattern='^(asc|desc)$')] = 'asc',
) -> list[EventResponse]:
    events = await repo.list(
        from_dt=from_dt,
        to_dt=to_dt,
        types=event_type,
        limit=limit,
        order_asc=(order == 'asc'),
    )
    return [EventResponse.model_validate(e) for e in events]


@router.get(
    '/events/{event_id}',
    name='Get Event',
    response_model=EventResponse,
)
async def get_event(
    event_id: uuid.UUID,
    repo: EventRepositoryDep,
) -> EventResponse:
    event = await repo.get_by_id(event_id)
    if event is None:
        raise HTTPException(status_code=404, detail='Event not found')
    return EventResponse.model_validate(event)


@router.patch(
    '/events/{event_id}',
    name='Patch Event',
    response_model=EventResponse,
)
async def patch_event(
    event_id: uuid.UUID,
    body: EventPatchRequest,
    repo: EventRepositoryDep,
    session: SessionDep,
) -> EventResponse:
    existing = await repo.get_by_id(event_id)
    if existing is None:
        raise HTTPException(status_code=404, detail='Event not found')

    new_type = body.type if body.type is not None else existing.type
    new_payload = body.payload if body.payload is not None else existing.payload

    payload_model = _TYPE_TO_PAYLOAD_MODEL.get(new_type)
    if payload_model is not None:
        try:
            payload_model.model_validate(new_payload)
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=exc.errors()) from exc

    # When type changes without an explicit payload, persist the existing payload
    # so the DB stays consistent with the new type (already validated above).
    persist_payload = new_payload if (body.payload is not None or body.type is not None) else None
    updated = await repo.update(
        event_id,
        occurred_at=body.occurred_at,
        event_type=body.type,
        payload=persist_payload,
    )
    await session.commit()
    return EventResponse.model_validate(updated)


@router.delete(
    '/events/{event_id}',
    name='Delete Event',
    status_code=204,
)
async def delete_event(
    event_id: uuid.UUID,
    repo: EventRepositoryDep,
    session: SessionDep,
) -> None:
    deleted = await repo.delete(event_id)
    if not deleted:
        raise HTTPException(status_code=404, detail='Event not found')
    await session.commit()


@router.post(
    '/events/from-text',
    name='Parse and Create Events from Text',
    response_model=FromTextResponse,
    status_code=201,
)
async def create_events_from_text(
    body: FromTextRequest,
    repo: EventRepositoryDep,
    parser: EventParserDep,
    session: SessionDep,
) -> FromTextResponse:
    # Return already-stored events for this Telegram message without re-parsing.
    # Handles concurrency between the live bot and the import path: whichever
    # ingests the message first wins; the second call gets the same events back.
    if body.source_chat_id is not None and body.source_message_id is not None:
        existing = await repo.list_by_source_message(
            source_chat_id=body.source_chat_id,
            source_message_id=body.source_message_id,
        )
        if existing:
            return FromTextResponse(events=[EventResponse.model_validate(e) for e in existing])

    # Fetch recent events for context (last 12h before message)
    from datetime import timedelta
    context_window_start = body.occurred_at - timedelta(hours=12)
    recent = await repo.list(
        from_dt=context_window_start,
        to_dt=body.occurred_at,
        limit=50,
        order_asc=True,
    )

    events = await parser.parse_message(
        text=body.text,
        message_date=body.occurred_at,
        recent_events=recent,
        source_type=body.source_type,
        source_message_id=body.source_message_id,
        source_chat_id=body.source_chat_id,
    )

    saved = await repo.save_many(events)
    await session.commit()
    return FromTextResponse(events=[EventResponse.model_validate(e) for e in saved])
