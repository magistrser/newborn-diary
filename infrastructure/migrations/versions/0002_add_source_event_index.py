"""add source_event_index to events

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-10

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '0002'
down_revision: Union[str, Sequence[str], None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('events', sa.Column('source_event_index', sa.SmallInteger(), nullable=False, server_default='0'))
    op.drop_constraint('uq_events_source', 'events', type_='unique')
    op.create_unique_constraint(
        'uq_events_source',
        'events',
        ['source_type', 'source_chat_id', 'source_message_id', 'source_event_index'],
    )


def downgrade() -> None:
    op.drop_constraint('uq_events_source', 'events', type_='unique')
    op.create_unique_constraint(
        'uq_events_source',
        'events',
        ['source_type', 'source_chat_id', 'source_message_id'],
    )
    op.drop_column('events', 'source_event_index')
