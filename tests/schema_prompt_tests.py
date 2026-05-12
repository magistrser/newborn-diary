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
    assert "Если используешь явные границы с `+03`, не добавляй к ним `AT TIME ZONE`" in prompt
    assert "WHERE occurred_at >= '2026-04-28 00:00:00+03' AT TIME ZONE 'Europe/Moscow'" in prompt


def test_sql_prompt_describes_breast_feeding_session_count() -> None:
    prompt = build_sql_system_prompt(
        now=datetime(2026, 5, 11, 12, 0, tzinfo=UTC),
        tz='Europe/Moscow',
        row_cap=200,
        statement_timeout_ms=3000,
    )

    assert 'сколько раз кормили грудью' in prompt
    assert 'не количество отдельных строк `feed_breast`' in prompt
    assert "фильтруй `type = 'feed_breast'` и группируй близкие записи" in prompt


def test_sql_prompt_uses_occurred_at_as_event_time_not_raw_text() -> None:
    prompt = build_sql_system_prompt(
        now=datetime(2026, 5, 12, 5, 0, tzinfo=UTC),
        tz='Europe/Moscow',
        row_cap=200,
        statement_timeout_ms=3000,
    )

    assert '`occurred_at` — единственный источник времени и даты события' in prompt
    assert 'выбора первого/последнего события и показа времени пользователю' in prompt
    assert 'не извлекай время события из `raw_text`' in prompt
    assert "occurred_at AT TIME ZONE 'Europe/Moscow' AS local_occurred_at" in prompt
    assert 'ORDER BY occurred_at ASC, source_event_index ASC, id ASC' in prompt
    assert 'ORDER BY occurred_at DESC, source_event_index DESC, id DESC' in prompt


def test_sql_prompt_describes_inferred_sleep_duration_rule() -> None:
    prompt = build_sql_system_prompt(
        now=datetime(2026, 5, 11, 12, 0, tzinfo=UTC),
        tz='Europe/Moscow',
        row_cap=200,
        statement_timeout_ms=3000,
    )

    assert 'считай сон от события `sleep_start` до следующего события после него' in prompt
    assert 'сначала учитывай явные пары `sleep_start` + `sleep_end`' in prompt
    assert "payload->>'sleep_start_id'" in prompt
    assert "у которого `type NOT IN ('sleep_start', 'note')`" in prompt
    assert 'если он пересекается по времени с любой явной парой' in prompt
    assert 'Если явная пара имеет конец раньше начала' in prompt
    assert "считай, что ребёнок спал от предыдущей записи с `type <> 'note'`" in prompt
    assert 'События `note` — это заметки' in prompt
    assert 'Не оставляй `...` в SQL' in prompt
    assert '`explicit_sleep_boundaries`, `start_based_sleeps`, `sleep_end_without_start`' in prompt
    assert 'Не добавляй `p.type <> \'sleep_start\'` внутрь поиска' in prompt
    assert 'source_event_index SMALLINT NOT NULL DEFAULT 0' in prompt
    assert 'WITH explicit_sleep_boundaries_all AS' in prompt
    assert 'explicit_sleep_boundary_events AS' in prompt
    assert 'start_based_sleeps_raw AS' in prompt
    assert 'sleep_end_without_start_raw AS' in prompt
    assert 'woke_at >= started_at' in prompt
    assert 'inferred.started_at < explicit.woke_at' in prompt
    assert 'inferred.woke_at > explicit.started_at' in prompt
    assert "wake.type = 'sleep_end'" in prompt
    assert "s.type = 'sleep_start'" in prompt
    assert "AND e.type NOT IN ('sleep_start', 'note')" in prompt
    assert 'AND e.source_message_id IS NOT DISTINCT FROM s.source_message_id' in prompt
    assert 'CASE WHEN e.occurred_at = s.occurred_at THEN e.source_event_index ELSE 0 END ASC' in prompt
    assert "AND p.type <> 'note'" in prompt
    assert 'boundary.event_id = p.id' in prompt
    assert "WHERE e.type = 'sleep_end'" in prompt
    assert 'previous_event.type <> \'sleep_start\'' in prompt
    assert 'start_based_sleeps_raw counted WHERE counted.wake_event_id = e.id' in prompt
    assert 'только про такие дополнительные `sleep_end` без записанного засыпания' in prompt
    assert 'Если пользователь спрашивает "сегодня ночью" или "сегодняшней ночью"' in prompt
    assert 'с 20:00 предыдущего календарного дня до 06:00 сегодняшнего дня' in prompt
    assert 'Не агрегируй использованные события в JSON/array' in prompt
    assert "WHERE started_at >= '2026-05-11 20:00:00+03'" in prompt
    assert "AND started_at <  '2026-05-12 06:00:00+03'" in prompt
    assert 'Для среднего сна в день сначала получи `inferred_sleeps` через полный базовый CTE выше' in prompt
    assert 'average_sleep_minutes_per_month' in prompt
