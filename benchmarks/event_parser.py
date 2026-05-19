from __future__ import annotations

import argparse
import asyncio
import json
import re
import subprocess
import time
from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from application.dto import ParserConfig
from application.services.event_parser import EventParser
from domain.event import Event
from infrastructure.llm_client import LLMClient
from settings import ParserSettings, load_settings


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_ENVIRONMENT = 'BENCHMARK'
RESULTS_ROOT = PROJECT_ROOT / 'benchmarks' / 'results' / 'event_parser'
ITERATIONS_ROOT = PROJECT_ROOT / 'benchmarks' / 'iterations' / 'event_parser'
_EVENT_REF_RE = re.compile(r'^<event:(\d+)>$')

DEFAULT_CASES: list[dict[str, Any]] = [
    {
        'id': 'sleep-duration-hh-mm-ends-at-message-date',
        'category': 'sleep',
        'text': 'сон 1:20',
        'message_date': '2026-05-09T15:20:00+03:00',
        'expected_events': [
            {'type': 'sleep_start', 'occurred_at': '2026-05-09T14:00:00+03:00', 'payload': {}},
            {
                'type': 'sleep_end',
                'occurred_at': '2026-05-09T15:20:00+03:00',
                'payload': {'duration_min': 80, 'sleep_start_id': '<event:0>'},
            },
        ],
    },
    {
        'id': 'sleep-range-links-start-and-end',
        'category': 'sleep',
        'text': '19:30-21:00 сон',
        'message_date': '2026-05-09T21:00:00+03:00',
        'expected_events': [
            {'type': 'sleep_start', 'occurred_at': '2026-05-09T19:30:00+03:00', 'payload': {}},
            {
                'type': 'sleep_end',
                'occurred_at': '2026-05-09T21:00:00+03:00',
                'payload': {'duration_min': 90, 'sleep_start_id': '<event:0>'},
            },
        ],
    },
    {
        'id': 'diaper-and-left-breast',
        'category': 'mixed',
        'text': 'Подгузник\nЛевая',
        'message_date': '2026-05-09T13:07:48+03:00',
        'expected_events': [
            {'type': 'diaper', 'occurred_at': '2026-05-09T13:07:48+03:00', 'payload': {'kind': 'unknown'}},
            {'type': 'feed_breast', 'occurred_at': '2026-05-09T13:07:48+03:00', 'payload': {'side': 'left'}},
        ],
    },
]


def _parser_config_from_settings(parser_settings: ParserSettings) -> ParserConfig:
    return ParserConfig(
        context_window_hours=parser_settings.context_window_hours,
        authors=parser_settings.authors,
        import_concurrency=parser_settings.import_concurrency,
        timezone=parser_settings.timezone,
    )


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _utc_now_id() -> str:
    return datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')


def _event_dict(event: Event) -> dict[str, Any]:
    return {
        'id': str(event.id),
        'type': event.type.value,
        'occurred_at': event.occurred_at.isoformat(),
        'payload': event.payload,
        'source_event_index': event.source_event_index,
    }


def _same_in_timezone(actual: datetime, expected: str, timezone: ZoneInfo) -> bool:
    actual_local = actual.astimezone(timezone).replace(microsecond=0)
    expected_local = _parse_datetime(expected).astimezone(timezone).replace(microsecond=0)
    return actual_local == expected_local


def _payload_value_matches(expected: object, actual: object, events: list[Event]) -> bool:
    if isinstance(expected, str):
        match = _EVENT_REF_RE.match(expected)
        if match:
            event_index = int(match.group(1))
            return event_index < len(events) and actual == str(events[event_index].id)
    return actual == expected


def score_case(case: dict[str, Any], events: list[Event], timezone_name: str = 'Europe/Moscow') -> dict[str, Any]:
    timezone = ZoneInfo(timezone_name)
    failures = []
    expected_events = case.get('expected_events') or []

    if len(events) != len(expected_events):
        failures.append(f'expected {len(expected_events)} events, got {len(events)}')

    for index, expected in enumerate(expected_events[:len(events)]):
        actual = events[index]
        expected_type = expected.get('type')
        if actual.type.value != expected_type:
            failures.append(f'event {index}: expected type {expected_type}, got {actual.type.value}')

        expected_at = expected.get('occurred_at')
        if expected_at and not _same_in_timezone(actual.occurred_at, expected_at, timezone):
            failures.append(
                f'event {index}: expected occurred_at {expected_at}, got {actual.occurred_at.isoformat()}'
            )

        expected_payload = expected.get('payload') or {}
        for key, expected_value in expected_payload.items():
            actual_value = actual.payload.get(key)
            if not _payload_value_matches(expected_value, actual_value, events):
                failures.append(f'event {index}: expected payload {key}={expected_value!r}, got {actual_value!r}')

    return {'passed': not failures, 'failures': failures}


async def run_case(parser: EventParser, case: dict[str, Any], timezone_name: str) -> dict[str, Any]:
    started = time.perf_counter()
    events: list[Event] = []
    error: str | None = None
    try:
        events = await parser.parse_message(case['text'], _parse_datetime(case['message_date']), [])
    except Exception as exc:  # pylint: disable=broad-exception-caught
        error = str(exc)

    latency_ms = int((time.perf_counter() - started) * 1000)
    score = score_case(case, events, timezone_name)
    if error:
        score['passed'] = False
        score['failures'].append(error)

    return {
        'case': case,
        'latency_ms': latency_ms,
        'events': [_event_dict(event) for event in events],
        'score': score,
    }


async def run_cases(cases: Sequence[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    settings = load_settings(BENCHMARK_ENVIRONMENT)
    parser = EventParser(
        LLMClient(settings.llm.for_task('parser')),
        _parser_config_from_settings(settings.parser),
    )
    timezone_name = settings.parser.timezone
    return [await run_case(parser, case, timezone_name) for case in cases or DEFAULT_CASES]


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


def write_outputs(run_result: dict[str, Any]) -> tuple[Path, Path]:
    RESULTS_ROOT.mkdir(parents=True, exist_ok=True)
    ITERATIONS_ROOT.mkdir(parents=True, exist_ok=True)

    json_path = RESULTS_ROOT / f'{run_result["run_id"]}.json'
    json_path.write_text(
        json.dumps(run_result, ensure_ascii=False, indent=2, default=_json_default) + '\n',
        encoding='utf-8',
    )

    previous = _latest_result_before(run_result['run_id'])
    summary = run_result['summary']
    git = run_result['git']
    lines = [
        f"# Event Parser Benchmark Iteration {run_result['run_id']}",
        '',
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

    lines.extend(['', '## Failures', ''])
    failures = [result for result in run_result['case_results'] if not result['score']['passed']]
    if not failures:
        lines.append('All benchmark cases passed.')
    for result in failures:
        case = result['case']
        lines.extend([
            f"### `{case['id']}`",
            '',
            f"- Text: `{case['text']}`",
            f"- Message date: `{case['message_date']}`",
            f"- Failures: {'; '.join(result['score']['failures'])}",
            f"- Latency: {result['latency_ms']} ms",
            '- Parsed events:',
            '',
            '```json',
            json.dumps(result['events'], ensure_ascii=False, indent=2),
            '```',
            '',
        ])

    markdown_path = ITERATIONS_ROOT / f'{run_result["run_id"]}.md'
    markdown_path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return json_path, markdown_path


async def run_benchmark(notes: str = '') -> tuple[dict[str, Any], Path, Path]:
    settings = load_settings(BENCHMARK_ENVIRONMENT)
    case_results = await run_cases()
    run_result = {
        'run_id': _utc_now_id(),
        'notes': notes,
        'settings': {
            'environment': BENCHMARK_ENVIRONMENT,
            'llm_model': settings.llm.for_task('parser').model,
            'llm_base_url': settings.llm.for_task('parser').base_url,
            'parser_timezone': settings.parser.timezone,
        },
        'git': collect_git_metadata(),
        'summary': _summarize_results(case_results),
        'case_results': case_results,
    }
    json_path, markdown_path = write_outputs(run_result)
    return run_result, json_path, markdown_path


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='Event message parser benchmark suite')
    subparsers = parser.add_subparsers(dest='command', required=True)
    run_parser = subparsers.add_parser('run', help='Run parser benchmarks against the configured parser LLM')
    run_parser.add_argument('--notes', default='')
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == 'run':
        result, json_path, markdown_path = asyncio.run(run_benchmark(notes=args.notes))
        summary = result['summary']
        print(f"Benchmark result: {summary['passed']}/{summary['total']} passed")
        print(f'Raw result: {json_path}')
        print(f'Iteration:  {markdown_path}')
        return 0

    parser.error(f'Unhandled command: {args.command}')
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
