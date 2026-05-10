import json
import logging
from contextlib import asynccontextmanager

from fastapi import File, HTTPException, UploadFile
from pydantic import BaseModel

from application.services.telegram_export_importer import TelegramExportImporter
from infrastructure.dependencies.db_session import ASYNC_SESSION
from infrastructure.dependencies.llm import EventParserDep
from infrastructure.endpoints.v1.router import router
from infrastructure.repositories.event_repository import SqlEventRepository
from settings import settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _repo_factory():
    async with ASYNC_SESSION() as session:
        try:
            yield SqlEventRepository(session)
            await session.commit()
        except Exception:
            await session.rollback()
            raise


class ImportResponse(BaseModel):
    messages_seen: int
    events_created: int
    skipped_duplicates: int
    parse_failures: int


@router.post(
    '/admin/import/telegram-export',
    name='Import Telegram Chat Export',
    response_model=ImportResponse,
)
async def import_telegram_export(
    parser: EventParserDep,
    file: UploadFile = File(..., description='Telegram Desktop JSON chat export'),
) -> ImportResponse:
    content = await file.read()
    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f'Invalid JSON: {exc}') from exc

    importer = TelegramExportImporter(parser, _repo_factory, settings.parser)
    result = await importer.import_data(data)
    return ImportResponse(
        messages_seen=result.messages_seen,
        events_created=result.events_created,
        skipped_duplicates=result.skipped_duplicates,
        parse_failures=result.parse_failures,
    )
