# Newborn Diary

Application for storing and querying newborn activity events (sleep, feeding, diapers, etc.).
Uses a local Qwen3 LLM (OpenAI-compatible) for free-text parsing and SQL-based question answering.

## Requirements

- Python 3.14.3 (`uv` manages the venv)
- PostgreSQL (run via docker-compose)
- Local Qwen3 LLM server (OpenAI-compatible, default `http://localhost:41234/v1`)

## Setup

```bash
# 1. Start Postgres
docker-compose -p diary -f docker-compose.dev.yml up -d

# 2. Install deps
uv sync

# 3. Run migrations
uv run alembic upgrade head

# 4. Start the API (dev mode, port 8001)
uv run fastapi dev --port 8001
```

## Key endpoints

| Method | Path | Description |
|---|---|---|
| POST | `/api/v1/events` | Create one structured event |
| GET | `/api/v1/events` | List events (`?from=&to=&type=&limit=&order=`) |
| POST | `/api/v1/events/from-text` | Parse free-form Russian message via LLM |
| POST | `/api/v1/ask` | Answer a natural-language question |
| POST | `/api/v1/admin/import/telegram-export` | Import Telegram Desktop JSON export |
| GET | `/health` | Health check |
| GET | `/metrics` | Prometheus metrics |

## Examples

```bash
# Create event directly
curl -X POST http://localhost:8001/api/v1/events \
  -H 'Content-Type: application/json' \
  -d '{"type":"feed_breast","occurred_at":"2026-05-09T11:42:56Z","payload":{"side":"right"}}'

# Parse wife's message
curl -X POST http://localhost:8001/api/v1/events/from-text \
  -H 'Content-Type: application/json' \
  -d '{"text":"Подгузник\nЛевая","occurred_at":"2026-05-09T13:07:48Z"}'

# Ask a question
curl -X POST http://localhost:8001/api/v1/ask \
  -H 'Content-Type: application/json' \
  -d '{"question":"Сколько спал вчера?"}'

# Import historical export
curl -X POST http://localhost:8001/api/v1/admin/import/telegram-export \
  -F 'file=@/path/to/result.json'

# Or via CLI
uv run python cli.py import-telegram-export /path/to/result.json
```

## Configuration

Edit `settings.dev.yml` (committed, for development).
Copy to `settings.yml` (gitignored) for production.

Key settings:
- `postgres.*` — database connection
- `llm.base_url` — LLM server URL (default `http://localhost:41234/v1`)
- `llm.model` — model name as registered in the LLM server
- `parser.authors` — list of Telegram author names whose messages are auto-parsed
- `qa.max_tool_iterations` — max SQL tool calls per question before forcing a final answer
- `qa.sql_row_cap` — max rows returned per SQL query
- `qa.user_timezone` — timezone used when interpreting relative date expressions in questions

## Tests

```bash
# Unit tests (no DB required)
uv run pytest -s --ignore=tests/

# Integration tests (requires running Postgres)
uv run pytest -s tests/
```
