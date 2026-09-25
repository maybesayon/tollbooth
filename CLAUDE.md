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
  api/               FastAPI routers: proxy, /admin keys+credentials, /admin ledger reporting
  dashboard.py       serves the built dashboard at /dashboard (SPA fallback to index.html)
  migrations/        Alembic migrations (packaged so the app can migrate on startup)
backend/pricing.toml per-model prices, editable without code changes
```

Request flow: proxy route -> authenticate virtual key -> decrypt provider credential -> forward via
shared `httpx.AsyncClient` -> (stream bytes through unchanged while an SSE parser extracts usage) ->
compute cost -> write one ledger row in a `finally` block.

Streaming usage:
- Anthropic: input/cache tokens in `message_start`, output tokens in `message_delta` (cumulative).
- OpenAI: Tollbooth forces `stream_options.include_usage=true` and reads the final usage chunk. If
  the client did not request usage, that chunk is stripped before it reaches the client. The
  `"usage": null` field OpenAI then adds to every other chunk is left alone: events are forwarded
  byte-for-byte, never re-serialized.
- Usage is normalized (`domain.Usage`): `input_tokens` excludes cache reads/writes, so OpenAI's
  `prompt_tokens` has `cached_tokens` subtracted, and each bucket is priced at its own rate.
- A client disconnect cancels the relay; the ledger write is shielded from cancellation and the
  row is recorded with outcome `client_disconnected` and whatever usage had arrived.

Budgets (`budgets.py`, `periods.py`):
- A budget limits spend per UTC calendar period (day, week from Monday, month) for everything, a
  team, or one virtual key. `soft` budgets only alert; `hard` budgets make the proxy answer 429
  (`budget_exceeded`, provider error shape, `Retry-After` = seconds to period end) and ledger the
  refusal with outcome `budget_exceeded`.
- `BudgetTracker` caches budget list and per-period spend for `ttl_seconds` and adds each recorded
  cost in between. Hard limits can be overshot by in-flight requests (cost is known only after the
  response). A failing budget check fails open (logged), never blocks traffic.
- Call `budget_tracker.invalidate()` after any budget change.

Alerts (`alerts.py`):
- After each ledger write, `AlertManager.evaluate` checks the touched budgets' thresholds. An alert
  is created at most once per (budget, period, threshold); the DB unique constraint is the source
  of truth, so this holds across processes and restarts. Thresholds crossed together are recorded
  but only the highest is delivered (the rest get `skipped` deliveries).
- Delivery runs in background tasks with retries (1s, 5s, 25s); every attempt updates an
  `alert_deliveries` row. Channel URLs and webhook signing secrets are Fernet-encrypted; only the
  host (`url_hint`) is ever returned. Stored delivery errors are an HTTP status or exception type,
  never a message (messages can contain the URL, which for Slack is the secret).
- Webhooks: JSON `budget.threshold_crossed` events, signed as
  `X-Tollbooth-Signature: v1=hex(HMAC-SHA256(secret, "{X-Tollbooth-Timestamp}.{body}"))`.
  Slack channels get `{"text": ...}`.

Auth (`auth.py`, `deps.py`, `api/auth_routes.py`, `api/user_routes.py`):
- Every `/admin` request resolves to a `Principal`: a user via the session cookie or a `tbu_` API
  token, or the optional admin token. Roles are global and ordered viewer < editor < admin;
  routes declare `Viewer`/`Editor`/`Admin` (routers default to viewer).
- Sessions and API tokens are random 256-bit tokens stored as SHA-256; passwords are Argon2id
  (hashed off the event loop). Cookie-authenticated unsafe requests need `X-Tollbooth-CSRF: 1`.
- Login failures are indistinguishable (unknown email still costs a hash) and throttled in memory.
- The last active admin can't be demoted or disabled, and admins can't demote themselves.

## Conventions

- Python 3.12, full type hints, small modules, no decorative comments or banner comments.
- Everything is async; one shared `httpx.AsyncClient` created in the lifespan.
- Storage is accessed only through the repository Protocols in `repositories/base.py`. The SQL
  implementation runs on SQLite (default) and Postgres (`postgresql+asyncpg://`); both are tested.
- Postgres rules: connections run in UTC (`db.create_engine`), `SUM(bigint)` returns Decimal so
  aggregates are cast with `int()`, and text columns reject NUL and enforce lengths. Anything
  client- or provider-supplied that reaches the ledger goes through `metering._fit`; API text uses
  `api/fields.Name`/`Text`; a middleware rejects NUL in paths and query strings.
- Settings come only from environment variables (see `.env.example`).
- Schema changes: edit `db.py`, then autogenerate a migration and review it. Migrations use plain
  SQLAlchemy types (never import from `tollbooth`). `test_migrations_match_metadata` catches drift.
- Tests use in-process mock providers (ASGI apps) injected into the upstream httpx client. No real
  API keys, no network. Cost assertions compare exact `Decimal` values.
- Commands (run in `backend/`): `uv run ruff check`, `uv run ruff format`, `uv run pytest`.
  `TOLLBOOTH_TEST_POSTGRES_URL=postgresql+asyncpg://user@host/postgres uv run pytest` runs the
  suite on Postgres (a fresh database per test, cloned from a migrated template).
- CLI: `tollbooth copy-db SOURCE TARGET`, `tollbooth create-user` (`cli.py`).
- Work on feature branches; open PRs into `main`; CI (ruff, pytest, docker build + smoke test) must pass.
- Docker: build context is the repo root; the image runs `uvicorn tollbooth.main:create_app --factory`
  as a non-root user, with SQLite in the `/app/data` volume and `pricing.toml` mounted read-only.

## Dashboard (`dashboard/`)

- React 19 + TypeScript (strict) + Vite, TanStack Query for server state, React Router, Recharts.
- Served by the backend at `/dashboard` (`TOLLBOOTH_DASHBOARD_DIR`); `npm run dev` proxies `/admin`.
- Auth: email/password session cookie (HttpOnly); send `X-Tollbooth-CSRF: 1` on writes; any 401 signs out.
- USD stays a decimal string from the API until display (`lib/format.ts`); never do money math in
  floats beyond chart heights.
- Colors are CSS tokens in `index.css` (light + dark). Chart series use `--series-1..7` in fixed
  order via `ColorRegistry` (color follows the entity), overflow folds into "Other". Status colors
  are reserved for badges, which always pair color with an icon and label.
- Filters live in the URL search params. Tests use `test/fakeApi.ts` (stubbed fetch, per-path routes).
- Commands (in `dashboard/`): `npm run lint`, `npm run format`, `npm run typecheck`, `npm test`.

## Roadmap

- **Phase 1** (done): transparent proxy for OpenAI chat completions and Anthropic messages,
  virtual keys, request ledger, streaming metering, pricing config, admin API, Docker, CI.
- **Phase 2** (done): React + TypeScript + Vite dashboard in `dashboard/`: overview (spend tiles,
  stacked spend chart, breakdown), key and credential management, request log.
- **Phase 3** (done): budgets (soft/hard, per team/key/global, UTC day/week/month) and alerts
  (Slack + signed webhooks), with a dashboard Budgets page. (per team/key limits, soft/hard enforcement, notifications).
- **Phase 4** (in progress): Postgres (done), multi-user accounts and roles (backend done), audit
  log, dashboard sign-in and user management.
- **Phase 5**: model routing (fallbacks, cost/latency-aware routing, provider translation).
