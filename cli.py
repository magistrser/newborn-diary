"""
CLI for newborn_diary management tasks.

Usage:
    uv run python cli.py import-telegram-export <path-to-export.json>
"""
import argparse
import asyncio
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')


def _set_verbose() -> None:
    logging.getLogger('application').setLevel(logging.DEBUG)


async def _run_import(export_path: Path, verbose: bool = False) -> None:
    if verbose:
        _set_verbose()
    from infrastructure.composition import NewbornDiaryApplicationFactory

    importer = NewbornDiaryApplicationFactory.telegram_export_importer(
        NewbornDiaryApplicationFactory.event_parser()
    )

    logging.info('Importing %s …', export_path)
    result = await importer.import_file(export_path)

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
    import_parser.add_argument(
        '--verbose', '-v', action='store_true',
        help='Print LLM prompts, responses, and saved events',
    )

    args = parser.parse_args()

    if args.command == 'import-telegram-export':
        if not args.path.exists():
            print(f'Error: file not found: {args.path}', file=sys.stderr)
            sys.exit(1)
        asyncio.run(_run_import(args.path, verbose=args.verbose))


if __name__ == '__main__':
    main()
