import json
from pathlib import Path

import httpx
import pytest
from conftest import PRICING_FILE
from mock_providers import (
    ANTHROPIC_REAL_KEY,
    OPENAI_REAL_KEY,
    SECRET_OUTPUT,
    MockProviders,
)

from tollbooth.domain import LedgerEntry, Outcome, Provider, ProviderCredential, Usage
from tollbooth.pricing import load_pricing
from tollbooth.proxy.sse import SSEParser
from tollbooth.repositories.base import LedgerFilter
from tollbooth.routing import RoutingError, load_routes, parse_routes, plan
from tollbooth.settings import Settings
from tollbooth.state import AppState

ROUTES = """
[routes.fast]
targets = [
  { credential = "openai-main", model = "gpt-5.4-mini" },
  { credential = "anthropic-main", model = "claude-haiku-4-5" },
]

[routes.smart]
targets = [
  { credential = "anthropic-main", model = "claude-sonnet-4-6" },
  { credential = "openai-main", model = "gpt-5.4" },
]

[routes.claude-only]
targets = [{ credential = "anthropic-main", model = "claude-haiku-4-5" }]

[routes.ghost]
targets = [
  { credential = "missing", model = "x" },
  { credential = "openai-main", model = "gpt-5-mini" },
]
"""
PROMPT = "SECRET-PROMPT-CONTENT"
OPENAI_CLIENT = {
    "model": "fast",
    "messages": [
        {"role": "system", "content": "Be brief."},
        {"role": "user", "content": PROMPT},
    ],
}
ANTHROPIC_CLIENT = {
    "model": "smart",
    "max_tokens": 256,
    "system": "Be brief.",
    "messages": [{"role": "user", "content": [{"type": "text", "text": PROMPT}]}],
}
# The mock Anthropic usage, as priced for claude-haiku-4-5 ($1 in, $5 out, 0.1x read,
# 1.25x/2x writes): 10*1000 + 5000*100 + 2000*1250 + 1000*2000 + 300*5000 nanodollars.
HAIKU_NANOUSD = 6_510_000
ANTHROPIC_USAGE = Usage(10, 300, 5000, 2000, 1000)
OPENAI_USAGE = Usage(input_tokens=1134, output_tokens=567, cache_read_tokens=100)


@pytest.fixture
def settings(settings: Settings, tmp_path: Path) -> Settings:
    path = tmp_path / "routes.toml"
    path.write_text(ROUTES)
    return settings.model_copy(update={"routes_file": path})


@pytest.fixture
async def key(client: httpx.AsyncClient, admin_headers: dict[str, str]) -> str:
    """An OpenAI-team key, plus the two credentials the routes name."""
    ids = {}
    for provider, real in (("openai", OPENAI_REAL_KEY), ("anthropic", ANTHROPIC_REAL_KEY)):
        response = await client.post(
            "/admin/credentials",
            json={"name": f"{provider}-main", "provider": provider, "api_key": real},
            headers=admin_headers,
        )
        ids[provider] = response.json()["id"]
    created = await client.post(
        "/admin/keys",
        json={"name": "svc", "team": "search", "credential_id": ids["openai"]},
        headers=admin_headers,
    )
    return created.json()["key"]


async def _entry(state: AppState) -> LedgerEntry:
    [entry] = await state.ledger.page(LedgerFilter())
    return entry


def _events(raw: bytes) -> list[tuple[str | None, object]]:
    events = SSEParser().feed(raw)
    return [
        (e.event, e.data if e.data == "[DONE]" else json.loads(e.data or "null")) for e in events
    ]


class TestConfig:
    def test_missing_file_means_no_routes(self, tmp_path: Path) -> None:
        assert load_routes(tmp_path / "nope.toml") == {}

    @pytest.mark.parametrize(
        "raw",
        [
            {
                "routes": {
                    "r": {"strategy": "fastest", "targets": [{"credential": "c", "model": "m"}]}
                }
            },
            {"routes": {"r": {"targets": []}}},
            {"routes": {"r": {"targets": [{"credential": "c"}]}}},
            {"routes": {"r": {"targets": [{"credential": "c", "model": ""}]}}},
            {"routes": {"r": {"targets": [{"credential": "c", "model": "m"}], "extra": 1}}},
            {"router": {}},
        ],
    )
    def test_invalid_config(self, raw: dict) -> None:
        with pytest.raises(RoutingError):
            parse_routes(raw)

    def test_cheapest_orders_by_price_and_skips_unknown_credentials(self) -> None:
        route = parse_routes(
            {
                "routes": {
                    "cheap": {
                        "strategy": "cheapest",
                        "targets": [
                            {"credential": "openai", "model": "gpt-5.5"},
                            {"credential": "anthropic", "model": "claude-haiku-4-5"},
                            {"credential": "gone", "model": "gpt-5-nano"},
                            {"credential": "openai", "model": "gpt-5-nano"},
                            {"credential": "openai", "model": "unpriced-model"},
                        ],
                    }
                }
            }
        )["cheap"]
        creds = [
            ProviderCredential("1", "openai", Provider.OPENAI, None),  # type: ignore[arg-type]
            ProviderCredential("2", "anthropic", Provider.ANTHROPIC, None),  # type: ignore[arg-type]
        ]
        order = plan(route, creds, load_pricing(PRICING_FILE), Provider.OPENAI, OPENAI_CLIENT)
        assert [m for _, m in order] == [
            "gpt-5-nano",
            "claude-haiku-4-5",
            "gpt-5.5",
            "unpriced-model",
        ]


class TestRouting:
    async def test_route_on_the_same_api(
        self, client: httpx.AsyncClient, key: str, providers: MockProviders, state: AppState
    ) -> None:
        response = await client.post(
            "/v1/chat/completions", json=OPENAI_CLIENT, headers={"Authorization": f"Bearer {key}"}
        )
        assert response.status_code == 200
        assert response.headers["x-tollbooth-model"] == "gpt-5.4-mini"
        [upstream] = providers.received
        assert upstream.json == {**OPENAI_CLIENT, "model": "gpt-5.4-mini"}
        entry = await _entry(state)
        assert (entry.route, entry.attempts, entry.model) == ("fast", 1, "gpt-5.4-mini-2024-07-18")
        assert entry.cost_nanousd == 1134 * 750 + 100 * 75 + 567 * 4500  # gpt-5.4-mini

    async def test_falls_back_across_apis(
        self, client: httpx.AsyncClient, key: str, providers: MockProviders, state: AppState
    ) -> None:
        providers.fail_models["gpt-5.4-mini"] = 503
        response = await client.post(
            "/v1/chat/completions", json=OPENAI_CLIENT, headers={"Authorization": f"Bearer {key}"}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["object"] == "chat.completion"
        assert body["choices"][0]["message"] == {"role": "assistant", "content": SECRET_OUTPUT}
        assert body["choices"][0]["finish_reason"] == "stop"
        assert body["usage"]["prompt_tokens"] == 10 + 5000 + 3000
        assert body["usage"]["completion_tokens"] == 300

        first, second = providers.received
        assert first.url.host == "api.openai.com"
        assert second.url.host == "api.anthropic.com"
        assert second.headers["x-api-key"] == ANTHROPIC_REAL_KEY
        assert second.headers["anthropic-version"] == "2023-06-01"
        assert second.json == {
            "model": "claude-haiku-4-5",
            "system": "Be brief.",
            "messages": [{"role": "user", "content": PROMPT}],
            "max_tokens": 4096,
        }
        entry = await _entry(state)
        assert (entry.provider, entry.model, entry.attempts) == (
            Provider.ANTHROPIC,
            "claude-haiku-4-5",
            2,
        )
        assert entry.usage == ANTHROPIC_USAGE
        assert entry.cost_nanousd == HAIKU_NANOUSD

    @pytest.mark.parametrize("include_usage", [True, False])
    async def test_translates_an_anthropic_stream_into_openai_chunks(
        self,
        client: httpx.AsyncClient,
        key: str,
        providers: MockProviders,
        state: AppState,
        include_usage: bool,
    ) -> None:
        providers.fail_models["gpt-5.4-mini"] = 429
        request = {**OPENAI_CLIENT, "stream": True}
        if include_usage:
            request["stream_options"] = {"include_usage": True}
        response = await client.post(
            "/v1/chat/completions", json=request, headers={"Authorization": f"Bearer {key}"}
        )
        events = _events(response.content)
        assert events[-1] == (None, "[DONE]")
        chunks = [data for _, data in events[:-1]]
        assert all(c["object"] == "chat.completion.chunk" for c in chunks)
        text = "".join(c["choices"][0]["delta"].get("content", "") for c in chunks if c["choices"])
        assert text == SECRET_OUTPUT.replace("-", "")
        finishes = [c["choices"][0]["finish_reason"] for c in chunks if c["choices"]]
        assert finishes[-1] == "stop"
        usage_chunks = [c for c in chunks if not c["choices"]]
        if include_usage:
            assert usage_chunks[0]["usage"]["completion_tokens"] == 300
        else:
            assert usage_chunks == []

        entry = await _entry(state)
        assert (entry.streamed, entry.outcome, entry.attempts) == (True, Outcome.SUCCESS, 2)
        assert entry.usage == ANTHROPIC_USAGE
        assert entry.cost_nanousd == HAIKU_NANOUSD

    async def test_translates_for_an_anthropic_client(
        self, client: httpx.AsyncClient, key: str, providers: MockProviders, state: AppState
    ) -> None:
        providers.fail_models["claude-sonnet-4-6"] = 529
        response = await client.post(
            "/v1/messages", json=ANTHROPIC_CLIENT, headers={"x-api-key": key}
        )
        assert response.status_code == 200
        body = response.json()
        assert (body["type"], body["role"], body["stop_reason"]) == (
            "message",
            "assistant",
            "end_turn",
        )
        assert body["content"] == [{"type": "text", "text": SECRET_OUTPUT}]
        assert body["usage"] == {
            "input_tokens": 1134,
            "output_tokens": 567,
            "cache_read_input_tokens": 100,
            "cache_creation_input_tokens": 0,
        }
        assert providers.received[1].json == {
            "model": "gpt-5.4",
            "messages": [
                {"role": "system", "content": "Be brief."},
                {"role": "user", "content": PROMPT},
            ],
            "max_completion_tokens": 256,
        }
        entry = await _entry(state)
        assert (entry.provider, entry.route, entry.attempts) == (Provider.OPENAI, "smart", 2)
        assert entry.usage == OPENAI_USAGE

    async def test_translates_an_openai_stream_into_anthropic_events(
        self, client: httpx.AsyncClient, key: str, providers: MockProviders, state: AppState
    ) -> None:
        providers.fail_models["claude-sonnet-4-6"] = "connect"
        response = await client.post(
            "/v1/messages",
            json={**ANTHROPIC_CLIENT, "stream": True},
            headers={"x-api-key": key},
        )
        events = _events(response.content)
        names = [name for name, _ in events]
        assert names[:2] == ["message_start", "content_block_start"]
        assert names[-3:] == ["content_block_stop", "message_delta", "message_stop"]
        text = "".join(d["delta"]["text"] for n, d in events if n == "content_block_delta")
        assert text == SECRET_OUTPUT.replace("-", "")
        delta = next(d for n, d in events if n == "message_delta")
        assert delta["delta"]["stop_reason"] == "end_turn"
        assert delta["usage"]["output_tokens"] == 567
        assert providers.received[-1].json["stream_options"] == {"include_usage": True}
        entry = await _entry(state)
        assert (entry.usage, entry.attempts) == (OPENAI_USAGE, 2)

    async def test_non_retryable_errors_do_not_fall_back(
        self, client: httpx.AsyncClient, key: str, providers: MockProviders, state: AppState
    ) -> None:
        providers.fail_models["gpt-5.4-mini"] = 400
        response = await client.post(
            "/v1/chat/completions", json=OPENAI_CLIENT, headers={"Authorization": f"Bearer {key}"}
        )
        assert response.status_code == 400
        assert len(providers.received) == 1
        entry = await _entry(state)
        assert (entry.outcome, entry.attempts) == (Outcome.UPSTREAM_ERROR, 1)

    async def test_when_every_target_fails_the_last_error_is_returned_in_the_client_format(
        self, client: httpx.AsyncClient, key: str, providers: MockProviders, state: AppState
    ) -> None:
        providers.fail_models |= {"gpt-5.4-mini": 503, "claude-haiku-4-5": 529}
        response = await client.post(
            "/v1/chat/completions", json=OPENAI_CLIENT, headers={"Authorization": f"Bearer {key}"}
        )
        assert response.status_code == 529
        assert response.json() == {
            "error": {
                "message": "upstream anthropic returned HTTP 529",
                "type": "overloaded_error",
                "param": None,
                "code": None,
            }
        }
        assert PROMPT not in response.text
        entry = await _entry(state)
        assert (entry.outcome, entry.attempts, entry.model) == (
            Outcome.UPSTREAM_ERROR,
            2,
            "claude-haiku-4-5",
        )

    async def test_requests_with_tools_only_use_targets_on_their_own_api(
        self, client: httpx.AsyncClient, key: str, providers: MockProviders
    ) -> None:
        tools = {"tools": [{"type": "function", "function": {"name": "f", "parameters": {}}}]}
        auth = {"Authorization": f"Bearer {key}"}
        response = await client.post(
            "/v1/chat/completions", json={**OPENAI_CLIENT, "model": "smart", **tools}, headers=auth
        )
        assert response.status_code == 200
        assert [r.json["model"] for r in providers.received] == ["gpt-5.4"]

        none = await client.post(
            "/v1/chat/completions",
            json={**OPENAI_CLIENT, "model": "claude-only", **tools},
            headers=auth,
        )
        assert none.status_code == 400
        assert "no target" in none.json()["error"]["message"]

    async def test_unknown_credentials_are_skipped(
        self, client: httpx.AsyncClient, key: str, state: AppState
    ) -> None:
        response = await client.post(
            "/v1/chat/completions",
            json={**OPENAI_CLIENT, "model": "ghost"},
            headers={"Authorization": f"Bearer {key}"},
        )
        assert response.status_code == 200
        entry = await _entry(state)
        assert (entry.model, entry.attempts) == ("gpt-5-mini-2024-07-18", 1)

    async def test_routes_work_from_either_endpoint_with_any_key(
        self, client: httpx.AsyncClient, key: str
    ) -> None:
        # An OpenAI-team key can call the Anthropic endpoint by route name...
        routed = await client.post(
            "/v1/messages", json=ANTHROPIC_CLIENT, headers={"x-api-key": key}
        )
        assert routed.status_code == 200
        # ...but not with a plain model, which stays bound to the key's own provider.
        plain = await client.post(
            "/v1/messages",
            json={**ANTHROPIC_CLIENT, "model": "claude-sonnet-4-6"},
            headers={"x-api-key": key},
        )
        assert plain.status_code == 400

    async def test_budgets_still_apply(
        self,
        client: httpx.AsyncClient,
        key: str,
        admin_headers: dict[str, str],
        providers: MockProviders,
    ) -> None:
        await client.post(
            "/admin/budgets",
            json={
                "name": "search",
                "scope": {"type": "team", "value": "search"},
                "period": "day",
                "limit_usd": "0.000000001",
                "enforcement": "hard",
            },
            headers=admin_headers,
        )
        auth = {"Authorization": f"Bearer {key}"}
        assert (
            await client.post("/v1/chat/completions", json=OPENAI_CLIENT, headers=auth)
        ).status_code == 200
        blocked = await client.post("/v1/chat/completions", json=OPENAI_CLIENT, headers=auth)
        assert blocked.status_code == 429
        assert len(providers.received) == 1

    async def test_requests_api_reports_the_route(
        self,
        client: httpx.AsyncClient,
        key: str,
        admin_headers: dict[str, str],
        providers: MockProviders,
    ) -> None:
        providers.fail_models["gpt-5.4-mini"] = 503
        await client.post(
            "/v1/chat/completions", json=OPENAI_CLIENT, headers={"Authorization": f"Bearer {key}"}
        )
        [item] = (await client.get("/admin/requests", headers=admin_headers)).json()["items"]
        assert (item["route"], item["attempts"], item["provider"]) == ("fast", 2, "anthropic")
