from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from benchmarks import ask
from settings import LLMSettings, PostgresSettings, Settings


def _settings(db_name: str) -> Settings:
    return Settings(
        postgres=PostgresSettings(
            host='localhost',
            port=5432,
            db_name=db_name,
            user='postgres',
            password='postgres',
            pool_size=1,
        ),
        llm=LLMSettings(base_url='http://localhost:41234/v1', model='model'),
    )


def _event(
    event_id: str,
    occurred_at: str,
    event_type: str,
    payload: dict,
    source_event_index: int = 0,
) -> dict:
    return {
        'id': event_id,
        'occurred_at': occurred_at,
        'recorded_at': occurred_at,
        'type': event_type,
        'payload': payload,
        'raw_text': None,
        'source_type': 'test',
        'source_message_id': event_id,
        'source_chat_id': 1,
        'source_event_index': source_event_index,
        'parser_version': 'manual',
    }


def test_generate_cases_uses_snapshot_values() -> None:
    events = [
        _event('00000000-0000-0000-0000-000000000001', '2026-04-30T06:00:00Z', 'diaper', {'kind': 'poo'}),
        _event('00000000-0000-0000-0000-000000000002', '2026-05-10T06:00:00Z', 'diaper', {'kind': 'poo'}),
        _event('00000000-0000-0000-0000-000000000003', '2026-05-10T07:00:00Z', 'diaper', {'kind': 'pee'}),
        _event('00000000-0000-0000-0000-000000000004', '2026-05-10T08:00:00Z', 'feed_breast', {'side': 'left'}),
        _event('00000000-0000-0000-0000-000000000005', '2026-05-10T08:20:00Z', 'feed_breast', {'side': 'right'}),
        _event('00000000-0000-0000-0000-000000000006', '2026-05-10T09:00:00Z', 'feed_bottle', {'volume_ml': 60}),
    ]

    cases = ask.generate_cases(events)
    by_id = {case['id']: case for case in cases}

    assert by_id['total-events']['checks']['numbers'] == [6]
    assert by_id['count-type-diaper']['expected'] == {'type': 'diaper', 'count': 3, 'unit': 'events'}
    assert by_id['count-poo-diapers']['checks']['numbers'] == [2]
    assert by_id['latest-week-events-total']['expected'] == {
        'date_range': ['2026-05-04', '2026-05-10'],
        'total_events': 5,
    }
    assert by_id['latest-week-events-by-day']['expected'] == {
        'date_range': ['2026-05-04', '2026-05-10'],
        'day_counts': {
            '2026-05-04': 0,
            '2026-05-05': 0,
            '2026-05-06': 0,
            '2026-05-07': 0,
            '2026-05-08': 0,
            '2026-05-09': 0,
            '2026-05-10': 5,
        },
    }
    assert by_id['latest-week-average-events-per-day']['expected'] == {
        'date_range': ['2026-05-04', '2026-05-10'],
        'average_events_per_day': 1,
        'days': 7,
    }
    assert by_id['latest-week-busiest-event-day']['expected'] == {
        'date_range': ['2026-05-04', '2026-05-10'],
        'local_day': '2026-05-10',
        'count': 5,
    }
    assert by_id['previous-week-most-poo-day']['expected'] == {
        'local_day': '2026-04-30',
        'count': 1,
        'date_range': ['2026-04-27', '2026-05-03'],
    }
    assert by_id['feeding-sessions-total']['expected'] == {'feeding_sessions': 2}
    assert by_id['latest-three-events']['checks']['sources'] == [
        '00000000-0000-0000-0000-000000000006',
        '00000000-0000-0000-0000-000000000005',
        '00000000-0000-0000-0000-000000000004',
    ]
    for case in cases:
        for internal_type in ask.TYPE_LABELS:
            assert internal_type not in case['question']


def test_generate_cases_rejects_empty_snapshot() -> None:
    with pytest.raises(ask.BenchmarkError):
        ask.generate_cases([])


def test_generate_cases_counts_feeding_questions_as_sessions() -> None:
    events = [
        _event('00000000-0000-0000-0000-000000000001', '2026-05-10T08:00:00Z', 'feed_breast', {'side': 'left'}),
        _event('00000000-0000-0000-0000-000000000002', '2026-05-10T08:20:00Z', 'feed_breast', {'side': 'right'}),
        _event('00000000-0000-0000-0000-000000000003', '2026-05-10T09:00:00Z', 'feed_breast', {'side': 'left'}),
    ]

    cases = ask.generate_cases(events)
    by_id = {case['id']: case for case in cases}

    assert by_id['count-type-feed_breast']['question'] == 'Сколько раз кормили грудью за всё время?'
    assert by_id['count-type-feed_breast']['expected'] == {
        'type': 'feed_breast',
        'count': 2,
        'unit': 'sessions',
    }
    assert by_id['count-type-feed_breast']['checks']['numbers'] == [2]


def test_generate_cases_infers_sleep_from_start_to_next_non_start_event() -> None:
    events = [
        _event('00000000-0000-0000-0000-000000000001', '2026-05-10T06:00:00Z', 'sleep_start', {}),
        _event(
            '00000000-0000-0000-0000-000000000002',
            '2026-05-10T06:15:00Z',
            'sleep_start',
            {},
        ),
        _event(
            '00000000-0000-0000-0000-000000000003',
            '2026-05-10T06:45:00Z',
            'diaper',
            {'kind': 'pee'},
        ),
    ]

    cases = ask.generate_cases(events)
    sleep_case = next(case for case in cases if case['id'] == 'inferred-sleep-duration-summary')

    assert sleep_case['expected'] == {
        'rule': 'prompt_inferred_sleep',
        'intervals': 2,
        'minutes': 75,
    }
    assert sleep_case['checks']['numbers'] == [2, 75]

    average_day_case = next(case for case in cases if case['id'] == 'average-sleep-minutes-per-day')
    average_month_case = next(case for case in cases if case['id'] == 'average-sleep-minutes-per-month')
    assert average_day_case['expected'] == {'average_minutes': 75, 'days_with_sleep_data': 1}
    assert average_month_case['expected'] == {'average_minutes': 75, 'months_with_sleep_data': 1}


def test_generate_cases_adds_sleep_end_without_start_intervals() -> None:
    events = [
        _event(
            '00000000-0000-0000-0000-000000000001',
            '2026-05-10T06:00:00Z',
            'feed_breast',
            {'side': 'left'},
        ),
        _event('00000000-0000-0000-0000-000000000002', '2026-05-10T06:30:00Z', 'sleep_end', {}),
    ]

    cases = ask.generate_cases(events)
    sleep_case = next(case for case in cases if case['id'] == 'inferred-sleep-duration-summary')

    assert sleep_case['expected'] == {
        'rule': 'prompt_inferred_sleep',
        'intervals': 1,
        'minutes': 30,
    }


def test_generate_cases_adds_latest_day_night_sleep_with_explicit_intervals() -> None:
    events = [
        _event(
            '00000000-0000-0000-0000-000000000001',
            '2026-05-11T21:34:22Z',
            'sleep_interval',
            {
                'started_at': '2026-05-11T22:20:00+03:00',
                'ended_at': '2026-05-12T00:30:00+03:00',
            },
        ),
        _event(
            '00000000-0000-0000-0000-000000000002',
            '2026-05-12T00:03:24Z',
            'sleep_interval',
            {
                'started_at': '2026-05-12T00:50:00+03:00',
                'ended_at': '2026-05-12T03:00:00+03:00',
            },
        ),
        _event('00000000-0000-0000-0000-000000000003', '2026-05-12T00:30:00Z', 'sleep_start', {}),
        _event('00000000-0000-0000-0000-000000000004', '2026-05-12T01:22:27Z', 'sleep_end', {}),
        _event('00000000-0000-0000-0000-000000000005', '2026-05-12T01:30:38Z', 'sleep_start', {}),
        _event('00000000-0000-0000-0000-000000000006', '2026-05-12T02:37:55Z', 'sleep_end', {}),
        _event(
            '00000000-0000-0000-0000-000000000007',
            '2026-05-12T05:37:05Z',
            'sleep_interval',
            {
                'started_at': '2026-05-12T07:20:00+03:00',
                'ended_at': '2026-05-12T08:30:00+03:00',
            },
        ),
    ]

    cases = ask.generate_cases(events)
    night_case = next(case for case in cases if case['id'] == 'latest-day-night-sleep-with-events')
    summary_case = next(case for case in cases if case['id'] == 'inferred-sleep-duration-summary')

    assert night_case['expected'] == {
        'local_day': '2026-05-12',
        'night_window': ['2026-05-11T20:00:00+03:00', '2026-05-12T06:00:00+03:00'],
        'minutes': 380,
        'source_ids': [
            '00000000-0000-0000-0000-000000000001',
            '00000000-0000-0000-0000-000000000002',
            '00000000-0000-0000-0000-000000000003',
            '00000000-0000-0000-0000-000000000004',
            '00000000-0000-0000-0000-000000000005',
            '00000000-0000-0000-0000-000000000006',
        ],
    }
    assert night_case['checks']['numbers'] == [380]
    assert night_case['checks']['number_tolerance'] == 1
    assert night_case['checks']['sources'] == night_case['expected']['source_ids']
    assert night_case['checks']['query_contains_all'] == ['sleep_interval', 'started_at', 'wake_event_id']
    assert summary_case['expected'] == {'rule': 'prompt_inferred_sleep', 'intervals': 5, 'minutes': 450}


def test_generate_cases_does_not_double_count_inferred_sleep_overlapping_explicit_interval() -> None:
    events = [
        _event('00000000-0000-0000-0000-000000000001', '2026-05-11T18:57:10Z', 'sleep_start', {}),
        _event(
            '00000000-0000-0000-0000-000000000002',
            '2026-05-11T21:34:22Z',
            'sleep_interval',
            {
                'started_at': '2026-05-11T22:20:00+03:00',
                'ended_at': '2026-05-12T00:30:00+03:00',
            },
        ),
    ]

    cases = ask.generate_cases(events)
    night_case = next(case for case in cases if case['id'] == 'latest-day-night-sleep-with-events')
    summary_case = next(case for case in cases if case['id'] == 'inferred-sleep-duration-summary')

    assert night_case['expected']['minutes'] == 130
    assert night_case['expected']['source_ids'] == ['00000000-0000-0000-0000-000000000002']
    assert summary_case['expected'] == {'rule': 'prompt_inferred_sleep', 'intervals': 1, 'minutes': 130}


def test_generate_cases_adds_today_case_after_pinned_snapshot() -> None:
    events = [
        _event('00000000-0000-0000-0000-000000000001', '2026-05-10T18:00:00Z', 'diaper', {'kind': 'pee'}),
    ]

    cases = ask.generate_cases(events, now=datetime(2026, 5, 10, 22, 0, tzinfo=UTC))
    today_case = next(case for case in cases if case['id'] == 'count-today-after-snapshot')

    assert today_case['question'] == 'Сколько записей сегодня?'
    assert today_case['expected'] == {'local_day': '2026-05-11', 'count': 0}
    assert today_case['checks']['numbers'] == [0]


def test_generate_cases_adds_event_time_case_when_raw_text_has_different_time() -> None:
    events = [
        _event(
            '00000000-0000-0000-0000-000000000001',
            '2026-05-11T21:34:22Z',
            'sleep_interval',
            {'started_at': '2026-05-11T19:20:00Z', 'ended_at': '2026-05-11T21:30:00Z'},
        )
        | {'raw_text': '22:20-00:30 сон'},
        _event(
            '00000000-0000-0000-0000-000000000002',
            '2026-05-12T00:03:24Z',
            'feed_breast',
            {'side': 'left'},
        ),
    ]

    cases = ask.generate_cases(events)
    time_case = next(case for case in cases if case['id'] == 'latest-day-first-event-time-from-occurred-at')

    assert time_case['expected'] == {
        'source_id': '00000000-0000-0000-0000-000000000001',
        'local_day': '2026-05-12',
        'local_time': '00:34',
        'raw_text_time_example': '22:20',
        'rule': 'event time must come from occurred_at, not raw_text',
    }
    assert time_case['checks']['sources'] == ['00000000-0000-0000-0000-000000000001']
    assert time_case['checks']['answer_contains'] == ['00:34']
    assert time_case['checks']['answer_contains_any'] == ['2026-05-12', '12 мая 2026']
    assert time_case['checks']['query_contains_all'] == ['occurred_at', 'raw_text', 'ORDER BY']


def test_score_case_checks_status_numbers_sources_queries_and_iterations() -> None:
    case = {
        'checks': {
            'numbers': [5],
            'sources': ['00000000-0000-0000-0000-000000000001'],
            'max_iterations': 2,
            'requires_sql': True,
            'query_contains_any': ['events'],
        },
    }
    response = {
        'answer': 'Всего 5 событий.',
        'used_window': {'iterations': 2, 'queries': ['SELECT count(*) FROM events']},
        'sources': ['00000000-0000-0000-0000-000000000001'],
    }

    score = ask.score_case(case, 200, response)

    assert score == {'passed': True, 'failures': []}


def test_score_case_checks_answer_and_required_query_fragments() -> None:
    case = {
        'checks': {
            'numbers': [],
            'sources': [],
            'answer_contains': ['00:34'],
            'answer_contains_any': ['2026-05-12', '12 мая 2026'],
            'max_iterations': 2,
            'requires_sql': True,
            'query_contains_any': [],
            'query_contains_all': ['occurred_at', 'raw_text'],
        },
    }
    response = {
        'answer': 'Первое событие было 12 мая 2026 в 00:34.',
        'used_window': {'iterations': 2, 'queries': ['SELECT occurred_at, raw_text FROM events']},
        'sources': [],
    }

    score = ask.score_case(case, 200, response)

    assert score == {'passed': True, 'failures': []}


def test_score_case_reports_failures() -> None:
    case = {
        'checks': {
            'numbers': [7],
            'sources': ['source-id'],
            'max_iterations': 1,
            'requires_sql': True,
            'query_contains_any': ['events'],
        },
    }
    response = {
        'answer': 'Всего 5 событий.',
        'used_window': {'iterations': 2, 'queries': []},
        'sources': [],
    }

    score = ask.score_case(case, 200, response)

    assert score['passed'] is False
    assert len(score['failures']) == 5


def test_score_case_accepts_zero_answer_without_digit() -> None:
    case = {
        'checks': {
            'numbers': [0],
            'sources': [],
            'max_iterations': 2,
            'requires_sql': True,
            'query_contains_any': [],
        },
    }
    response = {
        'answer': 'Сегодня записей нет.',
        'used_window': {'iterations': 2, 'queries': ['SELECT count(*) FROM events']},
        'sources': [],
    }

    score = ask.score_case(case, 200, response)

    assert score == {'passed': True, 'failures': []}


def test_score_case_accepts_grouped_number_with_narrow_no_break_space() -> None:
    case = {
        'checks': {
            'numbers': [11549],
            'sources': [],
            'max_iterations': 2,
            'requires_sql': True,
            'query_contains_any': [],
        },
    }
    response = {
        'answer': 'Суммарно ребёнок спал 11 549 минут.',
        'used_window': {'iterations': 2, 'queries': ['SELECT 11549']},
        'sources': [],
    }

    score = ask.score_case(case, 200, response)

    assert score == {'passed': True, 'failures': []}


def test_score_case_accepts_number_with_configured_tolerance() -> None:
    case = {
        'checks': {
            'numbers': [380],
            'number_tolerance': 1,
            'sources': [],
            'max_iterations': 2,
            'requires_sql': True,
            'query_contains_any': [],
        },
    }
    response = {
        'answer': 'Итого получилось 379 минут.',
        'used_window': {'iterations': 2, 'queries': ['SELECT 379']},
        'sources': [],
    }

    score = ask.score_case(case, 200, response)

    assert score == {'passed': True, 'failures': []}


def test_assert_benchmark_settings_requires_dedicated_db() -> None:
    ask.assert_benchmark_settings(_settings('diary_benchmark'))

    with pytest.raises(ask.BenchmarkError):
        ask.assert_benchmark_settings(_settings('diary'))


def test_load_events_and_cases_use_dataset_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ask, 'DATASET_ROOT', tmp_path)
    events = [_event('00000000-0000-0000-0000-000000000001', '2026-05-10T06:00:00Z', 'diaper', {})]
    cases = [{'id': 'case-1'}]

    ask.save_dataset('sample', events, cases)

    assert ask.load_events('sample') == events
    assert ask.load_cases('sample') == cases
