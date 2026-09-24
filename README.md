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

Fill in the two required values in `.env`:

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
export ADMIN="Authorization: Bearer $TOLLBOOTH_ADMIN_TOKEN"

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

See where the money went:

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
                                                     │ SQLite (repository  │  ◀── /admin API: keys,
                                                     │ interface; Postgres │      credentials, spend
                                                     │ later)              │
                                                     └─────────────────────┘
```

- **Streaming.** Responses are relayed event by event, byte for byte, while a parser reads usage along the way. Anthropic reports usage in `message_start` and updates it in `message_delta`. For OpenAI, Tollbooth sets `stream_options.include_usage=true`, reads the final usage chunk, and removes that chunk if your client didn't ask for it.
- **Cost.** Every price is a multiple of $0.001 per 1M tokens, so costs are exact integers in nanodollars, never floats. Uncached input, output, cache reads, and cache writes are each billed at their own rate. Each ledger row stores its cost at the time of the request, so later price changes don't rewrite history.
- **Failures still count.** Upstream 4xx/5xx responses, errors mid-stream, unreachable upstreams, and client disconnects all produce a ledger row with an `outcome` and `error_type`.

## Admin API

All routes require `Authorization: Bearer $TOLLBOOTH_ADMIN_TOKEN`. Interactive docs are served at `/docs`.

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

Ledger filters, accepted by all three reporting routes: `start` (inclusive), `end` (exclusive), `team`, `provider`, `model`, `key_id`, `outcome`.

## Configuration

Settings are read from environment variables; see [`.env.example`](.env.example).

| Variable | Default | |
|---|---|---|
| `TOLLBOOTH_ADMIN_TOKEN` | required | Bearer token for `/admin` |
| `TOLLBOOTH_ENCRYPTION_KEY` | required | Fernet key(s) for provider keys. To rotate, list the new key first: `new,old`. |
| `TOLLBOOTH_DATABASE_URL` | `sqlite+aiosqlite:///./data/tollbooth.db` | |
| `TOLLBOOTH_AUTO_MIGRATE` | `true` | Run database migrations on startup |
| `TOLLBOOTH_PRICING_FILE` | `pricing.toml` | |
| `TOLLBOOTH_OPENAI_BASE_URL` | `https://api.openai.com` | |
| `TOLLBOOTH_ANTHROPIC_BASE_URL` | `https://api.anthropic.com` | |
| `TOLLBOOTH_UPSTREAM_CONNECT_TIMEOUT` / `_READ_TIMEOUT` | `10` / `600` | Seconds |
| `TOLLBOOTH_DASHBOARD_DIR` | unset | Built dashboard to serve at `/dashboard` |
| `TOLLBOOTH_LOG_LEVEL` | `INFO` | |

## Pricing

[`backend/pricing.toml`](backend/pricing.toml) lists USD per 1M tokens for each model, grouped by provider. Dated snapshot names such as `gpt-4o-2024-08-06` fall back to the undated entry, and `aliases` covers any other names. Requests for a model with no price are still recorded, with no cost, and are counted as `unpriced_requests` in spend reports. Long-context surcharges and batch/flex/priority tiers are not modeled yet.

## Development

```bash
cd backend
uv sync
uv run pytest
uv run ruff check && uv run ruff format --check
TOLLBOOTH_ADMIN_TOKEN=dev TOLLBOOTH_ENCRYPTION_KEY=... uv run uvicorn tollbooth.main:create_app --factory --reload
```

Tests run against in-process fakes of both provider APIs, so they need no network access or API keys. See [`CLAUDE.md`](CLAUDE.md) for conventions and the roadmap.

## Roadmap

1. **Metering proxy** (done)
2. Web dashboard
3. Budgets and alerts
4. Postgres and multi-user admin
5. Model routing

## License

[MIT](LICENSE)
