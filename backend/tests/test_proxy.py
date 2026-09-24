import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import anyio
import httpx
import pytest
from fastapi import FastAPI
from mock_providers import (
    ANTHROPIC_EXPECTED_NANOUSD,
    ANTHROPIC_OUTPUT_TOKENS,
    ANTHROPIC_REAL_KEY,
    OPENAI_EXPECTED_NANOUSD,
    OPENAI_REAL_KEY,
    SECRET_OUTPUT,
    MockProviders,
    anthropic_stream,
    openai_stream,
)

from tollbooth.domain import LedgerEntry, Outcome, Provider, Usage
from tollbooth.repositories.base import LedgerFilter
from tollbooth.state import AppState

SECRET_PROMPT = "SECRET-PROMPT-CONTENT"
OPENAI_BODY = {"model": "gpt-4o-mini", "messages": [{"role": "user", "content": SECRET_PROMPT}]}
ANTHROPIC_BODY = {
    "model": "claude-sonnet-4-6",
    "max_tokens": 1024,
    "messages": [{"role": "user", "content": SECRET_PROMPT}],
}
ANTHROPIC_HEADERS = {"anthropic-version": "2023-06-01"}
ANTHROPIC_USAGE = Usage(
    input_tokens=10,
    output_tokens=ANTHROPIC_OUTPUT_TOKENS,
    cache_read_tokens=5000,
    cache_write_tokens=2000,
    cache_write_1h_tokens=1000,
)
OPENAI_USAGE = Usage(input_tokens=1134, output_tokens=567, cache_read_tokens=100)

MakeKey = Callable[..., Awaitable[str]]


@pytest.fixture
def providers() -> MockProviders:
    return MockProviders()


@pytest.fixture
def upstream_transport(providers: MockProviders) -> httpx.AsyncBaseTransport:
    return providers.transport


@pytest.fixture
def make_key(client: httpx.AsyncClient, admin_headers: dict[str, str]) -> MakeKey:
    async def make(provider: Provider, team: str = "search") -> str:
        real = OPENAI_REAL_KEY if provider is Provider.OPENAI else ANTHROPIC_REAL_KEY
        cred = await client.post(
            "/admin/credentials",
            json={"name": f"{provider}-{team}", "provider": provider, "api_key": real},
            headers=admin_headers,
        )
        key = await client.post(
            "/admin/keys",
            json={"name": "svc", "team": team, "credential_id": cred.json()["id"]},
            headers=admin_headers,
        )
        return key.json()["key"]

    return make


def _read_all_files(directory: Path) -> bytes:
    return b"".join(p.read_bytes() for p in sorted(directory.iterdir()))


async def _only_entry(state: AppState) -> LedgerEntry:
    entries = await state.ledger.page(LedgerFilter())
    assert len(entries) == 1
    return entries[0]


async def test_openai_non_streaming(
    client: httpx.AsyncClient, make_key: MakeKey, providers: MockProviders, state: AppState
) -> None:
    key = await make_key(Provider.OPENAI)
    response = await client.post(
        "/v1/chat/completions", json=OPENAI_BODY, headers={"Authorization": f"Bearer {key}"}
    )
    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == SECRET_OUTPUT
    assert response.headers["x-request-id"] == "req_openai_1"
    assert response.headers["openai-processing-ms"] == "42"

    [upstream] = providers.received
    assert upstream.url == "https://api.openai.com/v1/chat/completions"
    assert upstream.headers["authorization"] == f"Bearer {OPENAI_REAL_KEY}"
    assert key not in str(upstream.headers.raw)
    assert upstream.json == OPENAI_BODY

    entry = await _only_entry(state)
    assert entry.provider is Provider.OPENAI
    assert entry.team == "search"
    assert entry.model == "gpt-4o-mini-2024-07-18"
    assert entry.outcome is Outcome.SUCCESS
    assert entry.status_code == 200
    assert not entry.streamed
    assert entry.usage == OPENAI_USAGE
    assert entry.cost_nanousd == OPENAI_EXPECTED_NANOUSD == 517_800
    assert entry.upstream_request_id == "req_openai_1"
    assert entry.ttfb_ms is None


async def test_anthropic_non_streaming(
    client: httpx.AsyncClient, make_key: MakeKey, providers: MockProviders, state: AppState
) -> None:
    key = await make_key(Provider.ANTHROPIC)
    response = await client.post(
        "/v1/messages", json=ANTHROPIC_BODY, headers={"x-api-key": key, **ANTHROPIC_HEADERS}
    )
    assert response.status_code == 200
    assert response.json()["content"][0]["text"] == SECRET_OUTPUT

    [upstream] = providers.received
    assert upstream.headers["x-api-key"] == ANTHROPIC_REAL_KEY
    assert upstream.headers["anthropic-version"] == "2023-06-01"
    assert "authorization" not in upstream.headers

    entry = await _only_entry(state)
    assert entry.model == "claude-sonnet-4-6"
    assert entry.usage == ANTHROPIC_USAGE
    assert entry.cost_nanousd == ANTHROPIC_EXPECTED_NANOUSD
    assert entry.upstream_request_id == "req_anthropic_1"


@pytest.mark.parametrize("chunk_size", [0, 1, 7, 64])
async def test_openai_streaming_injects_usage_and_hides_it(
    client: httpx.AsyncClient,
    make_key: MakeKey,
    providers: MockProviders,
    state: AppState,
    chunk_size: int,
) -> None:
    key = await make_key(Provider.OPENAI)
    response = await client.post(
        "/v1/chat/completions",
        json={**OPENAI_BODY, "stream": True},
        headers={"Authorization": f"Bearer {key}", "x-mock-chunk-size": str(chunk_size)},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")

    [upstream] = providers.received
    assert upstream.json["stream_options"] == {"include_usage": True}

    upstream_bytes = openai_stream("gpt-4o-mini-2024-07-18", include_usage=True)
    usage_event = upstream_bytes.split(b"\n\n")[-3] + b"\n\n"
    assert b'"choices": []' in usage_event
    assert response.content == upstream_bytes.replace(usage_event, b"")
    assert response.content.endswith(b"data: [DONE]\n\n")

    entry = await _only_entry(state)
    assert entry.streamed
    assert entry.outcome is Outcome.SUCCESS
    assert entry.usage == OPENAI_USAGE
    assert entry.cost_nanousd == OPENAI_EXPECTED_NANOUSD
    assert entry.ttfb_ms is not None


async def test_openai_streaming_keeps_usage_when_client_asked(
    client: httpx.AsyncClient, make_key: MakeKey, providers: MockProviders, state: AppState
) -> None:
    key = await make_key(Provider.OPENAI)
    body = {**OPENAI_BODY, "stream": True, "stream_options": {"include_usage": True}}
    response = await client.post(
        "/v1/chat/completions", json=body, headers={"Authorization": f"Bearer {key}"}
    )
    assert response.content == openai_stream("gpt-4o-mini-2024-07-18", include_usage=True)
    assert providers.received[0].json == body
    assert (await _only_entry(state)).cost_nanousd == OPENAI_EXPECTED_NANOUSD


@pytest.mark.parametrize("chunk_size", [0, 1, 5, 100])
async def test_anthropic_streaming_is_byte_identical(
    client: httpx.AsyncClient,
    make_key: MakeKey,
    providers: MockProviders,
    state: AppState,
    chunk_size: int,
) -> None:
    key = await make_key(Provider.ANTHROPIC)
    raw = json.dumps({**ANTHROPIC_BODY, "stream": True}).encode()
    response = await client.post(
        "/v1/messages",
        content=raw,
        headers={"x-api-key": key, "x-mock-chunk-size": str(chunk_size), **ANTHROPIC_HEADERS},
    )
    assert response.status_code == 200
    assert response.content == anthropic_stream("claude-sonnet-4-6")
    assert providers.received[0].content == raw

    entry = await _only_entry(state)
    assert entry.streamed
    assert entry.outcome is Outcome.SUCCESS
    assert entry.usage == ANTHROPIC_USAGE
    assert entry.cost_nanousd == ANTHROPIC_EXPECTED_NANOUSD


@pytest.mark.parametrize("stream", [False, True])
async def test_upstream_error_passes_through(
    client: httpx.AsyncClient, make_key: MakeKey, state: AppState, stream: bool
) -> None:
    key = await make_key(Provider.OPENAI)
    response = await client.post(
        "/v1/chat/completions",
        json={**OPENAI_BODY, "stream": stream},
        headers={"Authorization": f"Bearer {key}", "x-mock-scenario": "error_429"},
    )
    assert response.status_code == 429
    assert response.headers["retry-after"] == "7"
    assert response.json()["error"]["type"] == "rate_limit_exceeded"
    assert SECRET_PROMPT in response.json()["error"]["message"]

    entry = await _only_entry(state)
    assert entry.outcome is Outcome.UPSTREAM_ERROR
    assert entry.status_code == 429
    assert entry.error_type == "rate_limit_exceeded"
    assert entry.model == "gpt-4o-mini"
    assert entry.usage == Usage()
    assert entry.cost_nanousd == 0


async def test_anthropic_error_event_mid_stream(
    client: httpx.AsyncClient, make_key: MakeKey, state: AppState
) -> None:
    key = await make_key(Provider.ANTHROPIC)
    response = await client.post(
        "/v1/messages",
        json={**ANTHROPIC_BODY, "stream": True},
        headers={"x-api-key": key, "x-mock-scenario": "stream_error", **ANTHROPIC_HEADERS},
    )
    assert response.status_code == 200
    assert b"overloaded_error" in response.content

    entry = await _only_entry(state)
    assert entry.outcome is Outcome.UPSTREAM_ERROR
    assert entry.error_type == "overloaded_error"
    assert entry.usage.input_tokens == 10
    assert entry.usage.output_tokens == 1


async def test_upstream_connection_dropped_mid_stream(
    client: httpx.AsyncClient, make_key: MakeKey, state: AppState
) -> None:
    key = await make_key(Provider.ANTHROPIC)
    with pytest.raises(httpx.ReadError):
        await client.post(
            "/v1/messages",
            json={**ANTHROPIC_BODY, "stream": True},
            headers={"x-api-key": key, "x-mock-scenario": "stream_cut", **ANTHROPIC_HEADERS},
        )
    entry = await _only_entry(state)
    assert entry.outcome is Outcome.UPSTREAM_ERROR
    assert entry.error_type == "stream_interrupted:ReadError"
    assert entry.usage.cache_read_tokens == 5000


@pytest.mark.parametrize(
    ("scenario", "status", "error_type"),
    [("connect_error", 502, "ConnectError"), ("timeout", 504, "timeout")],
)
async def test_upstream_unreachable(
    client: httpx.AsyncClient,
    make_key: MakeKey,
    state: AppState,
    scenario: str,
    status: int,
    error_type: str,
) -> None:
    key = await make_key(Provider.ANTHROPIC)
    response = await client.post(
        "/v1/messages",
        json=ANTHROPIC_BODY,
        headers={"x-api-key": key, "x-mock-scenario": scenario, **ANTHROPIC_HEADERS},
    )
    assert response.status_code == status
    assert response.json()["type"] == "error"

    entry = await _only_entry(state)
    assert entry.outcome is Outcome.UPSTREAM_UNREACHABLE
    assert entry.status_code == status
    assert entry.error_type == error_type


async def test_client_disconnect_mid_stream_is_ledgered(
    app: FastAPI, make_key: MakeKey, state: AppState
) -> None:
    key = await make_key(Provider.ANTHROPIC)
    body = json.dumps({**ANTHROPIC_BODY, "stream": True}).encode()
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/v1/messages",
        "raw_path": b"/v1/messages",
        "root_path": "",
        "query_string": b"",
        "headers": [
            (b"x-api-key", key.encode()),
            (b"content-type", b"application/json"),
            (b"x-mock-scenario", b"stream_hang"),
        ],
        "client": ("127.0.0.1", 1234),
        "server": ("tollbooth", 80),
    }
    got_first_chunk = anyio.Event()
    request_sent = False

    async def receive() -> dict[str, Any]:
        nonlocal request_sent
        if not request_sent:
            request_sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        await got_first_chunk.wait()
        return {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        if message["type"] == "http.response.body" and message.get("body"):
            got_first_chunk.set()

    with anyio.fail_after(5):
        await app(scope, receive, send)

    entry = await _only_entry(state)
    assert entry.outcome is Outcome.CLIENT_DISCONNECTED
    assert entry.usage.input_tokens == 10
    assert entry.cost_nanousd is not None


@pytest.mark.parametrize(
    ("path", "headers"),
    [
        ("/v1/chat/completions", {}),
        ("/v1/chat/completions", {"Authorization": "Bearer tb_nope"}),
        ("/v1/messages", {"x-api-key": "tb_nope"}),
    ],
)
async def test_invalid_virtual_key(
    client: httpx.AsyncClient, state: AppState, path: str, headers: dict[str, str]
) -> None:
    response = await client.post(path, json=OPENAI_BODY, headers=headers)
    assert response.status_code == 401
    body = response.json()
    error = body["error"]
    assert error["type"] == "authentication_error"
    if path == "/v1/messages":
        assert body["type"] == "error"
    assert await state.ledger.page(LedgerFilter()) == []


async def test_revoked_key_is_rejected(
    client: httpx.AsyncClient, make_key: MakeKey, admin_headers: dict[str, str]
) -> None:
    key = await make_key(Provider.OPENAI)
    [listed] = (await client.get("/admin/keys", headers=admin_headers)).json()
    await client.post(f"/admin/keys/{listed['id']}/revoke", headers=admin_headers)
    response = await client.post(
        "/v1/chat/completions", json=OPENAI_BODY, headers={"Authorization": f"Bearer {key}"}
    )
    assert response.status_code == 401


async def test_key_for_other_provider_is_rejected(
    client: httpx.AsyncClient, make_key: MakeKey, providers: MockProviders
) -> None:
    key = await make_key(Provider.OPENAI)
    response = await client.post("/v1/messages", json=ANTHROPIC_BODY, headers={"x-api-key": key})
    assert response.status_code == 400
    assert response.json()["error"]["type"] == "invalid_request_error"
    assert providers.received == []


async def test_unpriced_model_is_recorded_without_cost(
    client: httpx.AsyncClient, make_key: MakeKey, state: AppState
) -> None:
    key = await make_key(Provider.ANTHROPIC)
    response = await client.post(
        "/v1/messages",
        json={**ANTHROPIC_BODY, "model": "claude-future-9"},
        headers={"x-api-key": key, **ANTHROPIC_HEADERS},
    )
    assert response.status_code == 200
    entry = await _only_entry(state)
    assert entry.model == "claude-future-9"
    assert entry.usage == ANTHROPIC_USAGE
    assert entry.cost_nanousd is None


async def test_non_json_body_is_forwarded_untouched(
    client: httpx.AsyncClient, make_key: MakeKey, providers: MockProviders, state: AppState
) -> None:
    key = await make_key(Provider.OPENAI)
    response = await client.post(
        "/v1/chat/completions", content=b"not json", headers={"Authorization": f"Bearer {key}"}
    )
    assert response.status_code == 400
    assert providers.received[0].content == b"not json"
    entry = await _only_entry(state)
    assert entry.model == "unknown"
    assert entry.outcome is Outcome.UPSTREAM_ERROR


async def test_no_prompt_or_response_content_is_persisted(
    client: httpx.AsyncClient,
    make_key: MakeKey,
    state: AppState,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("DEBUG")
    openai_key = await make_key(Provider.OPENAI)
    anthropic_key = await make_key(Provider.ANTHROPIC)
    openai_auth = {"Authorization": f"Bearer {openai_key}"}
    anthropic_auth = {"x-api-key": anthropic_key, **ANTHROPIC_HEADERS}
    for stream in (False, True):
        await client.post(
            "/v1/chat/completions", json={**OPENAI_BODY, "stream": stream}, headers=openai_auth
        )
        await client.post(
            "/v1/messages", json={**ANTHROPIC_BODY, "stream": stream}, headers=anthropic_auth
        )
        await client.post(
            "/v1/chat/completions",
            json={**OPENAI_BODY, "stream": stream},
            headers={**openai_auth, "x-mock-scenario": "error_400"},
        )
    await client.post(
        "/v1/messages",
        json={**ANTHROPIC_BODY, "stream": True},
        headers={**anthropic_auth, "x-mock-scenario": "stream_error"},
    )
    assert len(await state.ledger.page(LedgerFilter())) == 7

    await state.engine.dispose()
    stored = _read_all_files(tmp_path)
    assert stored
    for secret in (SECRET_PROMPT, SECRET_OUTPUT, OPENAI_REAL_KEY, ANTHROPIC_REAL_KEY):
        assert secret.encode() not in stored
        assert secret not in caplog.text
    for plaintext_key in (openai_key, anthropic_key):
        assert plaintext_key.encode() not in stored
