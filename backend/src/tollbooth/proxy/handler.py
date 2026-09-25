import json
import logging
import math
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any

import anyio
import httpx
from fastapi import Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.types import Receive, Scope, Send

from tollbooth.budgets import BudgetUsage
from tollbooth.domain import Outcome, Provider, VirtualKey
from tollbooth.providers.base import ProviderAdapter, StreamMeter
from tollbooth.proxy.headers import client_response_headers, upstream_request_headers
from tollbooth.proxy.metering import UNKNOWN_MODEL, RequestMeter
from tollbooth.proxy.sse import SSEParser
from tollbooth.security import DecryptionError, hash_virtual_key
from tollbooth.state import AppState

logger = logging.getLogger("tollbooth.proxy")


class _RejectedError(Exception):
    def __init__(self, status_code: int, error_type: str, message: str) -> None:
        self.status_code = status_code
        self.error_type = error_type
        self.message = message


async def proxy(request: Request, adapter: ProviderAdapter, state: AppState) -> Response:
    try:
        key = await _authenticate(request, adapter, state)
    except _RejectedError as r:
        return _error(adapter, r.status_code, r.error_type, r.message)

    raw = await request.body()
    body = _json_object(raw)
    model = body.get("model") if body else None
    streaming = body is not None and body.get("stream") is True
    meter = RequestMeter(
        state=state,
        adapter=adapter,
        key=key,
        requested_model=model if isinstance(model, str) and model else UNKNOWN_MODEL,
        streamed=streaming,
    )
    try:
        blocked = await state.budget_tracker.blocking(key)
    except Exception:
        logger.exception("budget check failed for key %s; allowing the request", key.id)
        blocked = None
    if blocked is not None:
        await meter.record(
            status_code=429, outcome=Outcome.BUDGET_EXCEEDED, error_type="budget_exceeded"
        )
        return _budget_exceeded(adapter, blocked)
    try:
        return await _forward(request, raw, body, adapter, state, meter)
    except Exception:
        logger.exception("proxy failure for key %s", key.id)
        await meter.record(status_code=500, outcome=Outcome.PROXY_ERROR, error_type="proxy_error")
        return _error(adapter, 500, "api_error", "Tollbooth failed to proxy the request")


async def _authenticate(request: Request, adapter: ProviderAdapter, state: AppState) -> VirtualKey:
    presented = _presented_key(request)
    key = await state.keys.get_by_hash(hash_virtual_key(presented)) if presented else None
    if key is None or not key.is_active:
        raise _RejectedError(
            401, "authentication_error", "invalid or revoked Tollbooth virtual key"
        )
    if key.provider is not adapter.provider:
        raise _RejectedError(
            400,
            "invalid_request_error",
            f"this virtual key is for {key.provider.value}, not {adapter.provider.value}",
        )
    return key


def _presented_key(request: Request) -> str | None:
    authorization = request.headers.get("authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() == "bearer" and token.strip():
        return token.strip()
    return request.headers.get("x-api-key") or None


async def _forward(
    request: Request,
    raw: bytes,
    body: dict[str, Any] | None,
    adapter: ProviderAdapter,
    state: AppState,
    meter: RequestMeter,
) -> Response:
    try:
        api_key = await _provider_key(meter.key, state)
    except DecryptionError:
        logger.error("credential %s cannot be decrypted", meter.key.credential_id)
        await meter.record(
            status_code=500, outcome=Outcome.PROXY_ERROR, error_type="credential_unavailable"
        )
        return _error(adapter, 500, "api_error", "provider credential is unavailable")

    content = raw
    stream_meter: StreamMeter | None = None
    if meter.streamed and body is not None:
        prepared, stream_meter = adapter.prepare_stream_body(body)
        if prepared is not body:
            content = json.dumps(prepared).encode()

    upstream_request = state.upstream.build_request(
        "POST",
        _upstream_url(state, adapter, request),
        content=content,
        headers=upstream_request_headers(request.headers.items(), adapter.auth_headers(api_key)),
    )
    try:
        upstream = await state.upstream.send(upstream_request, stream=True)
    except httpx.TimeoutException:
        await meter.record(
            status_code=504, outcome=Outcome.UPSTREAM_UNREACHABLE, error_type="timeout"
        )
        return _error(adapter, 504, "timeout_error", "upstream provider timed out")
    except httpx.TransportError as e:
        await meter.record(
            status_code=502, outcome=Outcome.UPSTREAM_UNREACHABLE, error_type=type(e).__name__
        )
        return _error(adapter, 502, "api_error", "upstream provider is unreachable")

    request_id = upstream.headers.get(adapter.request_id_header)
    headers = client_response_headers(upstream.headers.multi_items())
    if stream_meter is not None and upstream.is_success:
        relay = _relay(upstream, meter, stream_meter, request_id)
        return _MeteredStreamingResponse(relay, status_code=upstream.status_code, headers=headers)

    try:
        payload = await upstream.aread()
    except httpx.HTTPError as e:
        await meter.record(
            status_code=502,
            outcome=Outcome.UPSTREAM_UNREACHABLE,
            error_type=type(e).__name__,
            upstream_request_id=request_id,
        )
        return _error(adapter, 502, "api_error", "upstream provider connection failed")
    finally:
        await upstream.aclose()

    parsed = _json_object(payload)
    if upstream.is_success:
        await meter.record(
            status_code=upstream.status_code,
            outcome=Outcome.SUCCESS,
            usage=adapter.usage_from_response(parsed) if parsed else None,
            model=_str(parsed.get("model")) if parsed else None,
            upstream_request_id=request_id,
        )
    else:
        await meter.record(
            status_code=upstream.status_code,
            outcome=Outcome.UPSTREAM_ERROR,
            error_type=adapter.error_type(parsed) or f"http_{upstream.status_code}",
            upstream_request_id=request_id,
        )
    return Response(payload, status_code=upstream.status_code, headers=headers)


async def _relay(
    upstream: httpx.Response,
    meter: RequestMeter,
    stream_meter: StreamMeter,
    request_id: str | None,
) -> AsyncGenerator[bytes]:
    parser = SSEParser()
    outcome = Outcome.CLIENT_DISCONNECTED
    error_type: str | None = None
    try:
        async for chunk in upstream.aiter_bytes():
            meter.mark_first_byte()
            forward = bytearray()
            for event in parser.feed(chunk):
                if stream_meter.observe(event):
                    forward += event.raw
            if forward:
                yield bytes(forward)
        if rest := parser.flush():
            yield rest
        outcome = Outcome.UPSTREAM_ERROR if stream_meter.error_type else Outcome.SUCCESS
    except httpx.HTTPError as e:
        outcome, error_type = Outcome.UPSTREAM_ERROR, f"stream_interrupted:{type(e).__name__}"
        raise
    finally:
        with anyio.CancelScope(shield=True):
            await upstream.aclose()
            await meter.record(
                status_code=upstream.status_code,
                outcome=outcome,
                usage=stream_meter.usage,
                model=stream_meter.model,
                error_type=error_type or stream_meter.error_type,
                upstream_request_id=request_id,
            )


class _MeteredStreamingResponse(StreamingResponse):
    """Starlette cancels the streaming task on client disconnect without closing the body
    iterator; closing it here guarantees the relay's ledger write runs."""

    def __init__(
        self, content: AsyncGenerator[bytes], status_code: int, headers: dict[str, str]
    ) -> None:
        super().__init__(content, status_code=status_code, headers=headers)
        self._relay = content

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            with anyio.CancelScope(shield=True):
                await self._relay.aclose()


async def _provider_key(key: VirtualKey, state: AppState) -> str:
    encrypted = await state.credentials.get_encrypted_key(key.credential_id)
    if encrypted is None:
        raise DecryptionError(f"credential {key.credential_id} not found")
    return state.secret_box.decrypt(encrypted)


def _upstream_url(state: AppState, adapter: ProviderAdapter, request: Request) -> str:
    base = {
        Provider.OPENAI: state.settings.openai_base_url,
        Provider.ANTHROPIC: state.settings.anthropic_base_url,
    }[adapter.provider]
    query = f"?{request.url.query}" if request.url.query else ""
    return f"{base.rstrip('/')}{adapter.path}{query}"


def _budget_exceeded(adapter: ProviderAdapter, usage: BudgetUsage) -> Response:
    budget = usage.budget
    reset = usage.period_end.isoformat().replace("+00:00", "Z")
    message = (
        f"Tollbooth budget '{budget.name}' is exhausted for this {budget.period.value}. "
        f"Requests resume at {reset}."
    )
    retry_after = max(1, math.ceil((usage.period_end - datetime.now(UTC)).total_seconds()))
    response = _error(adapter, 429, "budget_exceeded", message)
    response.headers["retry-after"] = str(retry_after)
    return response


def _error(adapter: ProviderAdapter, status_code: int, error_type: str, message: str) -> Response:
    return JSONResponse(adapter.error_body(error_type, message), status_code=status_code)


def _json_object(raw: bytes) -> dict[str, Any] | None:
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
