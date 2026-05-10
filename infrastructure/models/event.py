import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, SmallInteger, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import text

from infrastructure.models.base import Base


class EventModel(Base):
    __tablename__ = 'events'

    __table_args__ = (
        UniqueConstraint(
            'source_type', 'source_chat_id', 'source_message_id', 'source_event_index',
            name='uq_events_source',
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text('now()'), nullable=False,
    )
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    source_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    source_event_index: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    parser_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
