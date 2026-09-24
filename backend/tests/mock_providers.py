"""In-process fakes of the OpenAI and Anthropic APIs, used as the proxy's upstream transport.

Behaviour is selected per request with the `x-mock-scenario` header (forwarded by the proxy like
any other client header). `x-mock-chunk-size` splits streamed bodies into chunks of that many bytes.
"""

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import anyio
import httpx

OPENAI_REAL_KEY = "sk-openai-real-key"
ANTHROPIC_REAL_KEY = "sk-ant-real-key"
SECRET_OUTPUT = "SECRET-RESPONSE-CONTENT"

OPENAI_USAGE = {
    "prompt_tokens": 1234,
    "completion_tokens": 567,
    "total_tokens": 1801,
    "prompt_tokens_details": {"cached_tokens": 100},
}
# gpt-4o-mini: 1134 uncached * 150 + 100 cached * 75 + 567 * 600 nanodollars
OPENAI_EXPECTED_NANOUSD = 1134 * 150 + 100 * 75 + 567 * 600

ANTHROPIC_START_USAGE = {
    "input_tokens": 10,
    "cache_read_input_tokens": 5000,
    "cache_creation_input_tokens": 3000,
    "cache_creation": {"ephemeral_5m_input_tokens": 2000, "ephemeral_1h_input_tokens": 1000},
    "output_tokens": 1,
}
ANTHROPIC_OUTPUT_TOKENS = 300
# claude-sonnet-4-6: 10*3000 + 5000*300 + 2000*3750 + 1000*6000 + 300*15000 nanodollars
ANTHROPIC_EXPECTED_NANOUSD = 19_530_000


@dataclass(frozen=True)
class ReceivedRequest:
    url: httpx.URL
    headers: httpx.Headers
    content: bytes

    @property
    def json(self) -> Any:
        return json.loads(self.content)


class MockProviders:
    def __init__(self) -> None:
        self.received: list[ReceivedRequest] = []

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    async def handle(self, request: httpx.Request) -> httpx.Response:
        content = await request.aread()
        self.received.append(ReceivedRequest(request.url, request.headers, content))
        scenario = request.headers.get("x-mock-scenario", "ok")
        if scenario == "connect_error":
            raise httpx.ConnectError("connection refused", request=request)
        if scenario == "timeout":
            raise httpx.ReadTimeout("timed out", request=request)
        try:
            body = json.loads(content)
        except json.JSONDecodeError:
            return self._error(request, 400, "invalid_request_error", "body is not valid JSON")
        if request.url.host == "api.openai.com":
            return await self._openai(request, body, scenario)
        if request.url.host == "api.anthropic.com":
            return await self._anthropic(request, body, scenario)
        return httpx.Response(404)

    async def _openai(self, request: httpx.Request, body: Any, scenario: str) -> httpx.Response:
        if request.headers.get("authorization") != f"Bearer {OPENAI_REAL_KEY}":
            return self._error(request, 401, "invalid_request_error", "bad key")
        if scenario.startswith("error_"):
            status = int(scenario.removeprefix("error_"))
            return self._error(request, status, "rate_limit_exceeded", _echo(body))
        model = body.get("model", "gpt-4o-mini") + "-2024-07-18"
        headers = {"x-request-id": "req_openai_1", "openai-processing-ms": "42"}
        if not body.get("stream"):
            return httpx.Response(
                200,
                headers=headers,
                json={
                    "id": "chatcmpl-1",
                    "object": "chat.completion",
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": SECRET_OUTPUT},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": OPENAI_USAGE,
                },
            )
        include_usage = (body.get("stream_options") or {}).get("include_usage") is True
        return self._stream(request, headers, openai_stream(model, include_usage))

    async def _anthropic(self, request: httpx.Request, body: Any, scenario: str) -> httpx.Response:
        if request.headers.get("x-api-key") != ANTHROPIC_REAL_KEY:
            return self._error(request, 401, "authentication_error", "bad key")
        if scenario.startswith("error_"):
            status = int(scenario.removeprefix("error_"))
            return self._error(request, status, "overloaded_error", _echo(body))
        model = body.get("model", "claude-sonnet-4-6")
        headers = {"request-id": "req_anthropic_1"}
        if not body.get("stream"):
            usage = {**ANTHROPIC_START_USAGE, "output_tokens": ANTHROPIC_OUTPUT_TOKENS}
            return httpx.Response(
                200,
                headers=headers,
                json={
                    "id": "msg_1",
                    "type": "message",
                    "role": "assistant",
                    "model": model,
                    "content": [{"type": "text", "text": SECRET_OUTPUT}],
                    "stop_reason": "end_turn",
                    "usage": usage,
                },
            )
        events = anthropic_events(model)
        head = b"".join(events[:2])
        if scenario == "stream_error":
            error = sse("error", {"type": "error", "error": _overloaded()})
            return self._stream(request, headers, head + error)
        if scenario == "stream_cut":
            return self._stream(request, headers, head, then_fail=True)
        if scenario == "stream_hang":
            return self._stream(request, headers, head, then_hang=True)
        return self._stream(request, headers, b"".join(events))

    def _stream(
        self,
        request: httpx.Request,
        headers: dict[str, str],
        body: bytes,
        then_fail: bool = False,
        then_hang: bool = False,
    ) -> httpx.Response:
        size = int(request.headers.get("x-mock-chunk-size", "0")) or len(body)

        async def chunks() -> AsyncIterator[bytes]:
            for i in range(0, len(body), size):
                yield body[i : i + size]
            if then_fail:
                raise httpx.ReadError("connection reset", request=request)
            if then_hang:
                await anyio.sleep_forever()

        return httpx.Response(
            200,
            headers={**headers, "content-type": "text/event-stream; charset=utf-8"},
            content=chunks(),
        )

    def _error(
        self, request: httpx.Request, status: int, kind: str, message: str
    ) -> httpx.Response:
        headers = {"retry-after": "7"} if status == 429 else {}
        if request.url.host == "api.anthropic.com":
            body: dict[str, Any] = {"type": "error", "error": {"type": kind, "message": message}}
        else:
            body = {"error": {"message": message, "type": kind, "param": None, "code": None}}
        return httpx.Response(status, headers=headers, json=body)


def sse(event: str | None, data: Any) -> bytes:
    prefix = f"event: {event}\n" if event else ""
    payload = data if isinstance(data, str) else json.dumps(data)
    return f"{prefix}data: {payload}\n\n".encode()


def openai_stream(model: str, include_usage: bool) -> bytes:
    def chunk(delta: dict[str, Any], finish: str | None = None) -> dict[str, Any]:
        c: dict[str, Any] = {
            "id": "chatcmpl-1",
            "object": "chat.completion.chunk",
            "model": model,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
        }
        return c | {"usage": None} if include_usage else c

    out = sse(None, chunk({"role": "assistant", "content": ""}))
    for word in SECRET_OUTPUT.split("-"):
        out += sse(None, chunk({"content": word}))
    out += sse(None, chunk({}, "stop"))
    if include_usage:
        out += sse(
            None,
            {
                "id": "chatcmpl-1",
                "object": "chat.completion.chunk",
                "model": model,
                "choices": [],
                "usage": OPENAI_USAGE,
            },
        )
    return out + sse(None, "[DONE]")


def anthropic_events(model: str) -> list[bytes]:
    message = {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": [],
        "stop_reason": None,
        "usage": ANTHROPIC_START_USAGE,
    }
    text_block = {"type": "text", "text": ""}
    events = [
        sse("message_start", {"type": "message_start", "message": message}),
        sse(
            "content_block_start",
            {"type": "content_block_start", "index": 0, "content_block": text_block},
        ),
        b'event: ping\ndata: {"type": "ping"}\n\n',
    ]
    for word in SECRET_OUTPUT.split("-"):
        delta = {"type": "text_delta", "text": word}
        events.append(
            sse("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": delta})
        )
    usage = {"output_tokens": ANTHROPIC_OUTPUT_TOKENS}
    return [
        *events,
        sse("content_block_stop", {"type": "content_block_stop", "index": 0}),
        sse(
            "message_delta",
            {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": usage},
        ),
        sse("message_stop", {"type": "message_stop"}),
    ]


def anthropic_stream(model: str) -> bytes:
    return b"".join(anthropic_events(model))


def _overloaded() -> dict[str, str]:
    return {"type": "overloaded_error", "message": "Overloaded"}


def _echo(body: Any) -> str:
    """Providers sometimes echo input in error messages; the ledger must never store this."""
    return f"request rejected: {json.dumps(body)}"
