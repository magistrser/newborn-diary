"""create events table

Revision ID: 0001
Revises:
Create Date: 2026-05-09

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0001'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'events',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('recorded_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('type', sa.String(50), nullable=False),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('raw_text', sa.Text(), nullable=True),
        sa.Column('source_type', sa.String(50), nullable=False),
        sa.Column('source_message_id', sa.String(255), nullable=True),
        sa.Column('source_chat_id', sa.BigInteger(), nullable=True),
        sa.Column('parser_version', sa.String(50), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'source_type', 'source_chat_id', 'source_message_id',
            name='uq_events_source',
        ),
    )
    op.create_index('ix_events_occurred_at', 'events', ['occurred_at'])
    op.create_index('ix_events_type', 'events', ['type'])


def downgrade() -> None:
    op.drop_index('ix_events_type', table_name='events')
    op.drop_index('ix_events_occurred_at', table_name='events')
    op.drop_table('events')
