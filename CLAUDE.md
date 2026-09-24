# Tollbooth

Open-source LLM cost-metering proxy. Apps point their OpenAI/Anthropic SDK base URL at Tollbooth and
use a Tollbooth virtual key; Tollbooth forwards the request with the team's real provider key and
records tokens, cost, latency, and attribution for every request.

## Hard rules

- **Never log, store, or persist prompt or response content.** This covers the ledger, application
  logs, exception messages, and upstream error messages (providers sometimes echo input in errors).
  The ledger stores only metadata: counts, ids, model, status, error type/code. A test enforces this.
- Store only SHA-256 hashes of virtual keys. The plaintext is returned once, at creation.
- Real provider keys are encrypted at rest (Fernet, `TOLLBOOTH_ENCRYPTION_KEY`), never returned by
  the API, never logged.
- Money is `Decimal` in code and integer nanodollars (1e-9 USD) in storage. Never use `float`.
- Upstream errors pass through with the original status code and body; they are still ledgered.

## Layout

```
backend/src/tollbooth/
  main.py            app factory + lifespan (db engine, upstream httpx client, pricing)
  settings.py        pydantic-settings, env prefix TOLLBOOTH_
  security.py        key generation/hashing, provider-key encryption
  pricing.py         pricing.toml loading and model resolution
  cost.py            pure Decimal cost math
  domain.py          dataclasses shared across layers
  db.py              SQLAlchemy Core tables, engine factory, migration runner
  repositories/      Protocol interfaces (base.py) + SQLAlchemy Core implementation (sql.py)
  providers/         per-provider logic: upstream URL, auth headers, usage extraction, stream parsing
  proxy/             forwarding, incremental SSE parsing, metering + ledger write
  api/               FastAPI routers: proxy routes and /admin routes
  migrations/        Alembic migrations (packaged so the app can migrate on startup)
backend/pricing.toml per-model prices, editable without code changes
```

Request flow: proxy route -> authenticate virtual key -> decrypt provider credential -> forward via
shared `httpx.AsyncClient` -> (stream bytes through unchanged while an SSE parser extracts usage) ->
compute cost -> write one ledger row in a `finally` block.

Streaming usage:
- Anthropic: input/cache tokens in `message_start`, output tokens in `message_delta` (cumulative).
- OpenAI: Tollbooth forces `stream_options.include_usage=true` and reads the final usage chunk. If
  the client did not request usage, that chunk is stripped before it reaches the client.

## Conventions

- Python 3.12, full type hints, small modules, no decorative comments or banner comments.
- Everything is async; one shared `httpx.AsyncClient` created in the lifespan.
- Storage is accessed only through the repository Protocols in `repositories/base.py`, so the
  Postgres implementation in Phase 4 is a driver/URL change plus any dialect fixes.
- Settings come only from environment variables (see `.env.example`).
- Schema changes: edit `db.py`, then autogenerate a migration and review it. Migrations use plain
  SQLAlchemy types (never import from `tollbooth`). `test_migrations_match_metadata` catches drift.
- Tests use in-process mock providers (ASGI apps) injected into the upstream httpx client. No real
  API keys, no network. Cost assertions compare exact `Decimal` values.
- Commands (run in `backend/`): `uv run ruff check`, `uv run ruff format`, `uv run pytest`.
- Work on feature branches; open PRs into `main`; CI (ruff + pytest) must pass.

## Roadmap

- **Phase 1** (current): transparent proxy for OpenAI chat completions and Anthropic messages,
  virtual keys, request ledger, streaming metering, pricing config, admin API, Docker, CI.
- **Phase 2**: React + TypeScript + Vite dashboard in `dashboard/` (spend over time, per team/model/key).
- **Phase 3**: budgets and alerts (per team/key limits, soft/hard enforcement, notifications).
- **Phase 4**: Postgres repository implementation, multi-user admin accounts and roles.
- **Phase 5**: model routing (fallbacks, cost/latency-aware routing, provider translation).
