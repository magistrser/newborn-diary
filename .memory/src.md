# newborn_diary project memory

Last revised: 2026-05-10.

## Purpose

`newborn_diary` is a FastAPI service for storing newborn activity events, parsing free-form
Telegram text into structured events with an OpenAI-compatible LLM, importing Telegram Desktop
exports, and answering natural-language questions through a guarded SQL tool loop.

## Architecture

- `domain/`: event aggregate, payload models, enums, and deterministic domain validation.
- `application/`: DTOs, ports, use cases, parser orchestration, SQL validation, QA orchestration,
  and Telegram export import workflow. It must not import `infrastructure`.
- `infrastructure/`: FastAPI endpoints, dependencies, SQLAlchemy models/repositories, migrations,
  OpenAI/http/SQL adapters, metrics, and composition.
- `infrastructure/composition.py`: canonical composition root. Use it to build FastAPI apps,
  LLM clients, parsers, SQL executors, use cases, and importers.
- `main.py`: FastAPI app entrypoint only.
- `cli.py`: management CLI that goes through the composition root.

## Core behavior

- `POST /api/v1/events/from-text` is idempotent by physical Telegram message:
  `(source_chat_id, source_message_id)` returns existing events across live/import source types.
- Parser context uses recent events before `occurred_at`, controlled by parser settings.
- Patch validates the effective payload against the effective event type before updating.
- Agentic QA validates generated SQL deterministically before infrastructure executes a read-only
  query through SQLAlchemy.

## Guardrails

- Keep external OpenAI, SQLAlchemy, FastAPI, filesystem, and settings wiring in infrastructure.
- Keep application behavior testable with in-memory ports.
- Keep database schema and HTTP response shapes backward compatible unless a task explicitly asks
  for a migration/API change.
- Do not put generated Python artifacts under `application`, `domain`, or `infrastructure`.

## Verification

Use a cache prefix so verification does not write `__pycache__` into source packages:

- `PYTHONPYCACHEPREFIX=/tmp/newborn-diary-pyc .venv/bin/flake8`
- `PYTHONPYCACHEPREFIX=/tmp/newborn-diary-pyc .venv/bin/mypy .`
- `PYTHONPYCACHEPREFIX=/tmp/newborn-diary-pyc .venv/bin/pytest -q`
