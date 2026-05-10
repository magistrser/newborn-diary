import json
import logging

from fastapi import File, HTTPException, UploadFile
from pydantic import BaseModel

from infrastructure.composition import NewbornDiaryApplicationFactory
from infrastructure.dependencies.llm import EventParserDep
from infrastructure.endpoints.v1.router import router

logger = logging.getLogger(__name__)


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

    importer = NewbornDiaryApplicationFactory.telegram_export_importer(parser)
    result = await importer.import_data(data)
    return ImportResponse(
        messages_seen=result.messages_seen,
        events_created=result.events_created,
        skipped_duplicates=result.skipped_duplicates,
        parse_failures=result.parse_failures,
    )
