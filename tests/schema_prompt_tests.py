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
    assert 'в итоговом ответе явно укажи строку `Интервал расчёта: ...`' in prompt
    assert 'перечисли каждую группу с её числом' in prompt
    assert "WHERE DATE(occurred_at AT TIME ZONE 'Europe/Moscow') = '2026-05-11'" in prompt
    assert 'Не используй границы `+00` или литералы вида `T00:00:00+00`' in prompt
    assert 'среднее за неделю = сумма за 7 локальных дней / 7' in prompt
    assert (
        "WHERE DATE(occurred_at AT TIME ZONE 'Europe/Moscow') "
        "BETWEEN '2026-05-11' AND '2026-05-17'"
    ) in prompt
    assert "AND occurred_at <  '2026-05-18 00:00:00+03'" in prompt
    assert 'Для статистики количества обычных событий по дням с нулевыми днями' in prompt
    assert "SELECT generate_series('2026-05-11'::date, '2026-05-17'::date, INTERVAL '1 day')" in prompt
    assert "ON DATE(e.occurred_at AT TIME ZONE 'Europe/Moscow') = d.local_day" in prompt
    assert 'COUNT(e.id) AS event_count' in prompt
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


def test_sql_prompt_describes_interval_sleep_duration_rule() -> None:
    prompt = build_sql_system_prompt(
        now=datetime(2026, 5, 11, 12, 0, tzinfo=UTC),
        tz='Europe/Moscow',
        row_cap=200,
        statement_timeout_ms=3000,
    )

    assert 'длительность сна за любой период' in prompt
    assert '`border_left` и `border_right`' in prompt
    assert '`2026-05-11 00:00:00+03` — `2026-05-12 00:00:00+03`' in prompt
    assert 'occurred_at >= border_left AND occurred_at < border_right' in prompt
    assert 'повторные `sleep_start` после `sleep_start`' in prompt
    assert 'повторные `sleep_end` перед `sleep_end`' in prompt
    assert 'до `LEAST(now(), border_right)`' in prompt
    assert 'если предыдущего события нет — от `border_left`' in prompt
    assert 'не фильтруй `prepared_data` до одних только `sleep_start`/`sleep_end`' in prompt
    assert "запрещено добавлять `AND e.type IN ('sleep_start', 'sleep_end')`" in prompt
    assert "не суммируй `payload->>'duration_min'`" in prompt
    assert 'source_event_index SMALLINT NOT NULL DEFAULT 0' in prompt
    assert 'WITH interval_bounds AS' in prompt
    assert "'<border_left>'::timestamptz AS border_left" in prompt
    assert "'<border_right>'::timestamptz AS border_right" in prompt
    assert 'prepared_data AS' in prompt
    assert 'unique_sleep AS' in prompt
    assert 'prepared_time AS' in prompt
    assert 'completed_sleep_intervals AS' in prompt
    assert 'inferential_sleep_end_intervals AS' in prompt
    assert 'sleep_intervals AS' in prompt
    assert 'LAG(e.type) OVER (ORDER BY e.occurred_at, e.source_event_index, e.id)' in prompt
    assert 'LEAD(e.type) OVER (ORDER BY e.occurred_at, e.source_event_index, e.id)' in prompt
    assert "(type = 'sleep_end' AND type = next_event_type) IS NOT TRUE" in prompt
    assert "(type = 'sleep_start' AND type = prev_event_type) IS NOT TRUE" in prompt
    assert 'LAG(occurred_at, 1, b.border_left)' in prompt
    assert 'LEAD(occurred_at, 1, LEAST(now(), b.border_right))' in prompt
    assert "prev_event_type IS DISTINCT FROM 'sleep_start'" in prompt
    assert 'boundary_event_id' in prompt
    assert 'Не используй `ARRAY_AGG`, `JSON_AGG`, `jsonb_build_object` или `ROW(...)`' in prompt
    assert 'Не делай финальный SELECT только из `total`, если пользователь просит события' in prompt
    assert 'Не выдумывай события и id' in prompt
    assert 'CONCAT(total_minutes / 60, \' ч \', total_minutes % 60, \' мин\')' in prompt
    assert 'Итого: 12 ч 57 мин (777 минут).' in prompt
    assert 'period_bounds(period_label, border_left, border_right)' in prompt
    assert 'PARTITION BY period_label' in prompt
    assert 'Если пользователь спрашивает среднее "за всё время"' in prompt
    assert 'не ограничивай расчёт текущей неделей, текущим месяцем или текущим годом' in prompt
    assert '`prepared_data` должен выбирать `period_label`, `border_left` и `border_right`' in prompt
    assert '`DATE(started_at)` или `DATE(occurred_at)`' in prompt
    assert 'Никогда не отправляй SQL с литералами `\'<border_left>\'` или `\'<border_right>\'`' in prompt
    assert 'Готовый шаблон для среднего сна по локальным дням за всё время' in prompt
    assert 'MIN(DATE(occurred_at AT TIME ZONE \'Europe/Moscow\')) AS first_day' in prompt
    assert 'CROSS JOIN LATERAL generate_series(first_day, last_day, INTERVAL \'1 day\')' in prompt
    assert 'b.period_label' in prompt
    assert 'PARTITION BY b.period_label' in prompt
    assert 'LAG(occurred_at, 1, border_left)' in prompt
    assert 'average_sleep_minutes_per_day' in prompt
    assert 'Для среднего по месяцам используй тот же CTE' in prompt
    assert 'CROSS JOIN LATERAL generate_series(first_month, last_month, INTERVAL \'1 month\')' in prompt
    assert 'average_sleep_minutes_per_month' in prompt
