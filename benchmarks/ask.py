from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import time
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import psycopg2  # type: ignore[import-untyped]
from psycopg2 import sql  # type: ignore[import-untyped]
from psycopg2.extensions import connection as PsycopgConnection  # type: ignore[import-untyped]
from psycopg2.extras import Json, RealDictCursor, execute_values  # type: ignore[import-untyped]

from settings import PostgresSettings, Settings, load_settings


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET_NAME = 'current-dev'
DEFAULT_PORT = 8011
BENCHMARK_ENVIRONMENT = 'BENCHMARK'
BENCHMARK_DB_NAME = 'diary_benchmark'
DATASET_ROOT = PROJECT_ROOT / 'benchmarks' / 'datasets' / 'ask'
RESULTS_ROOT = PROJECT_ROOT / 'benchmarks' / 'results' / 'ask'
ITERATIONS_ROOT = PROJECT_ROOT / 'benchmarks' / 'iterations' / 'ask'
EVENT_COLUMNS = [
    'id',
    'occurred_at',
    'recorded_at',
    'type',
    'payload',
    'raw_text',
    'source_type',
    'source_message_id',
    'source_chat_id',
    'source_event_index',
    'parser_version',
]
FEED_TYPES = {'feed_breast', 'feed_bottle'}
TYPE_LABELS = {
    'sleep_start': 'начало сна',
    'sleep_end': 'окончание сна',
    'sleep_interval': 'интервал сна',
    'feed_breast': 'кормление грудью',
    'feed_bottle': 'кормление из бутылочки',
    'pump': 'сцеживание',
    'diaper': 'подгузник',
    'weight': 'вес',
    'temperature': 'температура',
    'medication': 'лекарство',
    'vaccination': 'вакцинация',
    'doctor_visit': 'визит к врачу',
    'bath': 'купание',
    'tummy_time': 'время на животе',
    'walk': 'прогулка',
    'spit_up': 'срыгивание',
    'crying': 'плач',
    'gas': 'газики',
    'father_calming': 'успокоение папой',
    'note': 'заметка',
}
COUNT_QUESTIONS_BY_TYPE = {
    'sleep_start': 'Сколько раз малыш засыпал за всё время?',
    'sleep_end': 'Сколько раз малыш просыпался за всё время?',
    'sleep_interval': 'Сколько интервалов сна записано за всё время?',
    'feed_breast': 'Сколько раз кормили грудью за всё время?',
    'feed_bottle': 'Сколько раз кормили из бутылочки за всё время?',
    'pump': 'Сколько раз было сцеживание за всё время?',
    'diaper': 'Сколько раз меняли подгузник за всё время?',
    'weight': 'Сколько раз записывали вес за всё время?',
    'temperature': 'Сколько раз измеряли температуру за всё время?',
    'medication': 'Сколько раз давали лекарства за всё время?',
    'vaccination': 'Сколько прививок записано за всё время?',
    'doctor_visit': 'Сколько визитов к врачу записано за всё время?',
    'bath': 'Сколько раз купали малыша за всё время?',
    'tummy_time': 'Сколько раз выкладывали на животик за всё время?',
    'walk': 'Сколько прогулок записано за всё время?',
    'spit_up': 'Сколько раз было срыгивание за всё время?',
    'crying': 'Сколько раз записывали плач за всё время?',
    'gas': 'Сколько раз записывали газики за всё время?',
    'father_calming': 'Сколько раз папа успокаивал малыша за всё время?',
    'note': 'Сколько заметок записано за всё время?',
}
LATEST_QUESTIONS_BY_TYPE = {
    'sleep_start': 'Когда малыш последний раз засыпал?',
    'sleep_end': 'Когда малыш последний раз просыпался?',
    'sleep_interval': 'Когда был последний записанный сон?',
    'feed_breast': 'Когда в последний раз кормили грудью?',
    'feed_bottle': 'Когда в последний раз кормили из бутылочки?',
    'pump': 'Когда в последний раз было сцеживание?',
    'diaper': 'Когда последний раз меняли подгузник?',
    'weight': 'Когда последний раз записывали вес?',
    'temperature': 'Когда последний раз измеряли температуру?',
    'medication': 'Когда последний раз давали лекарство?',
    'vaccination': 'Когда была последняя прививка?',
    'doctor_visit': 'Когда был последний визит к врачу?',
    'bath': 'Когда последний раз купали малыша?',
    'tummy_time': 'Когда последний раз выкладывали на животик?',
    'walk': 'Когда была последняя прогулка?',
    'spit_up': 'Когда последний раз было срыгивание?',
    'crying': 'Когда последний раз записывали плач?',
    'gas': 'Когда последний раз записывали газики?',
    'father_calming': 'Когда папа последний раз успокаивал малыша?',
    'note': 'Когда была последняя заметка?',
}
RU_MONTHS = {
    1: 'января',
    2: 'февраля',
    3: 'марта',
    4: 'апреля',
    5: 'мая',
    6: 'июня',
    7: 'июля',
    8: 'августа',
    9: 'сентября',
    10: 'октября',
    11: 'ноября',
    12: 'декабря',
}


class BenchmarkError(Exception):
    pass


def _dataset_dir(dataset_name: str) -> Path:
    return DATASET_ROOT / dataset_name


def _events_path(dataset_name: str) -> Path:
    return _dataset_dir(dataset_name) / 'events.json'


def _cases_path(dataset_name: str) -> Path:
    return _dataset_dir(dataset_name) / 'cases.json'


def _utc_now_id() -> str:
    return datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return _format_datetime(value)
    return str(value)


def _format_datetime(value: datetime) -> str:
    if value.tzinfo is not None:
        value = value.astimezone(UTC)
        return value.isoformat().replace('+00:00', 'Z')
    return value.isoformat()


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def _local_day(event: dict[str, Any], timezone: ZoneInfo) -> str:
    return _parse_datetime(event['occurred_at']).astimezone(timezone).date().isoformat()


def _ru_date(day: str) -> str:
    parsed = date.fromisoformat(day)
    return f'{parsed.day} {RU_MONTHS[parsed.month]} {parsed.year}'


def _ru_date_range(start: date, end: date) -> str:
    return f'{_ru_date(start.isoformat())} по {_ru_date(end.isoformat())}'


def _connect(settings: Settings, db_name: str | None = None) -> PsycopgConnection:
    postgres = settings.postgres
    if db_name is not None:
        postgres = postgres.model_copy(update={'db_name': db_name})
    return psycopg2.connect(postgres.get_sync_url())


def _assert_not_protected_database(postgres: PostgresSettings, action: str) -> None:
    protected = {'diary_test', 'newborn_diary_test'}
    if postgres.db_name in protected:
        raise BenchmarkError(f'{action} refused to use protected database {postgres.db_name!r}')


def assert_benchmark_settings(settings: Settings) -> None:
    if settings.postgres.db_name != BENCHMARK_DB_NAME:
        raise BenchmarkError(
            f'Benchmark runs must target {BENCHMARK_DB_NAME!r}, got {settings.postgres.db_name!r}'
        )
    _assert_not_protected_database(settings.postgres, 'benchmark')


def fetch_dev_events() -> list[dict[str, Any]]:
    dev_settings = load_settings('DEVELOPMENT')
    _assert_not_protected_database(dev_settings.postgres, 'snapshot')
    with _connect(dev_settings) as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                SELECT
                    id::text,
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
                FROM events
                ORDER BY occurred_at ASC, source_event_index ASC, id ASC
                """
            )
            rows = cursor.fetchall()
    events = []
    for row in rows:
        events.append({
            key: _format_datetime(row[key]) if isinstance(row[key], datetime) else row[key]
            for key in EVENT_COLUMNS
        })
    return events


def save_dataset(dataset_name: str, events: list[dict[str, Any]], cases: list[dict[str, Any]]) -> None:
    dataset_dir = _dataset_dir(dataset_name)
    dataset_dir.mkdir(parents=True, exist_ok=True)
    _events_path(dataset_name).write_text(
        json.dumps(events, ensure_ascii=False, indent=2, default=_json_default) + '\n',
        encoding='utf-8',
    )
    _cases_path(dataset_name).write_text(
        json.dumps(cases, ensure_ascii=False, indent=2, default=_json_default) + '\n',
        encoding='utf-8',
    )


def load_events(dataset_name: str = DEFAULT_DATASET_NAME) -> list[dict[str, Any]]:
    path = _events_path(dataset_name)
    if not path.exists():
        raise BenchmarkError(f'Missing dataset events file: {path}')
    return json.loads(path.read_text(encoding='utf-8'))


def load_cases(dataset_name: str = DEFAULT_DATASET_NAME) -> list[dict[str, Any]]:
    path = _cases_path(dataset_name)
    if not path.exists():
        raise BenchmarkError(f'Missing benchmark cases file: {path}')
    return json.loads(path.read_text(encoding='utf-8'))


def _case(
    case_id: str,
    category: str,
    question: str,
    *,
    numbers: Sequence[int] = (),
    sources: Sequence[str] = (),
    answer_contains: Sequence[str] = (),
    answer_contains_any: Sequence[str] = (),
    number_tolerance: int = 0,
    max_iterations: int = 5,
    requires_sql: bool = True,
    query_contains_any: Sequence[str] = (),
    query_contains_all: Sequence[str] = (),
    expected: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        'id': case_id,
        'category': category,
        'question': question,
        'expected': expected or {},
        'checks': {
            'numbers': list(numbers),
            'sources': list(sources),
            'answer_contains': list(answer_contains),
            'answer_contains_any': list(answer_contains_any),
            'number_tolerance': number_tolerance,
            'max_iterations': max_iterations,
            'requires_sql': requires_sql,
            'query_contains_any': list(query_contains_any),
            'query_contains_all': list(query_contains_all),
        },
    }


def _count_by_type(events: Iterable[dict[str, Any]]) -> Counter[str]:
    return Counter(event['type'] for event in events)


def _count_by_day(events: Iterable[dict[str, Any]], timezone: ZoneInfo) -> Counter[str]:
    return Counter(_local_day(event, timezone) for event in events)


def _previous_week_range(latest_day: date) -> tuple[date, date]:
    current_week_start = latest_day - timedelta(days=latest_day.weekday())
    previous_week_start = current_week_start - timedelta(days=7)
    previous_week_end = current_week_start - timedelta(days=1)
    return previous_week_start, previous_week_end


def _current_week_range(day: date) -> tuple[date, date]:
    week_start = day - timedelta(days=day.weekday())
    week_end = week_start + timedelta(days=6)
    return week_start, week_end


def _event_counts_by_day_in_range(
    events: Iterable[dict[str, Any]],
    timezone: ZoneInfo,
    start: date,
    end: date,
) -> dict[str, int]:
    days = {
        (start + timedelta(days=offset)).isoformat(): 0
        for offset in range((end - start).days + 1)
    }
    for event in events:
        local_date = _parse_datetime(event['occurred_at']).astimezone(timezone).date()
        if start <= local_date <= end:
            days[local_date.isoformat()] += 1
    return days


def _is_poo_diaper(event: dict[str, Any]) -> bool:
    return event['type'] == 'diaper' and (event.get('payload') or {}).get('kind') in {'poo', 'both'}


def _poo_counts_by_day(
    events: Iterable[dict[str, Any]],
    timezone: ZoneInfo,
    start: date,
    end: date,
) -> Counter[str]:
    counts: Counter[str] = Counter()
    for event in events:
        local_date = _parse_datetime(event['occurred_at']).astimezone(timezone).date()
        if start <= local_date <= end and _is_poo_diaper(event):
            counts[local_date.isoformat()] += 1
    return counts


def _feed_session_count(events: list[dict[str, Any]], feed_types: set[str] | None = None) -> int:
    feed_types = feed_types or FEED_TYPES
    feed_events = sorted(
        (event for event in events if event['type'] in feed_types),
        key=lambda event: _parse_datetime(event['occurred_at']),
    )
    sessions = 0
    previous: datetime | None = None
    for event in feed_events:
        occurred_at = _parse_datetime(event['occurred_at'])
        if previous is None or (occurred_at - previous).total_seconds() > 30 * 60:
            sessions += 1
        previous = occurred_at
    return sessions


def _sleep_end_summary(events: list[dict[str, Any]]) -> tuple[int, int]:
    total_minutes = 0
    count = 0
    for event in events:
        if event['type'] != 'sleep_end':
            continue
        count += 1
        duration_min = (event.get('payload') or {}).get('duration_min')
        if isinstance(duration_min, int) and duration_min >= 0:
            total_minutes += duration_min
    return count, total_minutes


def _sleep_interval_summary(events: list[dict[str, Any]]) -> tuple[int, int]:
    total_minutes = 0
    count = 0
    for event in events:
        if event['type'] != 'sleep_interval':
            continue
        payload = event.get('payload') or {}
        started_at = payload.get('started_at')
        ended_at = payload.get('ended_at')
        if not started_at or not ended_at:
            continue
        minutes = int((_parse_datetime(ended_at) - _parse_datetime(started_at)).total_seconds() // 60)
        if minutes >= 0:
            total_minutes += minutes
            count += 1
    return count, total_minutes


def _explicit_sleep_intervals(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    intervals = []
    for event in events:
        if event['type'] != 'sleep_interval':
            continue
        payload = event.get('payload') or {}
        started_at = payload.get('started_at')
        ended_at = payload.get('ended_at')
        if not started_at or not ended_at:
            continue
        started = _parse_datetime(started_at)
        ended = _parse_datetime(ended_at)
        duration_min = (ended - started).total_seconds() / 60.0
        if duration_min >= 0:
            intervals.append({
                'id': event['id'],
                'source_ids': [event['id']],
                'started_at': _format_datetime(started),
                'wake_event_id': event['id'],
                'woke_at': _format_datetime(ended),
                'duration_min': duration_min,
                'wake_event_type': event['type'],
            })
    return intervals


def _inferred_sleep_intervals(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    intervals = []
    used_wake_event_ids: set[str] = set()
    for event in events:
        if event['type'] != 'sleep_start':
            continue
        started_at = _parse_datetime(event['occurred_at'])
        wake_candidates = [
            candidate
            for candidate in events
            if candidate['type'] not in {'sleep_start', 'note'} and _is_after_sleep_start(candidate, event)
        ]
        wake_candidates.sort(
            key=lambda candidate: (
                _parse_datetime(candidate['occurred_at']),
                candidate.get('source_event_index') or 0
                if _parse_datetime(candidate['occurred_at']) == started_at
                else 0,
                candidate['id'],
            )
        )
        wake_event = wake_candidates[0] if wake_candidates else None
        if wake_event is None:
            continue
        woke_at = _parse_datetime(wake_event['occurred_at'])
        duration_min = (woke_at - started_at).total_seconds() / 60.0
        if duration_min >= 0:
            used_wake_event_ids.add(wake_event['id'])
            intervals.append({
                'id': event['id'],
                'source_ids': [event['id'], wake_event['id']],
                'started_at': event['occurred_at'],
                'wake_event_id': wake_event['id'],
                'woke_at': wake_event['occurred_at'],
                'duration_min': duration_min,
                'wake_event_type': wake_event['type'],
            })
    for event in events:
        if event['type'] != 'sleep_end' or event['id'] in used_wake_event_ids:
            continue
        previous_candidates = [
            candidate
            for candidate in events
            if candidate['type'] != 'note' and _is_before_event(candidate, event)
        ]
        previous_candidates.sort(
            key=lambda candidate: (
                _parse_datetime(candidate['occurred_at']),
                candidate.get('source_event_index') or 0
                if _parse_datetime(candidate['occurred_at']) == _parse_datetime(event['occurred_at'])
                else 32767,
                candidate['id'],
            ),
            reverse=True,
        )
        previous_event = previous_candidates[0] if previous_candidates else None
        if previous_event is None or previous_event['type'] == 'sleep_start':
            continue
        started_at = _parse_datetime(previous_event['occurred_at'])
        woke_at = _parse_datetime(event['occurred_at'])
        duration_min = (woke_at - started_at).total_seconds() / 60.0
        if duration_min >= 0:
            intervals.append({
                'id': event['id'],
                'source_ids': [previous_event['id'], event['id']],
                'started_at': previous_event['occurred_at'],
                'wake_event_id': event['id'],
                'woke_at': event['occurred_at'],
                'duration_min': duration_min,
                'wake_event_type': event['type'],
            })
    return intervals


def _is_after_sleep_start(candidate: dict[str, Any], sleep_start: dict[str, Any]) -> bool:
    candidate_at = _parse_datetime(candidate['occurred_at'])
    started_at = _parse_datetime(sleep_start['occurred_at'])
    if candidate_at > started_at:
        return True
    return (
        candidate_at == started_at
        and candidate.get('source_chat_id') == sleep_start.get('source_chat_id')
        and candidate.get('source_message_id') == sleep_start.get('source_message_id')
        and (candidate.get('source_event_index') or 0) > (sleep_start.get('source_event_index') or 0)
    )


def _is_before_event(candidate: dict[str, Any], event: dict[str, Any]) -> bool:
    candidate_at = _parse_datetime(candidate['occurred_at'])
    event_at = _parse_datetime(event['occurred_at'])
    if candidate_at < event_at:
        return True
    return (
        candidate_at == event_at
        and candidate.get('source_chat_id') == event.get('source_chat_id')
        and candidate.get('source_message_id') == event.get('source_message_id')
        and (candidate.get('source_event_index') or 0) < (event.get('source_event_index') or 0)
    )


def _intervals_overlap(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return (
        _parse_datetime(left['started_at']) < _parse_datetime(right['woke_at'])
        and _parse_datetime(left['woke_at']) > _parse_datetime(right['started_at'])
    )


def _sleep_duration_intervals(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    explicit_intervals = _explicit_sleep_intervals(events)
    inferred_intervals = [
        interval
        for interval in _inferred_sleep_intervals(events)
        if not any(_intervals_overlap(interval, explicit) for explicit in explicit_intervals)
    ]
    return sorted(
        [*explicit_intervals, *inferred_intervals],
        key=lambda interval: (_parse_datetime(interval['started_at']), interval['id']),
    )


def _inferred_sleep_summary(events: list[dict[str, Any]]) -> tuple[int, int]:
    intervals = _sleep_duration_intervals(events)
    return len(intervals), round(sum(interval['duration_min'] for interval in intervals))


def _sleep_duration_totals(
    intervals: Iterable[dict[str, Any]],
    timezone: ZoneInfo,
    period: str,
) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    for interval in intervals:
        local_date = _parse_datetime(interval['started_at']).astimezone(timezone)
        if period == 'day':
            key = local_date.date().isoformat()
        elif period == 'month':
            key = local_date.strftime('%Y-%m')
        else:
            raise ValueError(f'Unsupported sleep average period: {period}')
        totals[key] += interval['duration_min']
    return totals


def _rounded_average(values: Iterable[float]) -> int:
    values = list(values)
    if not values:
        return 0
    return round(sum(values) / len(values))


def _raw_text_clock_times(raw_text: str | None) -> list[str]:
    if not raw_text:
        return []
    return [
        f'{int(hour):02d}:{minute}'
        for hour, minute in re.findall(r'(?<!\d)([01]?\d|2[0-3]):([0-5]\d)(?!\d)', raw_text)
    ]


def _first_event_with_raw_text_time_mismatch(
    events: Iterable[dict[str, Any]],
    timezone: ZoneInfo,
    local_day: date,
) -> tuple[dict[str, Any], str, str] | None:
    day_events = sorted(
        (
            event
            for event in events
            if _parse_datetime(event['occurred_at']).astimezone(timezone).date() == local_day
        ),
        key=lambda event: (
            _parse_datetime(event['occurred_at']),
            event.get('source_event_index') or 0,
            event['id'],
        ),
    )
    for event in day_events:
        raw_times = _raw_text_clock_times(event.get('raw_text'))
        if not raw_times:
            continue
        local_time = _parse_datetime(event['occurred_at']).astimezone(timezone).strftime('%H:%M')
        if local_time not in raw_times:
            return event, local_time, raw_times[0]
    return None


def _night_window_for_day(local_day: date, timezone: ZoneInfo) -> tuple[datetime, datetime]:
    start = datetime.combine(local_day - timedelta(days=1), datetime.min.time(), tzinfo=timezone) + timedelta(hours=20)
    end = datetime.combine(local_day, datetime.min.time(), tzinfo=timezone) + timedelta(hours=6)
    return start, end


def _sleep_intervals_started_in_window(
    intervals: Iterable[dict[str, Any]],
    timezone: ZoneInfo,
    start: datetime,
    end: datetime,
) -> list[dict[str, Any]]:
    return [
        interval
        for interval in intervals
        if start <= _parse_datetime(interval['started_at']).astimezone(timezone) < end
    ]


def _source_ids_for_intervals(intervals: Iterable[dict[str, Any]]) -> list[str]:
    source_ids = []
    seen = set()
    for interval in intervals:
        for source_id in interval.get('source_ids') or [interval['id']]:
            if source_id not in seen:
                source_ids.append(source_id)
                seen.add(source_id)
    return source_ids


def generate_cases(
    events: list[dict[str, Any]],
    timezone_name: str = 'Europe/Moscow',
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    if not events:
        raise BenchmarkError('Cannot generate /ask benchmark cases from an empty event snapshot')

    timezone = ZoneInfo(timezone_name)
    cases = [
        _case(
            'total-events',
            'counts',
            'Сколько всего записей в дневнике?',
            numbers=[len(events)],
            expected={'total_events': len(events)},
        ),
    ]

    by_type = _count_by_type(events)
    top_type, top_type_count = by_type.most_common(1)[0]
    expected_unit = 'events'
    if top_type in FEED_TYPES:
        top_type_count = _feed_session_count(events, {top_type})
        expected_unit = 'sessions'
    count_question = COUNT_QUESTIONS_BY_TYPE.get(
        top_type,
        f'Сколько раз встречается {TYPE_LABELS.get(top_type, "этот тип записи")} за всё время?',
    )
    cases.append(_case(
        f'count-type-{top_type}',
        'counts',
        count_question,
        numbers=[top_type_count],
        query_contains_any=[top_type],
        expected={'type': top_type, 'count': top_type_count, 'unit': expected_unit},
    ))

    by_day = _count_by_day(events, timezone)
    top_day, top_day_count = sorted(by_day.items(), key=lambda item: (-item[1], item[0]))[0]
    cases.append(_case(
        f'count-day-{top_day}',
        'daily',
        f'Сколько записей было {_ru_date(top_day)}?',
        numbers=[top_day_count],
        query_contains_any=[top_day, 'AT TIME ZONE', '+03'],
        expected={'local_day': top_day, 'count': top_day_count},
    ))

    latest_day = max(_parse_datetime(event['occurred_at']).astimezone(timezone).date() for event in events)
    latest_week_start, latest_week_end = _current_week_range(latest_day)
    latest_week_counts = _event_counts_by_day_in_range(events, timezone, latest_week_start, latest_week_end)
    latest_week_total = sum(latest_week_counts.values())
    latest_week_average = round(latest_week_total / len(latest_week_counts))
    busiest_day, busiest_day_count = sorted(
        latest_week_counts.items(),
        key=lambda item: (-item[1], item[0]),
    )[0]
    cases.extend([
        _case(
            'latest-week-events-total',
            'daily_stats',
            f'Сколько всего записей было за неделю с {_ru_date_range(latest_week_start, latest_week_end)}?',
            numbers=[latest_week_total],
            query_contains_any=[
                latest_week_start.isoformat(),
                latest_week_end.isoformat(),
                'AT TIME ZONE',
                '+03',
            ],
            expected={
                'date_range': [latest_week_start.isoformat(), latest_week_end.isoformat()],
                'total_events': latest_week_total,
            },
        ),
        _case(
            'latest-week-events-by-day',
            'daily_stats',
            (
                'Покажи статистику количества записей по дням за неделю с '
                f'{_ru_date_range(latest_week_start, latest_week_end)}.'
            ),
            numbers=list(latest_week_counts.values()),
            query_contains_any=[
                latest_week_start.isoformat(),
                latest_week_end.isoformat(),
                'AT TIME ZONE',
                'GROUP BY',
            ],
            expected={
                'date_range': [latest_week_start.isoformat(), latest_week_end.isoformat()],
                'day_counts': latest_week_counts,
            },
        ),
        _case(
            'latest-week-average-events-per-day',
            'daily_stats',
            (
                'В среднем сколько записей в день было за неделю с '
                f'{_ru_date_range(latest_week_start, latest_week_end)}? Округли до целого.'
            ),
            numbers=[latest_week_average],
            query_contains_any=[
                latest_week_start.isoformat(),
                latest_week_end.isoformat(),
                'AT TIME ZONE',
                'AVG',
            ],
            expected={
                'date_range': [latest_week_start.isoformat(), latest_week_end.isoformat()],
                'average_events_per_day': latest_week_average,
                'days': len(latest_week_counts),
            },
        ),
        _case(
            'latest-week-busiest-event-day',
            'daily_stats',
            (
                'В какой день за неделю с '
                f'{_ru_date_range(latest_week_start, latest_week_end)} было больше всего записей и сколько?'
            ),
            numbers=[int(busiest_day[-2:]), busiest_day_count],
            query_contains_any=[
                latest_week_start.isoformat(),
                latest_week_end.isoformat(),
                'AT TIME ZONE',
                'GROUP BY',
            ],
            expected={
                'date_range': [latest_week_start.isoformat(), latest_week_end.isoformat()],
                'local_day': busiest_day,
                'count': busiest_day_count,
            },
        ),
    ])

    time_mismatch = _first_event_with_raw_text_time_mismatch(events, timezone, latest_day)
    if time_mismatch is not None:
        mismatch_event, local_time, raw_text_time = time_mismatch
        latest_day_str = latest_day.isoformat()
        cases.append(_case(
            'latest-day-first-event-time-from-occurred-at',
            'event_time',
            (
                f'Покажи первое событие за {_ru_date(latest_day_str)}: дату, '
                'локальное время из occurred_at, occurred_at UTC и raw_text.'
            ),
            sources=[mismatch_event['id']],
            answer_contains=[local_time],
            answer_contains_any=[latest_day_str, _ru_date(latest_day_str)],
            query_contains_any=[latest_day_str, 'AT TIME ZONE', '+03'],
            query_contains_all=['occurred_at', 'raw_text', 'ORDER BY'],
            expected={
                'source_id': mismatch_event['id'],
                'local_day': latest_day_str,
                'local_time': local_time,
                'raw_text_time_example': raw_text_time,
                'rule': 'event time must come from occurred_at, not raw_text',
            },
        ))

    local_today = (now or datetime.now(UTC)).astimezone(timezone).date()
    if local_today > latest_day:
        cases.append(_case(
            'count-today-after-snapshot',
            'relative_dates',
            'Сколько записей сегодня?',
            numbers=[0],
            query_contains_any=['AT TIME ZONE', '+03'],
            expected={'local_day': local_today.isoformat(), 'count': 0},
        ))

    poo_count = sum(1 for event in events if _is_poo_diaper(event))
    if poo_count:
        cases.append(_case(
            'count-poo-diapers',
            'diapers',
            'Сколько раз был стул за всё время?',
            numbers=[poo_count],
            query_contains_any=['diaper', 'poo', 'both'],
            expected={'kinds': ['poo', 'both'], 'count': poo_count},
        ))

    previous_week_start, previous_week_end = _previous_week_range(latest_day)
    previous_week_poo_counts = _poo_counts_by_day(events, timezone, previous_week_start, previous_week_end)
    if previous_week_poo_counts:
        poo_day, poo_day_count = sorted(
            previous_week_poo_counts.items(),
            key=lambda item: (-item[1], item[0]),
        )[0]
        cases.append(_case(
            'previous-week-most-poo-day',
            'diapers',
            f'На прошлой неделе, с {_ru_date_range(previous_week_start, previous_week_end)}, '
            'в какой день было больше всего стула и сколько раз?',
            numbers=[int(poo_day[-2:]), poo_day_count],
            query_contains_any=[
                previous_week_start.isoformat(),
                previous_week_end.isoformat(),
                'diaper',
                'poo',
                'both',
            ],
            expected={
                'local_day': poo_day,
                'count': poo_day_count,
                'date_range': [previous_week_start.isoformat(), previous_week_end.isoformat()],
            },
        ))

    feed_session_count = _feed_session_count(events)
    if feed_session_count:
        cases.append(_case(
            'feeding-sessions-total',
            'feeding',
            'Сколько всего кормлений было, если грудь и бутылочку в пределах 30 минут считать одним кормлением?',
            numbers=[feed_session_count],
            query_contains_any=['feed_breast', 'feed_bottle', '30'],
            expected={'feeding_sessions': feed_session_count},
        ))

    latest_top_type = max(
        (event for event in events if event['type'] == top_type),
        key=lambda event: _parse_datetime(event['occurred_at']),
    )
    cases.append(_case(
        f'latest-type-{top_type}',
        'sources',
        LATEST_QUESTIONS_BY_TYPE.get(top_type, f'Когда последний раз было {TYPE_LABELS.get(top_type, "это")}?'),
        sources=[latest_top_type['id']],
        query_contains_any=['id', top_type],
        expected={'type': top_type, 'source_id': latest_top_type['id']},
    ))

    latest_events = sorted(events, key=lambda event: _parse_datetime(event['occurred_at']), reverse=True)[:3]
    cases.append(_case(
        'latest-three-events',
        'sources',
        'Покажи последние 3 события в дневнике.',
        sources=[event['id'] for event in latest_events],
        query_contains_any=['id', 'ORDER BY'],
        expected={'source_ids': [event['id'] for event in latest_events]},
    ))

    inferred_sleep_intervals = _sleep_duration_intervals(events)
    inferred_sleep_count, inferred_sleep_minutes = _inferred_sleep_summary(events)
    if inferred_sleep_count:
        night_start, night_end = _night_window_for_day(latest_day, timezone)
        latest_night_intervals = _sleep_intervals_started_in_window(
            inferred_sleep_intervals,
            timezone,
            night_start,
            night_end,
        )
        latest_night_minutes = round(sum(interval['duration_min'] for interval in latest_night_intervals))
        latest_night_sources = _source_ids_for_intervals(latest_night_intervals)
        if latest_night_intervals:
            cases.append(_case(
                'latest-day-night-sleep-with-events',
                'sleep',
                'Сколько ребёнок спал сегодня ночью? Покажи события, с помощью которых считал.',
                numbers=[latest_night_minutes],
                number_tolerance=1,
                sources=latest_night_sources,
                query_contains_any=[latest_day.isoformat(), 'AT TIME ZONE', '+03'],
                query_contains_all=['sleep_interval', 'started_at', 'wake_event_id'],
                expected={
                    'local_day': latest_day.isoformat(),
                    'night_window': [
                        night_start.isoformat(),
                        night_end.isoformat(),
                    ],
                    'minutes': latest_night_minutes,
                    'source_ids': latest_night_sources,
                },
            ))

        cases.append(_case(
            'inferred-sleep-duration-summary',
            'sleep',
            (
                'Сколько всего снов получилось и сколько минут сна суммарно, '
                'если учитывать записанные интервалы сна, сон от засыпания до следующей записи, '
                'а пробуждения без записанного засыпания — от предыдущей не-заметки?'
            ),
            numbers=[inferred_sleep_count, inferred_sleep_minutes],
            query_contains_any=['sleep_interval', 'sleep_start'],
            expected={
                'rule': 'prompt_inferred_sleep',
                'intervals': inferred_sleep_count,
                'minutes': inferred_sleep_minutes,
            },
        ))
        day_totals = _sleep_duration_totals(inferred_sleep_intervals, timezone, 'day')
        average_sleep_per_day = _rounded_average(day_totals.values())
        if average_sleep_per_day:
            cases.append(_case(
                'average-sleep-minutes-per-day',
                'sleep_stats',
                'В среднем сколько минут сна в день получается по дням, где есть записи сна?',
                numbers=[average_sleep_per_day],
                query_contains_any=['sleep_start', 'AVG'],
                expected={
                    'average_minutes': average_sleep_per_day,
                    'days_with_sleep_data': len(day_totals),
                },
            ))
        month_totals = _sleep_duration_totals(inferred_sleep_intervals, timezone, 'month')
        average_sleep_per_month = _rounded_average(month_totals.values())
        if average_sleep_per_month:
            cases.append(_case(
                'average-sleep-minutes-per-month',
                'sleep_stats',
                'В среднем сколько минут сна в месяц получается по месяцам, где есть записи сна?',
                numbers=[average_sleep_per_month],
                query_contains_any=['sleep_start', 'AVG'],
                expected={
                    'average_minutes': average_sleep_per_month,
                    'months_with_sleep_data': len(month_totals),
                },
            ))
    else:
        sleep_interval_count, sleep_minutes = _sleep_interval_summary(events)
        if sleep_interval_count:
            cases.append(_case(
                'sleep-interval-summary',
                'sleep',
                'Сколько отдельных интервалов сна записано и сколько минут сна они суммарно занимают?',
                numbers=[sleep_interval_count, sleep_minutes],
                query_contains_any=['sleep_interval'],
                expected={'event_type': 'sleep_interval', 'intervals': sleep_interval_count, 'minutes': sleep_minutes},
            ))

    return cases


def snapshot_current_dev(dataset_name: str = DEFAULT_DATASET_NAME) -> tuple[int, int]:
    events = fetch_dev_events()
    cases = generate_cases(events)
    save_dataset(dataset_name, events, cases)
    return len(events), len(cases)


def regenerate_cases(dataset_name: str = DEFAULT_DATASET_NAME) -> int:
    events = load_events(dataset_name)
    cases = generate_cases(events)
    save_dataset(dataset_name, events, cases)
    return len(cases)


def create_benchmark_database(settings: Settings) -> None:
    assert_benchmark_settings(settings)
    conn = _connect(settings, db_name='postgres')
    try:
        conn.autocommit = True
        with conn.cursor() as cursor:
            cursor.execute('SELECT 1 FROM pg_database WHERE datname = %s', [settings.postgres.db_name])
            if cursor.fetchone() is not None:
                return
            cursor.execute(
                sql.SQL('CREATE DATABASE {}').format(sql.Identifier(settings.postgres.db_name))
            )
    finally:
        conn.close()


def run_migrations() -> None:
    env = os.environ.copy()
    env['ENVIRONMENT'] = BENCHMARK_ENVIRONMENT
    subprocess.run(
        [sys.executable, '-m', 'alembic', 'upgrade', 'head'],
        cwd=PROJECT_ROOT,
        env=env,
        check=True,
    )


def seed_benchmark_database(settings: Settings, events: list[dict[str, Any]]) -> None:
    assert_benchmark_settings(settings)
    with _connect(settings) as conn:
        with conn.cursor() as cursor:
            cursor.execute('TRUNCATE TABLE events')
            values = [
                (
                    event['id'],
                    _parse_datetime(event['occurred_at']),
                    _parse_datetime(event['recorded_at']),
                    event['type'],
                    Json(event['payload']),
                    event.get('raw_text'),
                    event['source_type'],
                    event.get('source_message_id'),
                    event.get('source_chat_id'),
                    event.get('source_event_index', 0),
                    event.get('parser_version'),
                )
                for event in events
            ]
            if values:
                execute_values(
                    cursor,
                    """
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
                    VALUES %s
                    """,
                    values,
                )


def _wait_for_server(base_url: str, process: subprocess.Popen, timeout_sec: float) -> None:
    deadline = time.monotonic() + timeout_sec
    last_error = ''
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise BenchmarkError(f'Benchmark server exited early with code {process.returncode}')
        try:
            response = httpx.get(f'{base_url}/health', timeout=2)
            if response.status_code == 200:
                return
            last_error = f'HTTP {response.status_code}'
        except httpx.HTTPError as exc:
            last_error = str(exc)
        time.sleep(0.5)
    raise BenchmarkError(f'Benchmark server did not become healthy: {last_error}')


def start_benchmark_server(port: int, startup_timeout_sec: float = 30) -> subprocess.Popen:
    env = os.environ.copy()
    env['ENVIRONMENT'] = BENCHMARK_ENVIRONMENT
    process = subprocess.Popen(
        [
            sys.executable,
            '-m',
            'uvicorn',
            'main:app',
            '--host',
            '127.0.0.1',
            '--port',
            str(port),
            '--log-level',
            'warning',
        ],
        cwd=PROJECT_ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    _wait_for_server(f'http://127.0.0.1:{port}', process, startup_timeout_sec)
    return process


def stop_process(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    process.send_signal(signal.SIGTERM)
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)


def _normalize_number_separators(answer: str) -> str:
    return re.sub(r'(?<=\d)[\s\u00a0\u202f](?=\d)', '', answer)


def _answer_numbers(answer: str) -> list[int]:
    answer = _normalize_number_separators(answer)
    return [int(match) for match in re.findall(r'(?<![\d.,])-?\d+(?![\d.,])', answer)]


def _answer_contains_expected_number(answer: str, answer_numbers: list[int], number: int) -> bool:
    normalized_answer = _normalize_number_separators(answer)
    if number in answer_numbers or str(number) in normalized_answer:
        return True
    if number == 0:
        answer_lower = answer.lower()
        return bool(re.search(r'\bнет\b', answer_lower)) or any(
            fragment in answer_lower for fragment in ('нету', 'не было', 'отсутств')
        )
    return False


def _answer_contains_expected_number_with_tolerance(
    answer: str,
    answer_numbers: list[int],
    number: int,
    tolerance: int,
) -> bool:
    if _answer_contains_expected_number(answer, answer_numbers, number):
        return True
    return tolerance > 0 and any(abs(answer_number - number) <= tolerance for answer_number in answer_numbers)


def _combined_queries(response_data: dict[str, Any]) -> str:
    used_window = response_data.get('used_window') or {}
    queries = used_window.get('queries') or []
    return '\n'.join(str(query) for query in queries)


def score_case(case: dict[str, Any], status_code: int | None, response_data: dict[str, Any] | None) -> dict[str, Any]:
    failures = []
    checks = case.get('checks') or {}
    response_data = response_data or {}

    if status_code != 200:
        failures.append(f'expected HTTP 200, got {status_code}')
        return {'passed': False, 'failures': failures}

    answer = str(response_data.get('answer') or '')
    answer_numbers = _answer_numbers(answer)
    number_tolerance = int(checks.get('number_tolerance') or 0)
    for number in checks.get('numbers') or []:
        if not _answer_contains_expected_number_with_tolerance(answer, answer_numbers, number, number_tolerance):
            failures.append(f'answer does not contain expected number {number}')

    answer_lower = answer.lower()
    for fragment in checks.get('answer_contains') or []:
        if str(fragment).lower() not in answer_lower:
            failures.append(f'answer does not contain expected text {fragment!r}')

    answer_contains_any = [str(fragment).lower() for fragment in checks.get('answer_contains_any') or []]
    if answer_contains_any and not any(fragment in answer_lower for fragment in answer_contains_any):
        failures.append(f'answer does not contain any of: {", ".join(answer_contains_any)}')

    used_window = response_data.get('used_window') or {}
    queries = used_window.get('queries') or []
    if checks.get('requires_sql', True) and not queries:
        failures.append('response did not record any SQL query')

    iterations = used_window.get('iterations')
    max_iterations = checks.get('max_iterations')
    if max_iterations is not None and isinstance(iterations, int) and iterations > max_iterations:
        failures.append(f'used {iterations} iterations, expected at most {max_iterations}')

    sources = set(str(source) for source in response_data.get('sources') or [])
    for source in checks.get('sources') or []:
        if str(source) not in sources:
            failures.append(f'missing expected source {source}')

    query_text = _combined_queries(response_data).lower()
    query_contains_any = [str(fragment).lower() for fragment in checks.get('query_contains_any') or []]
    if query_contains_any and not any(fragment in query_text for fragment in query_contains_any):
        failures.append(f'queries do not contain any of: {", ".join(query_contains_any)}')

    query_contains_all = [str(fragment).lower() for fragment in checks.get('query_contains_all') or []]
    missing_query_fragments = [fragment for fragment in query_contains_all if fragment not in query_text]
    if missing_query_fragments:
        failures.append(f'queries do not contain required text: {", ".join(missing_query_fragments)}')

    return {'passed': not failures, 'failures': failures}


def run_http_cases(
    cases: list[dict[str, Any]],
    *,
    port: int,
    request_timeout_sec: float,
) -> list[dict[str, Any]]:
    base_url = f'http://127.0.0.1:{port}'
    results = []
    with httpx.Client(timeout=request_timeout_sec) as client:
        for case in cases:
            started = time.perf_counter()
            status_code: int | None = None
            response_data: dict[str, Any] | None = None
            error: str | None = None
            try:
                response = client.post(f'{base_url}/api/v1/ask', json={'question': case['question']})
                status_code = response.status_code
                response_data = response.json()
            except Exception as exc:  # pylint: disable=broad-exception-caught
                error = str(exc)
            latency_ms = int((time.perf_counter() - started) * 1000)
            score = score_case(case, status_code, response_data)
            if error:
                score['passed'] = False
                score['failures'].append(error)
            results.append({
                'case': case,
                'status_code': status_code,
                'latency_ms': latency_ms,
                'response': response_data,
                'score': score,
            })
    return results


def _run_git(args: list[str]) -> str:
    result = subprocess.run(
        ['git', *args],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return result.stderr.strip()
    return result.stdout.strip()


def collect_git_metadata() -> dict[str, Any]:
    return {
        'commit': _run_git(['rev-parse', '--short', 'HEAD']),
        'status_short': _run_git(['status', '--short']),
        'diff_stat': _run_git(['diff', '--stat']),
    }


def _summarize_results(case_results: list[dict[str, Any]]) -> dict[str, Any]:
    passed = sum(1 for result in case_results if result['score']['passed'])
    by_category: dict[str, dict[str, int]] = defaultdict(lambda: {'passed': 0, 'total': 0})
    for result in case_results:
        category = result['case']['category']
        by_category[category]['total'] += 1
        if result['score']['passed']:
            by_category[category]['passed'] += 1
    return {
        'passed': passed,
        'total': len(case_results),
        'pass_rate': passed / len(case_results) if case_results else 0,
        'by_category': dict(sorted(by_category.items())),
    }


def _latest_result_before(run_id: str) -> dict[str, Any] | None:
    if not RESULTS_ROOT.exists():
        return None
    candidates = sorted(path for path in RESULTS_ROOT.glob('*.json') if path.stem < run_id)
    if not candidates:
        return None
    return json.loads(candidates[-1].read_text(encoding='utf-8'))


def _write_result_json(run_result: dict[str, Any]) -> Path:
    RESULTS_ROOT.mkdir(parents=True, exist_ok=True)
    path = RESULTS_ROOT / f'{run_result["run_id"]}.json'
    path.write_text(
        json.dumps(run_result, ensure_ascii=False, indent=2, default=_json_default) + '\n',
        encoding='utf-8',
    )
    return path


def _comparison_text(current: dict[str, Any], previous: dict[str, Any] | None) -> str:
    if previous is None:
        return 'No previous benchmark result found.'
    current_summary = current['summary']
    previous_summary = previous.get('summary') or {}
    delta = current_summary['passed'] - int(previous_summary.get('passed') or 0)
    return (
        f"Previous run: {previous.get('run_id', 'unknown')} "
        f"({previous_summary.get('passed', 0)}/{previous_summary.get('total', 0)} passed). "
        f"Delta: {delta:+d} passed cases."
    )


def _write_iteration_markdown(run_result: dict[str, Any], previous: dict[str, Any] | None) -> Path:
    ITERATIONS_ROOT.mkdir(parents=True, exist_ok=True)
    summary = run_result['summary']
    git = run_result['git']
    lines = [
        f"# Ask Benchmark Iteration {run_result['run_id']}",
        '',
        f"- Dataset: `{run_result['dataset']}`",
        f"- Notes: {run_result['notes'] or 'None'}",
        f"- Commit: `{git['commit']}`",
        f"- Result: {summary['passed']}/{summary['total']} passed ({summary['pass_rate']:.0%})",
        f"- Comparison: {_comparison_text(run_result, previous)}",
        '',
        '## Category Breakdown',
        '',
    ]
    for category, data in summary['by_category'].items():
        lines.append(f"- `{category}`: {data['passed']}/{data['total']}")

    lines.extend(['', '## Working Tree', ''])
    lines.append('```text')
    lines.append(git['status_short'] or '(clean)')
    lines.append('```')
    lines.append('')
    lines.append('```text')
    lines.append(git['diff_stat'] or '(no diff)')
    lines.append('```')

    failures = [result for result in run_result['case_results'] if not result['score']['passed']]
    lines.extend(['', '## Failures', ''])
    if not failures:
        lines.append('All benchmark cases passed.')
    for result in failures:
        case = result['case']
        response = result.get('response') or {}
        used_window = response.get('used_window') or {}
        lines.extend([
            f"### `{case['id']}`",
            '',
            f"- Question: {case['question']}",
            f"- Expected: `{json.dumps(case.get('expected') or {}, ensure_ascii=False)}`",
            f"- Failures: {'; '.join(result['score']['failures'])}",
            f"- Latency: {result['latency_ms']} ms",
            f"- Sources: `{response.get('sources') or []}`",
            '- SQL:',
            '',
            '```sql',
            '\n\n'.join(str(query) for query in used_window.get('queries') or []) or '(none)',
            '```',
            '',
            '- Answer:',
            '',
            '```text',
            str(response.get('answer') or ''),
            '```',
            '',
        ])

    path = ITERATIONS_ROOT / f'{run_result["run_id"]}.md'
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return path


def write_outputs(run_result: dict[str, Any]) -> tuple[Path, Path]:
    previous = _latest_result_before(run_result['run_id'])
    json_path = _write_result_json(run_result)
    markdown_path = _write_iteration_markdown(run_result, previous)
    return json_path, markdown_path


def run_benchmark(
    *,
    dataset_name: str = DEFAULT_DATASET_NAME,
    port: int = DEFAULT_PORT,
    notes: str = '',
    request_timeout_sec: float = 900,
) -> tuple[dict[str, Any], Path, Path]:
    events = load_events(dataset_name)
    cases = load_cases(dataset_name)
    benchmark_settings = load_settings(BENCHMARK_ENVIRONMENT)
    assert_benchmark_settings(benchmark_settings)
    create_benchmark_database(benchmark_settings)
    run_migrations()
    seed_benchmark_database(benchmark_settings, events)

    process = start_benchmark_server(port)
    try:
        case_results = run_http_cases(cases, port=port, request_timeout_sec=request_timeout_sec)
    finally:
        stop_process(process)

    run_result = {
        'run_id': _utc_now_id(),
        'dataset': dataset_name,
        'notes': notes,
        'port': port,
        'settings': {
            'environment': BENCHMARK_ENVIRONMENT,
            'db_name': benchmark_settings.postgres.db_name,
            'llm_model': benchmark_settings.llm.for_task('agentic_qa').model,
            'llm_base_url': benchmark_settings.llm.for_task('agentic_qa').base_url,
        },
        'git': collect_git_metadata(),
        'summary': _summarize_results(case_results),
        'case_results': case_results,
    }
    json_path, markdown_path = write_outputs(run_result)
    return run_result, json_path, markdown_path


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='Pinned /ask benchmark suite')
    subparsers = parser.add_subparsers(dest='command', required=True)

    snapshot_parser = subparsers.add_parser(
        'snapshot-current-dev',
        help='Create or update the pinned current-dev dataset from the development DB',
    )
    snapshot_parser.add_argument('--dataset', default=DEFAULT_DATASET_NAME)

    regenerate_parser = subparsers.add_parser(
        'regenerate-cases',
        help='Regenerate cases from an existing pinned dataset without reading the development DB',
    )
    regenerate_parser.add_argument('--dataset', default=DEFAULT_DATASET_NAME)

    run_parser = subparsers.add_parser(
        'run',
        help='Run /ask benchmarks against the pinned dataset and benchmark DB',
    )
    run_parser.add_argument('--dataset', default=DEFAULT_DATASET_NAME)
    run_parser.add_argument('--port', type=int, default=DEFAULT_PORT)
    run_parser.add_argument('--notes', default='')
    run_parser.add_argument('--request-timeout-sec', type=float, default=900)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == 'snapshot-current-dev':
            event_count, case_count = snapshot_current_dev(args.dataset)
            print(f'Snapshot saved: {event_count} events, {case_count} cases')
            print(f'Events: {_events_path(args.dataset)}')
            print(f'Cases:  {_cases_path(args.dataset)}')
            return 0

        if args.command == 'regenerate-cases':
            case_count = regenerate_cases(args.dataset)
            print(f'Cases regenerated from pinned events: {case_count}')
            print(f'Cases: {_cases_path(args.dataset)}')
            return 0

        if args.command == 'run':
            result, json_path, markdown_path = run_benchmark(
                dataset_name=args.dataset,
                port=args.port,
                notes=args.notes,
                request_timeout_sec=args.request_timeout_sec,
            )
            summary = result['summary']
            print(f"Benchmark result: {summary['passed']}/{summary['total']} passed")
            print(f'Raw result: {json_path}')
            print(f'Iteration:  {markdown_path}')
            return 0

    except BenchmarkError as exc:
        print(f'Benchmark error: {exc}', file=sys.stderr)
        return 2

    parser.error(f'Unhandled command: {args.command}')
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
