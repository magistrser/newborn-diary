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


class LLMTaskSettings(BaseModel):
    base_url: str | None = Field(default=None)
    api_key: str | None = Field(default=None)
    model: str | None = Field(default=None)
    max_tokens: int | None = Field(default=None)
    request_timeout_sec: int | None = Field(default=None)


class LLMSettings(BaseModel):
    base_url: str = Field(...)
    api_key: str = Field(default='not-needed')
    model: str = Field(...)
    max_tokens: int = Field(default=2048)
    request_timeout_sec: int = Field(default=600)
    tasks: dict[str, LLMTaskSettings] = Field(default_factory=dict)

    def for_task(self, task: str) -> 'LLMSettings':
        override = self.tasks.get(task)  # pylint: disable=no-member
        if override is None:
            return self
        updates = {k: v for k, v in override.model_dump().items() if v is not None}
        return self.model_copy(update=updates)


class ParserSettings(BaseModel):
    context_window_hours: int = Field(default=12)
    authors: list[str] = Field(default_factory=list)
    import_concurrency: int = Field(default=4)
    timezone: str = Field(default='Europe/Moscow')


class QASettings(BaseModel):
    max_tool_iterations: int = Field(default=5)
    sql_row_cap: int = Field(default=200)
    sql_statement_timeout_ms: int = Field(default=3000)
    user_timezone: str = Field(default='Europe/Moscow')
    agent_max_tokens: int = Field(default=1024)


class Settings(BaseModel):
    postgres: PostgresSettings = Field(...)
    llm: LLMSettings = Field(...)
    parser: ParserSettings = Field(default_factory=ParserSettings)
    qa: QASettings = Field(default_factory=QASettings)
    verbose: bool = Field(default=False)


def load_settings(environment: str | None = None) -> Settings:
    root_dir = Path(__file__).parent

    match environment:
        case 'DEVELOPMENT' | None:
            settings_path = root_dir / 'settings.dev.yml'
        case 'TEST':
            settings_path = root_dir / 'settings.test.yml'
        case 'BENCHMARK':
            settings_path = root_dir / 'settings.benchmark.yml'
        case 'PRODUCTION':
            settings_path = root_dir / 'settings.yml'
        case invalid:
            raise ValueError(f'Failed to initialize settings. Invalid ENVIRONMENT variable: {invalid}')

    with open(settings_path, 'r', encoding='utf-8') as settings_file:
        return Settings.model_validate(safe_load(settings_file))


def get_settings() -> Settings:
    return load_settings(environ.get('ENVIRONMENT'))


settings = get_settings()
