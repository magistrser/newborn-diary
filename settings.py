from os import environ
from pathlib import Path

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from yaml import safe_load


class PostgresSettings(BaseModel):
    host: str = Field(...)
    port: int = Field(...)
    db_name: str = Field(...)
    user: str = Field(...)
    password: str = Field(...)
    pool_size: int = Field(...)

    def get_async_url(self) -> str:
        return f'postgresql+asyncpg://{self.user}:{self.password}@{self.host}:{self.port}/{self.db_name}'

    def get_sync_url(self) -> str:
        return f'postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.db_name}'

    def create_engine(self, pool_size: int | None = None) -> AsyncEngine:
        return create_async_engine(
            url=self.get_async_url(),
            pool_pre_ping=True,
            pool_size=pool_size if pool_size is not None else self.pool_size,
            echo=False,
        )


class LLMSettings(BaseModel):
    base_url: str = Field(...)
    api_key: str = Field(default='not-needed')
    model: str = Field(...)
    parser_max_tokens: int = Field(default=1024)
    qa_max_tokens: int = Field(default=2048)
    request_timeout_sec: int = Field(default=600)


class ParserSettings(BaseModel):
    context_window_hours: int = Field(default=12)
    authors: list[str] = Field(default_factory=list)
    import_concurrency: int = Field(default=4)
    timezone: str = Field(default='Europe/Moscow')


class QASettings(BaseModel):
    default_window_days: int = Field(default=14)


class Settings(BaseModel):
    postgres: PostgresSettings = Field(...)
    llm: LLMSettings = Field(...)
    parser: ParserSettings = Field(default_factory=ParserSettings)
    qa: QASettings = Field(default_factory=QASettings)
    verbose: bool = Field(default=False)


def get_settings() -> Settings:
    root_dir = Path(__file__).parent
    environment = environ.get('ENVIRONMENT')

    match environment:
        case 'DEVELOPMENT' | 'TEST' | None:
            settings_path = root_dir / 'settings.dev.yml'
        case 'PRODUCTION':
            settings_path = root_dir / 'settings.yml'
        case invalid:
            raise Exception(f'Failed to initialize settings. Invalid ENVIRONMENT variable: {invalid}')

    with open(settings_path, 'r') as settings_file:
        return Settings.model_validate(safe_load(settings_file))


settings = get_settings()
