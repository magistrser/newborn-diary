import logging
import logging.config
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from infrastructure.endpoints import root_router
from settings import settings


def _configure_verbose_logging() -> None:
    logging.config.dictConfig({
        'version': 1,
        'disable_existing_loggers': False,
        'formatters': {
            'verbose': {'format': '%(levelname)s %(name)s %(message)s'},
        },
        'handlers': {
            'verbose_stdout': {
                'class': 'logging.StreamHandler',
                'stream': 'ext://sys.stdout',
                'level': 'DEBUG',
                'formatter': 'verbose',
            },
        },
        'loggers': {
            'application': {
                'handlers': ['verbose_stdout'],
                'level': 'DEBUG',
                'propagate': False,
            },
        },
    })
    logging.getLogger('application').info('Verbose logging enabled')


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[dict]:
    if settings.verbose:
        _configure_verbose_logging()
    yield {}


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=['http://localhost:8000'],
    allow_methods=['*'],
    allow_headers=['*'],
)


app.include_router(root_router)
