# Tollbooth v0.1.0

First release. An open-source proxy that meters every OpenAI and Anthropic request.

- Transparent proxy for OpenAI chat completions and Anthropic messages, including streaming.
- Virtual keys per team; real provider keys encrypted at rest. Prompts and responses are never stored.
- Request ledger with tokens, exact cost (nanodollars), latency and attribution.
- Dashboard: spend by team/model/provider, budgets, keys, request log, users and settings.
- Budgets (soft/hard, per team/key/global) with Slack and signed-webhook alerts.
- Multi-user accounts with roles, API tokens, audit log. SQLite or Postgres.
- Model routing: fallbacks, cheapest-first, OpenAI <-> Anthropic text translation.

Run it:

```
docker run -p 8080:8080 ghcr.io/maybesayon/tollbooth:0.1.0
```

See the README for compose files and configuration.
