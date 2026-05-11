from datetime import UTC, datetime

from application.services.schema_prompt import build_sql_system_prompt


def test_sql_prompt_uses_local_today_for_relative_dates() -> None:
    prompt = build_sql_system_prompt(
        now=datetime(2026, 5, 10, 22, 0, tzinfo=UTC),
        tz='Europe/Moscow',
        row_cap=200,
        statement_timeout_ms=3000,
    )

    assert 'Текущее локальное время пользователя (Europe/Moscow): 2026-05-11T01:00:00+03:00' in prompt
    assert 'Сегодня по календарю пользователя: 2026-05-11' in prompt
    assert "Для \"сегодня\" используй локальную дату 2026-05-11" in prompt
    assert "WHERE DATE(occurred_at AT TIME ZONE 'Europe/Moscow') = '2026-05-11'" in prompt


def test_sql_prompt_describes_inferred_sleep_duration_rule() -> None:
    prompt = build_sql_system_prompt(
        now=datetime(2026, 5, 11, 12, 0, tzinfo=UTC),
        tz='Europe/Moscow',
        row_cap=200,
        statement_timeout_ms=3000,
    )

    assert 'считай сон от события `sleep_start` до следующего события после него' in prompt
    assert 'source_event_index SMALLINT NOT NULL DEFAULT 0' in prompt
    assert "AND e.type <> 'sleep_start'" in prompt
    assert 'AND e.source_message_id IS NOT DISTINCT FROM s.source_message_id' in prompt
    assert 'CASE WHEN e.occurred_at = s.occurred_at THEN e.source_event_index ELSE 0 END ASC' in prompt
    assert 'Для среднего сна в день сначала суммируй сон по локальным дням начала сна' in prompt
    assert 'average_sleep_minutes_per_month' in prompt
