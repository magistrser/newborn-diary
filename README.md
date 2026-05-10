# newborn_diary

FastAPI HTTP service that stores and queries newborn activity events. Uses a local LLM (Qwen3,
OpenAI-compatible API) for free-text parsing and SQL-based question answering.

---

## Overview

Parents log baby events by sending free-form Russian text to a Telegram chat.
`newborn_diary` receives those messages (forwarded by `telegram_adapter`), parses them into
structured events via LLM, stores them in Postgres, and answers natural-language questions about
the data by having the LLM generate SQL.

---

## Requirements

- Python 3.14.3 (`uv` manages the venv)
- PostgreSQL (via docker-compose)
- Local LLM server, OpenAI-compatible — default `http://localhost:41234/v1`

---

## Quick start

```bash
# 1. Start Postgres
docker-compose -p diary -f docker-compose.dev.yml up -d

# 2. Install deps
uv sync

# 3. Run migrations
uv run alembic upgrade head

# 4. Start the API (dev mode, port 8001, hot-reload on .py changes)
uv run fastapi dev --port 8001
```

---

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/events` | Create one structured event |
| GET | `/api/v1/events` | List events (`?from=&to=&type=&limit=&order=`) |
| GET | `/api/v1/events/{id}` | Get single event |
| PATCH | `/api/v1/events/{id}` | Update `occurred_at`, `type`, and/or `payload` |
| DELETE | `/api/v1/events/{id}` | Delete event |
| POST | `/api/v1/events/from-text` | Parse free-form Russian text via LLM and store events |
| POST | `/api/v1/ask` | Answer a natural-language question via agentic SQL |
| POST | `/api/v1/admin/import/telegram-export` | Bulk-import Telegram Desktop JSON export |
| GET | `/health` | Health check |
| GET | `/metrics` | Prometheus metrics |

### `POST /api/v1/events/from-text` — idempotency

If `source_chat_id` + `source_message_id` are provided and those events already exist in the DB,
the endpoint returns the stored events without re-parsing. This is the deduplication guard used
when both the live bot and the import path might process the same message.

### `POST /api/v1/ask` response shape

```json
{
  "answer": "...",
  "used_window": {"mode": "agentic", "iterations": 2, "queries": ["SELECT ..."]},
  "sources": ["uuid1", "uuid2"]
}
```

`sources` contains UUIDs of events referenced in the SQL result (only rows where `id` is a column).

---

## Configuration

`ENVIRONMENT` env var selects the settings file:
- `DEVELOPMENT` / unset → `settings.dev.yml`
- `TEST` → `settings.test.yml`
- `PRODUCTION` → `settings.yml`

Key settings in `settings.dev.yml`:

```yaml
postgres:
  host: localhost
  port: 5432
  db_name: newborn_diary
  user: diary
  password: diary
  pool_size: 5

llm:
  base_url: http://localhost:41234/v1
  api_key: not-needed          # local LLM, no auth
  model: qwen3-235b-a22b       # or whatever the server registers
  max_tokens: 2048
  request_timeout_sec: 600
  tasks:                       # per-task LLM overrides (all optional)
    agentic_qa:
      model: qwen3-8b
      max_tokens: 1024

parser:
  context_window_hours: 12     # how far back to look for "recent events" context
  authors: ["Mila"]            # Telegram author names to accept during import
  import_concurrency: 4        # parallel tasks during bulk import
  timezone: Europe/Moscow

qa:
  max_tool_iterations: 5       # cap on SQL calls per question
  sql_row_cap: 200             # max rows returned per SQL query
  sql_statement_timeout_ms: 3000
  user_timezone: Europe/Moscow
  agent_max_tokens: 1024

verbose: false                 # enables DEBUG logging for the application logger
```

`llm.tasks.<name>` lets you route different tasks to different models or backends.
Currently used task names: `agentic_qa`.

---

## Architecture

```
newborn_diary/
├── domain/
│   └── event.py          — Event aggregate + all payload Pydantic models + enums
├── application/
│   ├── dto.py                    — use-case commands/results/config DTOs
│   ├── ports.py                  — repository, LLM, SQL executor, transaction ports
│   ├── use_cases.py              — event CRUD + parse-and-create orchestration
│   └── services/
│       ├── event_parser.py       — LLM-based free-text → Event list
│       ├── schema_prompt.py      — Generates the SQL system prompt dynamically from domain models
│       ├── agentic_qa_service.py — Multi-turn LLM+tool loop for answering questions
│       ├── sql_tool.py           — deterministic SQL validation and source extraction
│       └── telegram_export_importer.py — Bulk import from Telegram Desktop JSON
├── infrastructure/
│   ├── endpoints/v1/     — FastAPI routers: events, ask, admin_import
│   ├── composition.py     — composition root for app/use-case/client wiring
│   ├── llm_client.py      — AsyncOpenAI adapter
│   ├── sql_executor.py    — SQLAlchemy SELECT executor for the QA SQL tool
│   ├── models/event.py   — SQLAlchemy ORM model
│   ├── repositories/     — SqlEventRepository (concrete implementation)
│   ├── migrations/       — Alembic migration scripts
│   ├── dependencies/     — FastAPI Depends factories (DB session, LLM, repo)
│   └── metrics/          — Prometheus instrumentation
├── settings.py           — Pydantic settings loaded from YAML
├── main.py               — FastAPI app factory + lifespan
└── cli.py                — CLI wrapper (import-telegram-export command)
```

### Layering rules

- `domain/` has no imports from other local packages.
- `application/` imports from `domain/`, defines ports, and must not import `infrastructure/`.
- `infrastructure/` imports from `application/` and `domain/` (never the reverse).

---

## Database schema

```sql
CREATE TABLE events (
    id                UUID PRIMARY KEY,
    occurred_at       TIMESTAMPTZ NOT NULL,    -- when the event happened (use for queries)
    recorded_at       TIMESTAMPTZ NOT NULL,    -- when it was stored
    type              VARCHAR(50) NOT NULL,
    payload           JSONB NOT NULL,
    raw_text          TEXT,
    source_type       VARCHAR(50) NOT NULL,    -- 'telegram_live' | 'telegram_export' | 'api' | 'telegram_quick_action'
    source_message_id VARCHAR(255),
    source_chat_id    BIGINT,
    source_event_index SMALLINT NOT NULL DEFAULT 0,  -- position within a single message (0-based)
    parser_version    VARCHAR(50),             -- 'llm-v1' | 'manual'

    CONSTRAINT uq_events_source UNIQUE (source_type, source_chat_id, source_message_id, source_event_index)
);
CREATE INDEX ix_events_occurred_at ON events (occurred_at);
CREATE INDEX ix_events_type ON events (type);
```

`uq_events_source` prevents duplicate imports. One Telegram message can produce multiple events
(e.g. "Подгузник\nЛевая" → diaper + feed_breast); `source_event_index` is the 0-based position
within that message.

### Migration history

- **0001** — initial `events` table with `uq_events_source` on 3 columns
- **0002** — added `source_event_index`; rebuilt `uq_events_source` to include it

---

## Event model

All events share:

| Field | Type | Notes |
|-------|------|-------|
| `id` | UUID | generated |
| `occurred_at` | TIMESTAMPTZ | when the event happened |
| `recorded_at` | TIMESTAMPTZ | when stored to DB |
| `type` | EventType (str enum) | see below |
| `payload` | dict / JSONB | type-specific fields |
| `raw_text` | str or null | original message text |
| `source_type` | str | origin system |
| `source_message_id` | str or null | Telegram message ID |
| `source_chat_id` | int or null | Telegram chat ID |
| `source_event_index` | int | 0-based index within source message |
| `parser_version` | str or null | `llm-v1` or `manual` |

### Event types and payload fields

| Type | Payload fields |
|------|---------------|
| `sleep_start` | _(none)_ |
| `sleep_end` | `duration_min?: int` |
| `sleep_interval` | `started_at: datetime`, `ended_at: datetime` |
| `feed_breast` | `side: left\|right`, `duration_min?: int` |
| `feed_bottle` | `volume_ml?: int`, `contents: formula\|expressed` |
| `pump` | `volume_ml?: int`, `duration_min?: int` |
| `diaper` | `kind: pee\|poo\|both\|unknown` |
| `weight` | `grams: int` |
| `temperature` | `celsius: float`, `method: rectal\|axillary\|forehead` |
| `medication` | `name: str`, `dose_ml?: float` |
| `vaccination` | `vaccine: str` |
| `doctor_visit` | `type: routine\|sick`, `notes?: str` |
| `bath` | `duration_min?: int` |
| `tummy_time` | `duration_min?: int` |
| `walk` | `duration_min?: int` |
| `spit_up` | `volume: small\|large` |
| `crying` | `duration_min?: int`, `reason: hunger\|gas\|unknown` |
| `gas` | _(none)_ |
| `father_calming` | `duration_min?: int` |
| `note` | `text: str` |

---

## LLM integration

### LLMClient (`application/services/llm_client.py`)

Uses `AsyncOpenAI` pointed at the local LLM server. Three methods:

- `chat_json(messages)` — expects the model to return JSON; strips thinking tags and code fences,
  then `json.loads`. Temperature 0.1.
- `chat_text(messages)` — plain text response. Temperature 0.3.
- `chat_with_tools(messages, tools)` — OpenAI tool-call protocol. Temperature 0.2.

**Thinking-tag stripping** (`_strip_thinking`): Qwen3 reasoning models emit `<think>...</think>`
blocks before the actual answer. These are stripped from all responses. Also handles the
`<|channel>...<channel|>` variant.

**Code-fence unwrapping** (`_extract_json`): if the model wraps JSON in a ` ```json ... ``` ` block,
the fence is stripped before parsing.

### Event parser (`application/services/event_parser.py`)

Converts one Russian Telegram message into a list of structured `Event` objects.

**Time extraction rule (critical):** If the message text contains an explicit time (e.g. "13:25",
"в 19:26", "с 13:00 до 15:30"), that time is used as `occurred_at` — taking the date and `+03:00`
offset from `message_date`. If no explicit time is present, `message_date` is used as-is. This is
explicitly documented in the system prompt and is the most important parsing rule.

**Context window:** The parser receives `recent_events` — up to 30 events from the preceding
`context_window_hours` (default 12h). These appear in the prompt as a compact `HH:MM type payload`
summary. Used for rules like "if there is no active sleep_start and user asks '?Заснул' — create
sleep_start".

**Payload normalisation** (`_normalise_payload`): After the LLM response is parsed, enum fields
(side, kind, contents, method, volume, reason, type) are validated against the allowed values and
coerced to defaults if the LLM returns something invalid. This prevents DB validation errors from
LLM hallucinations.

**Fallback to `note`:** If LLM output fails Pydantic validation entirely, or if a single event
in the list has an unknown type, that event is stored as `note` with the raw text. At least one
event is always returned.

### Agentic QA (`application/services/agentic_qa_service.py`)

Multi-turn agent loop: LLM is given an `execute_sql` tool and iterates until it either returns
a text answer (no tool call) or exhausts `max_tool_iterations`.

At the iteration cap, a forced follow-up message `"Answer now based on the data already gathered
above."` is appended and one final `chat_text` call is made.

SQL tool results are JSON-serialised and truncated to 8000 characters before being appended to the
message list.

### SQL tool safety (`application/services/sql_tool.py`)

All SQL from the LLM is validated using `sqlglot` AST parsing before execution:

- Must be exactly one `SELECT` statement (CTEs are allowed).
- Tables: only `events` (plus CTE aliases) — any other table name raises `SqlValidationError`.
- Denied node types: INSERT, UPDATE, DELETE, MERGE, CREATE, DROP, ALTER, TRUNCATE, GRANT, REVOKE,
  TRANSACTION, COMMIT, ROLLBACK, COMMAND.
- Denied functions: `pg_read_file`, `pg_ls_dir`, `pg_read_binary_file`, `dblink`, `dblink_exec`,
  `lo_import`, `lo_export`.
- Denied schemas: `pg_catalog`, `information_schema`.

Execution uses `SET LOCAL statement_timeout = '...ms'` + a savepoint; the savepoint is always
rolled back so no side-effects leak even if something slips through validation.

### Schema prompt (`application/services/schema_prompt.py`)

The SQL system prompt is generated at query time by reflecting the actual domain models — it lists
every event type and its payload fields with SQL types. This means adding a new event type to
`domain/event.py` automatically appears in the QA prompt without manual edits.

The prompt includes:
- Full `CREATE TABLE` DDL with comments.
- How to access JSONB fields (`payload->>'field'`, casts).
- Timezone handling rules (always filter by Moscow calendar day, not UTC).
- **Feeding session grouping SQL pattern** (left+right breast within 30 min = 1 session).

---

## Feeding session counting

Left breast + right breast feedings within 30 minutes are counted as **one** feeding session.
This logic is baked into the QA system prompt as a SQL pattern using `LAG` + running sum.
Any question about "how many feedings" or "feeding frequency" must use this pattern.

---

## Telegram export import

`TelegramExportImporter.import_data(data)` processes a Telegram Desktop `result.json`:

1. Filters messages by `msg.type == 'message'` and `parser.authors` (if non-empty).
2. Sorts by date ascending.
3. Processes up to `import_concurrency` messages concurrently using `asyncio.Semaphore`.
4. For each message: checks `exists_by_source` first (skip if duplicate), then fetches
   `recent_events` for context, calls `EventParser.parse_message`, stores with `save_many`.
5. `save_many` uses `ON CONFLICT DO NOTHING` so re-running the import is idempotent.

**Timestamp handling:** Telegram Desktop exports timestamps in local machine time without timezone.
`_parse_tg_datetime` treats naive timestamps as `parser.timezone` (Moscow). This matches how
the bot records live events.

**Text extraction:** The `text` field in Telegram export can be a string or a list of mixed
strings and dicts (`{"type": "...", "text": "..."}`). `_extract_text` joins all text parts.

Also available via CLI:
```bash
uv run python cli.py import-telegram-export /path/to/result.json
```

---

## Hacks and non-obvious decisions

- **AsyncOpenAI for a local LLM**: the LLM server speaks the OpenAI chat completions API. Using
  `openai.AsyncOpenAI` with a custom `base_url` and `api_key='not-needed'` is simpler than a raw
  httpx client and gives tool-call support for free.

- **`_normalise_payload` coerces LLM output**: LLMs sometimes return `"Left"` instead of `"left"`.
  Rather than failing, bad enum values are replaced with their defaults silently.

- **`schema_prompt.py` generates the QA prompt from domain models**: avoids the prompt drifting out
  of sync when new event types are added. The `_unwrap_optional` helper is needed because Python
  3.10+ `X | None` syntax produces `types.UnionType`, not `typing.Union`.

- **PATCH validation re-runs the payload model**: `PATCH /events/{id}` fetches the stored event,
  merges new fields, and re-validates the payload against the (possibly new) type's Pydantic model.
  If type changes without explicit payload, the old payload is persisted as-is.

- **`from-text` deduplication**: the endpoint first checks `list_by_source_message`. If events
  already exist for that `(chat_id, message_id)` pair, they are returned without re-parsing.
  This handles a race where the live bot and a bulk import might process the same message.

- **`sleep_interval` duration math in the system prompt**: "слала полтора часа" → the LLM is
  instructed to set `started_at = message_date - 90 min`, `ended_at = message_date`. This
  approximation is by design when no explicit start time is given.

- **`note` as safety net**: if the LLM returns a completely unrecognisable event type, the parser
  creates a `note` with the raw text rather than dropping the message.

- **Metrics**: thin Prometheus wrapper in `infrastructure/metrics/`. Available at `/metrics`.

---

## Tests

```bash
# Unit tests (no DB, no LLM)
uv run pytest -s --ignore=tests/

# Integration tests (require running Postgres in docker-compose.dev.yml)
uv run pytest -s tests/
```

Integration tests use `settings.test.yml` (set `ENVIRONMENT=TEST` automatically via `pytest.ini`).
Test DB is `newborn_diary_test`; created by `docker-init/create_test_db.sql`.
