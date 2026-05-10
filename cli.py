"""
CLI for newborn_diary management tasks.

Usage:
    uv run python cli.py import-telegram-export <path-to-export.json>
"""
import argparse
import asyncio
import logging
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')


def _set_verbose() -> None:
    logging.getLogger('application').setLevel(logging.DEBUG)


async def _run_import(export_path: Path, verbose: bool = False) -> None:
    if verbose:
        _set_verbose()
    from contextlib import asynccontextmanager
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from application.services.event_parser import EventParser
    from application.services.llm_client import LLMClient
    from application.services.telegram_export_importer import TelegramExportImporter
    from infrastructure.repositories.event_repository import SqlEventRepository
    from settings import settings

    concurrency = settings.parser.import_concurrency
    engine = settings.postgres.create_engine(pool_size=concurrency)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    @asynccontextmanager
    async def repo_factory() -> AsyncIterator[Any]:
        async with session_maker() as session:
            try:
                yield SqlEventRepository(session)
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    llm = LLMClient(settings.llm)
    parser = EventParser(llm, settings.parser)
    importer = TelegramExportImporter(parser, repo_factory, settings.parser)

    logging.info('Importing %s …', export_path)
    result = await importer.import_file(export_path)

    await engine.dispose()

    print(f'messages_seen:      {result.messages_seen}')
    print(f'events_created:     {result.events_created}')
    print(f'skipped_duplicates: {result.skipped_duplicates}')
    print(f'parse_failures:     {result.parse_failures}')


def main() -> None:
    parser = argparse.ArgumentParser(description='Newborn Diary CLI')
    subparsers = parser.add_subparsers(dest='command', required=True)

    import_parser = subparsers.add_parser(
        'import-telegram-export',
        help='Import Telegram Desktop JSON chat export',
    )
    import_parser.add_argument('path', type=Path, help='Path to the export JSON file')
    import_parser.add_argument('--verbose', '-v', action='store_true', help='Print LLM prompts, responses, and saved events')

    args = parser.parse_args()

    if args.command == 'import-telegram-export':
        if not args.path.exists():
            print(f'Error: file not found: {args.path}', file=sys.stderr)
            sys.exit(1)
        asyncio.run(_run_import(args.path, verbose=args.verbose))


if __name__ == '__main__':
    main()
