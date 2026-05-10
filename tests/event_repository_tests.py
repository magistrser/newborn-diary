import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from domain.event import Event, EventType
from infrastructure.repositories.event_repository import SqlEventRepository


def _make_event(**kwargs: Any) -> Event:
    defaults: dict[str, Any] = dict(
        id=uuid.uuid4(),
        occurred_at=datetime(2026, 5, 10, 10, 0, 0, tzinfo=timezone.utc),
        recorded_at=datetime(2026, 5, 10, 10, 0, 0, tzinfo=timezone.utc),
        type=EventType.sleep_start,
        payload={},
        source_type='test',
    )
    defaults.update(kwargs)
    return Event(**defaults)


async def test_update_occurred_at(db_session: AsyncSession) -> None:
    repo = SqlEventRepository(db_session)
    event = await repo.save(_make_event())

    new_dt = datetime(2026, 5, 10, 12, 0, 0, tzinfo=timezone.utc)
    updated = await repo.update(event.id, occurred_at=new_dt)

    assert updated is not None
    assert updated.id == event.id
    assert updated.occurred_at == new_dt
    assert updated.type == EventType.sleep_start


async def test_update_type_and_payload(db_session: AsyncSession) -> None:
    repo = SqlEventRepository(db_session)
    event = await repo.save(_make_event())

    updated = await repo.update(
        event.id,
        type=EventType.diaper,
        payload={'kind': 'pee'},
    )

    assert updated is not None
    assert updated.type == EventType.diaper
    assert updated.payload == {'kind': 'pee'}


async def test_update_nonexistent_returns_none(db_session: AsyncSession) -> None:
    repo = SqlEventRepository(db_session)
    result = await repo.update(uuid.uuid4(), occurred_at=datetime.now(timezone.utc))
    assert result is None


async def test_update_no_fields_returns_event(db_session: AsyncSession) -> None:
    repo = SqlEventRepository(db_session)
    event = await repo.save(_make_event())
    result = await repo.update(event.id)
    assert result is not None
    assert result.id == event.id


async def test_delete_existing(db_session: AsyncSession) -> None:
    repo = SqlEventRepository(db_session)
    event = await repo.save(_make_event())

    deleted = await repo.delete(event.id)
    assert deleted is True

    fetched = await repo.get_by_id(event.id)
    assert fetched is None


async def test_delete_nonexistent(db_session: AsyncSession) -> None:
    repo = SqlEventRepository(db_session)
    deleted = await repo.delete(uuid.uuid4())
    assert deleted is False
