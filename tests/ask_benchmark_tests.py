from __future__ import annotations

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


def test_generate_cases_counts_all_sleep_end_events_and_sums_known_durations() -> None:
    events = [
        _event('00000000-0000-0000-0000-000000000001', '2026-05-10T06:00:00Z', 'sleep_end', {}),
        _event(
            '00000000-0000-0000-0000-000000000002',
            '2026-05-10T07:00:00Z',
            'sleep_end',
            {'duration_min': 45},
        ),
    ]

    cases = ask.generate_cases(events)
    sleep_case = next(case for case in cases if case['id'] == 'sleep-end-duration-summary')

    assert sleep_case['expected'] == {'event_type': 'sleep_end', 'intervals': 2, 'minutes': 45}
    assert sleep_case['checks']['numbers'] == [2, 45]

    average_day_case = next(case for case in cases if case['id'] == 'average-sleep-minutes-per-day')
    average_month_case = next(case for case in cases if case['id'] == 'average-sleep-minutes-per-month')
    assert average_day_case['expected'] == {'average_minutes': 45, 'days_with_sleep_data': 1}
    assert average_month_case['expected'] == {'average_minutes': 45, 'months_with_sleep_data': 1}


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
