# Tollbooth

An open-source proxy that meters every OpenAI and Anthropic request by team, model, and key, so you know exactly where your LLM spend goes.

Apps keep using the official SDKs. They change two things, the base URL and the API key, and every request is recorded with its token counts, cost, latency, and owner. Prompts and responses are never stored.

## Features

- Transparent proxy for OpenAI `POST /v1/chat/completions` and Anthropic `POST /v1/messages`, streaming and non-streaming
- Per-team virtual keys mapped to real provider keys. Virtual keys are stored only as hashes; provider keys are encrypted at rest.
- A ledger row for every request: tokens (including cache reads and writes), exact cost, latency, time to first byte, status, and outcome
- Spend reports grouped by team, model, provider, or key, with date ranges
- Prices in [`backend/pricing.toml`](backend/pricing.toml): edit the file and restart, no code changes
- Upstream errors reach the client unchanged and are still recorded

## Quickstart

```bash
git clone https://github.com/maybesayon/tollbooth.git && cd tollbooth
cp .env.example .env
```

Fill in `.env`: the encryption key is required, and the admin token lets you create the first admin account from the dashboard:

```bash
python3 -c "import secrets; print('TOLLBOOTH_ADMIN_TOKEN=' + secrets.token_urlsafe(32))"
python3 -c "import base64, os; print('TOLLBOOTH_ENCRYPTION_KEY=' + base64.urlsafe_b64encode(os.urandom(32)).decode())"
```

Start it:

```bash
docker compose up -d
```

Register a real provider key, then issue a virtual key for a team:

```bash
set -a; source .env; set +a
export ADMIN="Authorization: Bearer $TOLLBOOTH_ADMIN_TOKEN"   # or a personal API token (tbu_…)

curl -s localhost:8080/admin/credentials -H "$ADMIN" -H "content-type: application/json" \
  -d '{"name": "openai-prod", "provider": "openai", "api_key": "sk-..."}'
# => {"id": "3f2a...", ...}

curl -s localhost:8080/admin/keys -H "$ADMIN" -H "content-type: application/json" \
  -d '{"name": "search-api", "team": "search", "credential_id": "3f2a..."}'
# => {"key": "tb_...", ...}   shown once; store it
```

Point your app at Tollbooth:

```python
from openai import OpenAI
client = OpenAI(base_url="http://localhost:8080/v1", api_key="tb_...")

from anthropic import Anthropic
client = Anthropic(base_url="http://localhost:8080", api_key="tb_...")
```

Open the dashboard at http://localhost:8080/dashboard. The first visit asks for the admin token to create the first admin account (or run `docker compose exec tollbooth tollbooth create-user --email you@example.com --name You`). After that, everyone signs in with email and password. The dashboard shows spend over time by team, model, or provider, budgets and alerts, key management, and a request log. Or ask the API directly:

```bash
curl -s "localhost:8080/admin/spend?group_by=team&start=2026-09-01" -H "$ADMIN"
```

```json
{
  "group_by": "team",
  "total": {"requests": 5, "cost_usd": "0.0400956", "unpriced_requests": 0, "...": "..."},
  "groups": [
    {"group": "ads", "requests": 3, "cost_usd": "0.03906", "...": "..."},
    {"group": "search", "requests": 2, "cost_usd": "0.0010356", "...": "..."}
  ]
}
```

## Architecture

```
  your app (official SDK)                       Tollbooth                               provider
 ┌──────────────────────┐   tb_ virtual key   ┌────────────────────────────────────┐   real key   ┌───────────┐
 │ base_url = tollbooth │ ──────────────────▶ │ 1. hash key → team, credential     │ ───────────▶ │  OpenAI   │
 │                      │                     │ 2. decrypt provider key            │              │     or    │
 │                      │ ◀────────────────── │ 3. forward request                 │ ◀─────────── │ Anthropic │
 └──────────────────────┘  unchanged response │ 4. relay response, SSE parsed      │  JSON / SSE  └───────────┘
                                              │    event by event (never buffered) │
                                              │ 5. usage × pricing.toml → cost     │
                                              │ 6. one ledger row (no content)     │
                                              └─────────────────┬──────────────────┘
                                                                │
                                                     ┌──────────▼──────────┐
                                                     │ SQLite or Postgres  │  ◀── /admin API: keys,
                                                     │ (repository         │      credentials, spend
                                                     │ interface)          │
                                                     └─────────────────────┘
```

- **Streaming.** Responses are relayed event by event, byte for byte, while a parser reads usage along the way. Anthropic reports usage in `message_start` and updates it in `message_delta`. For OpenAI, Tollbooth sets `stream_options.include_usage=true`, reads the final usage chunk, and removes that chunk if your client didn't ask for it.
- **Cost.** Every price is a multiple of $0.001 per 1M tokens, so costs are exact integers in nanodollars, never floats. Uncached input, output, cache reads, and cache writes are each billed at their own rate. Each ledger row stores its cost at the time of the request, so later price changes don't rewrite history.
- **Budgets.** A hard budget answers requests with a 429 in the provider's error format (with `Retry-After` until the period resets) once its period's spend reaches the limit. Cost is known only after a response, so requests already in flight can overshoot a limit slightly. Soft budgets only alert.
- **Failures still count.** Upstream 4xx/5xx responses, errors mid-stream, unreachable upstreams, and client disconnects all produce a ledger row with an `outcome` and `error_type`.

## Users and access

People sign in to the dashboard with email and password. Each account has one role:

| Role | Can |
|---|---|
| `viewer` | See spend, requests, keys, budgets, alerts, and channels |
| `editor` | Everything a viewer can, plus create and revoke virtual keys and manage budgets and alert channels |
| `admin` | Everything, plus provider credentials and user accounts |

The dashboard session is an HttpOnly, `SameSite=Strict` cookie that lasts 7 days (`TOLLBOOTH_SESSION_TTL_HOURS`). Behind HTTPS, set `TOLLBOOTH_COOKIE_SECURE=true` unless Tollbooth itself sees the HTTPS scheme. Failed sign-ins are throttled per email and per client address. Changing a password signs out that user's other sessions, and disabling a user ends their sessions and stops their API tokens.

Scripts use personal API tokens (`tbu_…`, created under your account, with your role) as `Authorization: Bearer`. `TOLLBOOTH_ADMIN_TOKEN` is optional. When set, it works as a break-glass admin credential and lets the first admin account be created from the dashboard.

## Admin API

Admin routes take an API token (or the admin token) as `Authorization: Bearer …`, or a dashboard session. Interactive docs are served at `/docs`.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/admin/credentials` | Store a real provider key (`name`, `provider`, `api_key`). The key is never returned. |
| `GET` | `/admin/credentials` | List credentials |
| `POST` | `/admin/keys` | Issue a virtual key (`name`, `team`, `credential_id`). The plaintext key is returned once. |
| `GET` | `/admin/keys` | List keys (`?team=`, `?include_revoked=true`) |
| `GET` | `/admin/keys/{id}` | Get one key |
| `POST` | `/admin/keys/{id}/revoke` | Revoke a key. Its ledger history is kept. |
| `GET` | `/admin/spend` | Spend report: `group_by=team\|model\|provider\|key`, plus the ledger filters below |
| `GET` | `/admin/spend/timeseries` | Spend per `interval=day\|hour` bucket (UTC), optionally split by `group_by`; `start` and `end` required |
| `GET` | `/admin/requests` | Ledger entries, newest first, metadata only. Paged with `limit` and `cursor` (`next_cursor` from the previous page). |
| `POST` | `/admin/budgets` | Create a budget: `name`, `scope` (`{"type": "global"\|"team"\|"key", "value": ...}`), `period` (`day`\|`week`\|`month`, UTC), `limit_usd`, `enforcement` (`soft`\|`hard`), `thresholds` (percent, default `[50, 80, 100]`) |
| `GET` | `/admin/budgets` | Budgets with current-period spend, percent used, and whether each is exhausted |
| `GET` / `PATCH` / `DELETE` | `/admin/budgets/{id}` | Read, partially update, or delete a budget |
| `POST` | `/admin/channels` | Add an alert channel: `name`, `type` (`webhook`\|`slack`), `url`. Webhooks get a `signing_secret`, shown once. |
| `GET` / `DELETE` | `/admin/channels`, `/admin/channels/{id}` | List (URL host only) or delete channels |
| `POST` | `/admin/channels/{id}/test` | Send a test notification |
| `GET` / `POST` | `/admin/users` | List or create users (admin); omit `password` to get a one-time temporary password |
| `PATCH` | `/admin/users/{id}` | Change `name`, `role`, or `disabled`. The last active admin cannot be demoted or disabled. |
| `POST` | `/admin/users/{id}/reset-password` | Issue a temporary password and end the user's sessions |
| `POST` | `/auth/login`, `/auth/logout` | Dashboard sign-in and sign-out (session cookie) |
| `GET` | `/auth/me` | The signed-in user and role |
| `POST` | `/auth/password` | Change your password (`current_password`, `new_password`, at least 12 characters) |
| `GET` / `POST` / `DELETE` | `/auth/tokens` | Your API tokens; a new token is shown once |
| `GET` | `/admin/alerts` | Recent threshold alerts with per-channel delivery status (`?budget_id=`, `?limit=`) |

Budgets take `channel_ids` to choose where their alerts go.

Ledger filters, accepted by all three reporting routes: `start` (inclusive), `end` (exclusive), `team`, `provider`, `model`, `key_id`, `outcome`.

## Budget alerts

When a budget's spend crosses one of its thresholds (default 50%, 80%, 100%), Tollbooth sends one alert per threshold per period to the budget's channels, retrying failed deliveries up to three times. If several thresholds are crossed at once, only the highest is sent; the others are recorded as skipped. Slack channels get a readable message. Webhook channels get a JSON event:

```json
{
  "type": "budget.threshold_crossed",
  "threshold_percent": 80,
  "spend_usd": "80.12",
  "limit_usd": "100",
  "period": {"type": "month", "start": "2026-09-01T00:00:00Z", "end": "2026-10-01T00:00:00Z"},
  "budget": {"id": "…", "name": "search monthly", "scope": {"type": "team", "value": "search"}, "enforcement": "hard"}
}
```

Verify webhook requests by recomputing the signature and rejecting stale timestamps:

```python
import hashlib, hmac, time

def verify(secret: str, headers, body: bytes) -> bool:
    timestamp = headers["X-Tollbooth-Timestamp"]
    expected = "v1=" + hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()
    fresh = abs(time.time() - int(timestamp)) < 300
    return fresh and hmac.compare_digest(expected, headers["X-Tollbooth-Signature"])
```

## Configuration

Settings are read from environment variables; see [`.env.example`](.env.example).

| Variable | Default | |
|---|---|---|
| `TOLLBOOTH_ADMIN_TOKEN` | unset | Optional break-glass admin credential; enables first-run setup in the dashboard |
| `TOLLBOOTH_SESSION_TTL_HOURS` | `168` | Dashboard session lifetime |
| `TOLLBOOTH_COOKIE_SECURE` | auto | `true` behind HTTPS termination; by default the cookie is Secure when the request is HTTPS |
| `TOLLBOOTH_ENCRYPTION_KEY` | required | Fernet key(s) for provider keys. To rotate, list the new key first: `new,old`. |
| `TOLLBOOTH_DATABASE_URL` | `sqlite+aiosqlite:///./data/tollbooth.db` | Or `postgresql+asyncpg://…` |
| `TOLLBOOTH_AUTO_MIGRATE` | `true` | Run database migrations on startup |
| `TOLLBOOTH_PRICING_FILE` | `pricing.toml` | |
| `TOLLBOOTH_OPENAI_BASE_URL` | `https://api.openai.com` | |
| `TOLLBOOTH_ANTHROPIC_BASE_URL` | `https://api.anthropic.com` | |
| `TOLLBOOTH_UPSTREAM_CONNECT_TIMEOUT` / `_READ_TIMEOUT` | `10` / `600` | Seconds |
| `TOLLBOOTH_DASHBOARD_DIR` | unset | Built dashboard to serve at `/dashboard` |
| `TOLLBOOTH_LOG_LEVEL` | `INFO` | |

## Database

SQLite is the default and needs no setup. For several replicas or larger volumes, use Postgres by setting `TOLLBOOTH_DATABASE_URL=postgresql+asyncpg://user:password@host:5432/tollbooth` (URL-encode special characters in the password). Migrations run on startup either way.

With Docker, the Postgres override starts a database next to Tollbooth. Set `POSTGRES_PASSWORD` in `.env`, then:

```bash
docker compose -f docker-compose.yml -f docker-compose.postgres.yml up -d
```

To move an existing SQLite install to Postgres, stop Tollbooth and copy the data into the empty database. The target is migrated first, and the copy runs in one transaction, so a failure leaves it empty:

```bash
docker compose stop tollbooth
docker compose -f docker-compose.yml -f docker-compose.postgres.yml run --rm tollbooth tollbooth copy-db \
  sqlite+aiosqlite:////app/data/tollbooth.db \
  postgresql+asyncpg://tollbooth:PASSWORD@postgres:5432/tollbooth
```

## Pricing

[`backend/pricing.toml`](backend/pricing.toml) lists USD per 1M tokens for each model, grouped by provider. Dated snapshot names such as `gpt-4o-2024-08-06` fall back to the undated entry, and `aliases` covers any other names. Requests for a model with no price are still recorded, with no cost, and are counted as `unpriced_requests` in spend reports. Long-context surcharges and batch/flex/priority tiers are not modeled yet.

## Development

```bash
cd dashboard && npm install && npm run dev   # http://localhost:5173/dashboard/, proxies to :8080
```

```bash
cd backend
uv sync
uv run pytest
uv run ruff check && uv run ruff format --check
TOLLBOOTH_ADMIN_TOKEN=dev TOLLBOOTH_ENCRYPTION_KEY=... uv run uvicorn tollbooth.main:create_app --factory --reload
```

Tests run against in-process fakes of both provider APIs, so they need no network access or API keys. They use SQLite by default; set `TOLLBOOTH_TEST_POSTGRES_URL=postgresql+asyncpg://user@localhost:5432/postgres` to run the same suite against Postgres (each test gets a fresh database; the user needs `CREATEDB`). See [`CLAUDE.md`](CLAUDE.md) for conventions and the roadmap.

## Roadmap

1. **Metering proxy** (done)
2. **Web dashboard** (done)
3. **Budgets and alerts** (done)
4. **Postgres and multi-user accounts** (done)
5. Model routing

## License

[MIT](LICENSE)
