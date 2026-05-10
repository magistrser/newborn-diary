"""
Imports a Telegram Desktop chat export (JSON format) into the events database.

Idempotent: messages already present (matched by source_type + source_chat_id + source_message_id)
are silently skipped via the uq_events_source unique constraint.
"""
import asyncio
import json
import logging
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from application.repositories.event_repository import AbstractEventRepository
from application.services.event_parser import EventParser
from settings import ParserSettings

logger = logging.getLogger(__name__)

RepoFactory = Callable[[], AbstractAsyncContextManager[AbstractEventRepository]]


@dataclass
class ImportResult:
    messages_seen: int
    events_created: int
    skipped_duplicates: int
    parse_failures: int


@dataclass
class _Counters:
    messages_seen: int = 0
    events_created: int = 0
    skipped_duplicates: int = 0
    parse_failures: int = 0

    def add(self, *, seen: int = 0, created: int = 0, dupes: int = 0, failures: int = 0) -> None:
        # Safe without a lock: asyncio is single-threaded and integer addition never yields.
        self.messages_seen += seen
        self.events_created += created
        self.skipped_duplicates += dupes
        self.parse_failures += failures


def _parse_tg_datetime(raw: str, tz: ZoneInfo) -> datetime:
    # Telegram Desktop exports timestamps in local machine time without tzinfo.
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    return dt.astimezone(timezone.utc)


class TelegramExportImporter:

    def __init__(
        self,
        parser: EventParser,
        repo_factory: RepoFactory,
        parser_settings: ParserSettings,
    ) -> None:
        self._parser = parser
        self._repo_factory = repo_factory
        self._settings = parser_settings

    async def import_file(self, path: Path) -> ImportResult:
        data = json.loads(path.read_text(encoding='utf-8'))
        return await self.import_data(data)

    async def import_data(self, data: dict[str, Any]) -> ImportResult:
        messages = data.get('messages', [])
        allowed_authors = set(self._settings.authors)
        chat_id = int(data.get('id', 0))
        tz = ZoneInfo(self._settings.timezone)

        candidates = sorted(
            (
                msg for msg in messages
                if msg.get('type') == 'message'
                and (not allowed_authors or msg.get('from', '') in allowed_authors)
                and _extract_text(msg.get('text', '')).strip()
            ),
            key=lambda m: m.get('date', ''),
        )

        counters = _Counters()
        sem = asyncio.Semaphore(self._settings.import_concurrency)

        async def process(msg: dict[str, Any]) -> None:
            msg_id = str(msg.get('id', ''))
            date_str = msg.get('date', '')
            raw_text = _extract_text(msg.get('text', ''))

            try:
                msg_dt = _parse_tg_datetime(date_str, tz)
            except (ValueError, TypeError):
                logger.warning('Could not parse date "%s" for message %s', date_str, msg_id)
                counters.add(failures=1)
                return

            counters.add(seen=1)

            async with sem, self._repo_factory() as repo:
                if msg_id and await repo.exists_by_source('telegram_export', chat_id, msg_id):
                    counters.add(dupes=1)
                    return

                try:
                    context_start = msg_dt - timedelta(hours=self._settings.context_window_hours)
                    recent = await repo.list(from_dt=context_start, to_dt=msg_dt, limit=30)
                    events = await self._parser.parse_message(
                        text=raw_text,
                        message_date=msg_dt,
                        recent_events=recent,
                        source_type='telegram_export',
                        source_message_id=msg_id,
                        source_chat_id=chat_id,
                    )
                    saved = await repo.save_many(events)
                    counters.add(created=len(saved))
                    for e in saved:
                        logger.debug(
                            'saved [msg %s] %s %s %s',
                            msg_id,
                            e.occurred_at.strftime('%Y-%m-%d %H:%M'),
                            e.type,
                            json.dumps(e.payload, ensure_ascii=False),
                        )
                except Exception as exc:
                    logger.error('Failed to parse message %s: %s', msg_id, exc)
                    counters.add(failures=1)

        await asyncio.gather(*(process(msg) for msg in candidates))

        return ImportResult(
            messages_seen=counters.messages_seen,
            events_created=counters.events_created,
            skipped_duplicates=counters.skipped_duplicates,
            parse_failures=counters.parse_failures,
        )


def _extract_text(text_field: Any) -> str:
    """Telegram export text field can be a string or a list of text fragments."""
    if isinstance(text_field, str):
        return text_field
    if isinstance(text_field, list):
        parts = []
        for item in text_field:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(item.get('text', ''))
        return ''.join(parts)
    return ''
