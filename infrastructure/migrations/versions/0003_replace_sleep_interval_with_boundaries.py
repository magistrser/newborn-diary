"""replace sleep_interval with sleep boundaries

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-12

"""
from typing import Sequence, Union

from alembic import op

revision: str = '0003'
down_revision: Union[str, Sequence[str], None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint('uq_events_source', 'events', type_='unique')

    op.execute("""
        CREATE TEMP TABLE sleep_interval_migration ON COMMIT DROP AS
        WITH source_rows AS (
            SELECT
                e.*,
                e.source_event_index AS old_source_event_index,
                COALESCE((e.payload->>'started_at')::TIMESTAMPTZ, e.occurred_at) AS started_at,
                COALESCE((e.payload->>'ended_at')::TIMESTAMPTZ, e.occurred_at) AS ended_at,
                md5('newborn_diary:sleep_interval:end:' || e.id::TEXT) AS end_hash
            FROM events e
            WHERE e.type = 'sleep_interval'
        )
        SELECT
            *,
            (
                substr(end_hash, 1, 8) || '-' ||
                substr(end_hash, 9, 4) || '-' ||
                substr(end_hash, 13, 4) || '-' ||
                substr(end_hash, 17, 4) || '-' ||
                substr(end_hash, 21, 12)
            )::UUID AS end_id
        FROM source_rows
    """)

    op.execute("""
        WITH shifted AS (
            SELECT
                e.id,
                (
                    e.source_event_index + (
                        SELECT COUNT(*)
                        FROM sleep_interval_migration si
                        WHERE si.source_type IS NOT DISTINCT FROM e.source_type
                          AND si.source_chat_id IS NOT DISTINCT FROM e.source_chat_id
                          AND si.source_message_id IS NOT DISTINCT FROM e.source_message_id
                          AND si.old_source_event_index < e.source_event_index
                    )
                )::SMALLINT AS new_source_event_index
            FROM events e
            WHERE e.type <> 'sleep_interval'
              AND EXISTS (
                  SELECT 1
                  FROM sleep_interval_migration si
                  WHERE si.source_type IS NOT DISTINCT FROM e.source_type
                    AND si.source_chat_id IS NOT DISTINCT FROM e.source_chat_id
                    AND si.source_message_id IS NOT DISTINCT FROM e.source_message_id
                    AND si.old_source_event_index < e.source_event_index
              )
        )
        UPDATE events e
        SET source_event_index = shifted.new_source_event_index
        FROM shifted
        WHERE e.id = shifted.id
    """)

    op.execute("""
        WITH prepared AS (
            SELECT
                si.id,
                si.started_at,
                (
                    si.old_source_event_index + (
                        SELECT COUNT(*)
                        FROM sleep_interval_migration previous
                        WHERE previous.source_type IS NOT DISTINCT FROM si.source_type
                          AND previous.source_chat_id IS NOT DISTINCT FROM si.source_chat_id
                          AND previous.source_message_id IS NOT DISTINCT FROM si.source_message_id
                          AND previous.old_source_event_index < si.old_source_event_index
                    )
                )::SMALLINT AS start_source_event_index
            FROM sleep_interval_migration si
        )
        UPDATE events e
        SET
            occurred_at = prepared.started_at,
            type = 'sleep_start',
            payload = '{}'::JSONB,
            source_event_index = prepared.start_source_event_index
        FROM prepared
        WHERE e.id = prepared.id
    """)

    op.execute("""
        WITH prepared AS (
            SELECT
                si.*,
                (
                    si.old_source_event_index + (
                        SELECT COUNT(*)
                        FROM sleep_interval_migration previous
                        WHERE previous.source_type IS NOT DISTINCT FROM si.source_type
                          AND previous.source_chat_id IS NOT DISTINCT FROM si.source_chat_id
                          AND previous.source_message_id IS NOT DISTINCT FROM si.source_message_id
                          AND previous.old_source_event_index < si.old_source_event_index
                    )
                )::SMALLINT AS start_source_event_index
            FROM sleep_interval_migration si
        )
        INSERT INTO events (
            id,
            occurred_at,
            recorded_at,
            type,
            payload,
            raw_text,
            source_type,
            source_message_id,
            source_chat_id,
            source_event_index,
            parser_version
        )
        SELECT
            end_id,
            ended_at,
            recorded_at,
            'sleep_end',
            jsonb_strip_nulls(jsonb_build_object(
                'sleep_start_id', id::TEXT,
                'duration_min',
                    CASE
                        WHEN ended_at >= started_at
                        THEN ROUND(EXTRACT(EPOCH FROM (ended_at - started_at)) / 60.0)::INTEGER
                        ELSE NULL
                    END
            )),
            raw_text,
            source_type,
            source_message_id,
            source_chat_id,
            (start_source_event_index + 1)::SMALLINT,
            parser_version
        FROM prepared
    """)

    op.create_unique_constraint(
        'uq_events_source',
        'events',
        ['source_type', 'source_chat_id', 'source_message_id', 'source_event_index'],
    )


def downgrade() -> None:
    op.drop_constraint('uq_events_source', 'events', type_='unique')

    op.execute("""
        CREATE TEMP TABLE sleep_boundary_migration ON COMMIT DROP AS
        WITH candidate_pairs AS (
            SELECT
                s.id AS start_id,
                wake.id AS end_id,
                s.occurred_at AS started_at,
                wake.occurred_at AS ended_at,
                s.source_type,
                s.source_chat_id,
                s.source_message_id,
                s.source_event_index AS start_source_event_index,
                md5('newborn_diary:sleep_interval:end:' || s.id::TEXT) AS expected_end_hash
            FROM events wake
            JOIN events s ON s.id::TEXT = wake.payload->>'sleep_start_id'
            WHERE s.type = 'sleep_start'
              AND wake.type = 'sleep_end'
        )
        SELECT *
        FROM candidate_pairs
        WHERE end_id = (
            substr(expected_end_hash, 1, 8) || '-' ||
            substr(expected_end_hash, 9, 4) || '-' ||
            substr(expected_end_hash, 13, 4) || '-' ||
            substr(expected_end_hash, 17, 4) || '-' ||
            substr(expected_end_hash, 21, 12)
        )::UUID
    """)

    op.execute("""
        DELETE FROM events e
        USING sleep_boundary_migration migration
        WHERE e.id = migration.end_id
    """)

    op.execute("""
        WITH shifted AS (
            SELECT
                e.id,
                (
                    e.source_event_index - (
                        SELECT COUNT(*)
                        FROM sleep_boundary_migration migration
                        WHERE migration.source_type IS NOT DISTINCT FROM e.source_type
                          AND migration.source_chat_id IS NOT DISTINCT FROM e.source_chat_id
                          AND migration.source_message_id IS NOT DISTINCT FROM e.source_message_id
                          AND migration.start_source_event_index < e.source_event_index
                    )
                )::SMALLINT AS new_source_event_index
            FROM events e
            WHERE EXISTS (
                SELECT 1
                FROM sleep_boundary_migration migration
                WHERE migration.source_type IS NOT DISTINCT FROM e.source_type
                  AND migration.source_chat_id IS NOT DISTINCT FROM e.source_chat_id
                  AND migration.source_message_id IS NOT DISTINCT FROM e.source_message_id
                  AND migration.start_source_event_index < e.source_event_index
            )
        )
        UPDATE events e
        SET source_event_index = shifted.new_source_event_index
        FROM shifted
        WHERE e.id = shifted.id
    """)

    op.execute("""
        UPDATE events e
        SET
            type = 'sleep_interval',
            payload = jsonb_build_object(
                'started_at', migration.started_at,
                'ended_at', migration.ended_at
            )
        FROM sleep_boundary_migration migration
        WHERE e.id = migration.start_id
    """)

    op.create_unique_constraint(
        'uq_events_source',
        'events',
        ['source_type', 'source_chat_id', 'source_message_id', 'source_event_index'],
    )
