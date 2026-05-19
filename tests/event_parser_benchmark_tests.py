from __future__ import annotations

import uuid
from datetime import datetime

from benchmarks import event_parser as parser_benchmark
from domain.event import Event, EventType


def _event(
    event_id: str,
    occurred_at: str,
    event_type: EventType,
    payload: dict,
    source_event_index: int,
) -> Event:
    return Event(
        id=uuid.UUID(event_id),
        occurred_at=datetime.fromisoformat(occurred_at),
        recorded_at=datetime.fromisoformat(occurred_at),
        type=event_type,
        payload=payload,
        raw_text='сон 1:20',
        source_type='benchmark',
        source_message_id='1',
        source_chat_id=1,
        source_event_index=source_event_index,
        parser_version='llm-v1',
    )


def test_default_cases_include_sleep_hhmm_duration_regression() -> None:
    case = parser_benchmark.DEFAULT_CASES[0]

    assert case['id'] == 'sleep-duration-hh-mm-ends-at-message-date'
    assert case['text'] == 'сон 1:20'
    assert case['expected_events'][0]['occurred_at'] == '2026-05-09T14:00:00+03:00'
    assert case['expected_events'][1]['occurred_at'] == '2026-05-09T15:20:00+03:00'
    assert case['expected_events'][1]['payload']['duration_min'] == 80


def test_score_case_accepts_expected_sleep_duration_events() -> None:
    case = parser_benchmark.DEFAULT_CASES[0]
    events = [
        _event(
            '00000000-0000-0000-0000-000000000001',
            '2026-05-09T14:00:00+03:00',
            EventType.sleep_start,
            {},
            0,
        ),
        _event(
            '00000000-0000-0000-0000-000000000002',
            '2026-05-09T15:20:00+03:00',
            EventType.sleep_end,
            {'duration_min': 80, 'sleep_start_id': '00000000-0000-0000-0000-000000000001'},
            1,
        ),
    ]

    assert parser_benchmark.score_case(case, events) == {'passed': True, 'failures': []}


def test_score_case_rejects_future_sleep_duration_events() -> None:
    case = parser_benchmark.DEFAULT_CASES[0]
    events = [
        _event(
            '00000000-0000-0000-0000-000000000001',
            '2026-05-09T15:20:00+03:00',
            EventType.sleep_start,
            {},
            0,
        ),
        _event(
            '00000000-0000-0000-0000-000000000002',
            '2026-05-09T16:40:00+03:00',
            EventType.sleep_end,
            {'duration_min': 80, 'sleep_start_id': '00000000-0000-0000-0000-000000000001'},
            1,
        ),
    ]

    score = parser_benchmark.score_case(case, events)

    assert score['passed'] is False
    assert score['failures'] == [
        'event 0: expected occurred_at 2026-05-09T14:00:00+03:00, got 2026-05-09T15:20:00+03:00',
        'event 1: expected occurred_at 2026-05-09T15:20:00+03:00, got 2026-05-09T16:40:00+03:00',
    ]
