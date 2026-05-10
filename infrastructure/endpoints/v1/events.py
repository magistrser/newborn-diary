import uuid
from datetime import datetime
from typing import Annotated

from fastapi import HTTPException, Query

from application.dto import (
    CreateEventCommand,
    EventNotFoundError,
    FromTextCommand,
    ListEventsQuery,
    PatchEventCommand,
    PayloadValidationError,
)
from domain.event import EventType
from infrastructure.dependencies.use_cases import EventUseCaseDep
from infrastructure.endpoints.v1.router import router
from infrastructure.endpoints.v1.schemas import (
    EventCreateRequest,
    EventPatchRequest,
    EventResponse,
    FromTextRequest,
    FromTextResponse,
)


@router.post(
    '/events',
    name='Create Event',
    response_model=EventResponse,
    status_code=201,
)
async def create_event(
    body: EventCreateRequest,
    use_case: EventUseCaseDep,
) -> EventResponse:
    saved = await use_case.create_event(CreateEventCommand(
        occurred_at=body.occurred_at,
        event_type=body.type,
        payload=body.payload.model_dump(exclude_none=True),
        raw_text=body.raw_text,
        source_type=body.source_type,
        source_message_id=body.source_message_id,
        source_chat_id=body.source_chat_id,
    ))
    return EventResponse.model_validate(saved)


@router.get(
    '/events',
    name='List Events',
    response_model=list[EventResponse],
)
async def list_events(
    use_case: EventUseCaseDep,
    from_dt: Annotated[datetime | None, Query(alias='from')] = None,
    to_dt: Annotated[datetime | None, Query(alias='to')] = None,
    event_type: Annotated[list[EventType] | None, Query(alias='type')] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
    order: Annotated[str, Query(pattern='^(asc|desc)$')] = 'asc',
) -> list[EventResponse]:
    events = await use_case.list_events(ListEventsQuery(
        from_dt=from_dt,
        to_dt=to_dt,
        event_types=event_type,
        limit=limit,
        order_asc=(order == 'asc'),
    ))
    return [EventResponse.model_validate(e) for e in events]


@router.get(
    '/events/{event_id}',
    name='Get Event',
    response_model=EventResponse,
)
async def get_event(
    event_id: uuid.UUID,
    use_case: EventUseCaseDep,
) -> EventResponse:
    try:
        event = await use_case.get_event(event_id)
    except EventNotFoundError as exc:
        raise HTTPException(status_code=404, detail='Event not found') from exc
    return EventResponse.model_validate(event)


@router.patch(
    '/events/{event_id}',
    name='Patch Event',
    response_model=EventResponse,
)
async def patch_event(
    event_id: uuid.UUID,
    body: EventPatchRequest,
    use_case: EventUseCaseDep,
) -> EventResponse:
    try:
        updated = await use_case.patch_event(PatchEventCommand(
            event_id=event_id,
            occurred_at=body.occurred_at,
            event_type=body.type,
            payload=body.payload,
        ))
    except EventNotFoundError as exc:
        raise HTTPException(status_code=404, detail='Event not found') from exc
    except PayloadValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors) from exc
    return EventResponse.model_validate(updated)


@router.delete(
    '/events/{event_id}',
    name='Delete Event',
    status_code=204,
)
async def delete_event(
    event_id: uuid.UUID,
    use_case: EventUseCaseDep,
) -> None:
    try:
        await use_case.delete_event(event_id)
    except EventNotFoundError as exc:
        raise HTTPException(status_code=404, detail='Event not found') from exc


@router.post(
    '/events/from-text',
    name='Parse and Create Events from Text',
    response_model=FromTextResponse,
    status_code=201,
)
async def create_events_from_text(
    body: FromTextRequest,
    use_case: EventUseCaseDep,
) -> FromTextResponse:
    saved = await use_case.create_events_from_text(FromTextCommand(
        text=body.text,
        occurred_at=body.occurred_at,
        source_type=body.source_type,
        source_message_id=body.source_message_id,
        source_chat_id=body.source_chat_id,
    ))
    return FromTextResponse(events=[EventResponse.model_validate(e) for e in saved])
