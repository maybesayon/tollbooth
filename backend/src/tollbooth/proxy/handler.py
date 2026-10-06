import json
import logging
import math
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

import anyio
import httpx
from fastapi import Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.types import Receive, Scope, Send

from tollbooth.budgets import BudgetUsage
from tollbooth.domain import Outcome, Provider, VirtualKey
from tollbooth.providers import ADAPTERS
from tollbooth.providers.base import ProviderAdapter, StreamMeter
from tollbooth.proxy.headers import client_response_headers, upstream_request_headers
from tollbooth.proxy.metering import UNKNOWN_MODEL, RequestMeter
from tollbooth.proxy.sse import SSEEvent, SSEParser
from tollbooth.routing import plan, retryable
from tollbooth.security import DecryptionError, hash_virtual_key
from tollbooth.state import AppState
from tollbooth.translate import (
    error_body,
    stream_translator,
    translate_request,
    translate_response,
)

logger = logging.getLogger("tollbooth.proxy")

ANTHROPIC_VERSION = "2023-06-01"


class _RejectedError(Exception):
    def __init__(self, status_code: int, error_type: str, message: str) -> None:
        self.status_code = status_code
        self.error_type = error_type
        self.message = message


@dataclass(frozen=True)
class _Target:
    adapter: ProviderAdapter
    credential_id: str
    model: str | None  # None: send the client's request as is


async def proxy(request: Request, adapter: ProviderAdapter, state: AppState) -> Response:
    try:
        key = await _authenticate(request, state)
    except _RejectedError as r:
        return _error(adapter, r.status_code, r.error_type, r.message)

    raw = await request.body()
    body = _json_object(raw)
    model = body.get("model") if body else None
    route = state.routes.get(model) if isinstance(model, str) and body else None
    if route is None:
        if key.provider is not adapter.provider:
            return _error(
                adapter,
                400,
                "invalid_request_error",
                f"this virtual key is for {key.provider.value}, not {adapter.provider.value}",
            )
        targets = [_Target(adapter, key.credential_id, None)]
    else:
        assert body is not None
        credentials = await state.credentials.list_all()
        planned = plan(route, credentials, state.pricing, adapter.provider, body)
        if not planned:
            return _error(
                adapter,
                400,
                "invalid_request_error",
                f"route '{route.name}' has no target that can serve this request "
                "(tools and images need a target on the same API)",
            )
        targets = [_Target(ADAPTERS[c.provider], c.id, m) for c, m in planned]

    meter = RequestMeter(
        state=state,
        adapter=adapter,
        key=key,
        requested_model=model if isinstance(model, str) and model else UNKNOWN_MODEL,
        streamed=body is not None and body.get("stream") is True,
        route=route.name if route else None,
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
        for i, target in enumerate(targets):
            meter.attempts, meter.adapter = i + 1, target.adapter
            meter.requested_model = target.model or meter.requested_model
            last = i == len(targets) - 1
            response = await _attempt(request, raw, body, adapter, target, state, meter, last)
            if response is not None:
                return response
        raise AssertionError("the last attempt always returns a response")
    except Exception:
        logger.exception("proxy failure for key %s", key.id)
        await meter.record(status_code=500, outcome=Outcome.PROXY_ERROR, error_type="proxy_error")
        return _error(adapter, 500, "api_error", "Tollbooth failed to proxy the request")


async def _authenticate(request: Request, state: AppState) -> VirtualKey:
    presented = _presented_key(request)
    key = await state.keys.get_by_hash(hash_virtual_key(presented)) if presented else None
    if key is None or not key.is_active:
        raise _RejectedError(
            401, "authentication_error", "invalid or revoked Tollbooth virtual key"
        )
    return key


def _presented_key(request: Request) -> str | None:
    authorization = request.headers.get("authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() == "bearer" and token.strip():
        return token.strip()
    return request.headers.get("x-api-key") or None


async def _attempt(
    request: Request,
    raw: bytes,
    body: dict[str, Any] | None,
    client: ProviderAdapter,
    target: _Target,
    state: AppState,
    meter: RequestMeter,
    last: bool,
) -> Response | None:
    """Try one target. None means it failed in a way the next target may not, so move on."""
    upstream_adapter = target.adapter
    translate = upstream_adapter is not client
    try:
        api_key = await _provider_key(target.credential_id, state)
    except DecryptionError:
        logger.error("credential %s cannot be decrypted", target.credential_id)
        if not last:
            return None
        await meter.record(
            status_code=500, outcome=Outcome.PROXY_ERROR, error_type="credential_unavailable"
        )
        return _error(client, 500, "api_error", "provider credential is unavailable")

    send = body
    if body is not None and target.model:
        send = (
            translate_request(client.provider, body, target.model)
            if translate
            else {**body, "model": target.model}
        )
    stream_meter: StreamMeter | None = None
    if meter.streamed and send is not None:
        send, stream_meter = upstream_adapter.prepare_stream_body(send)
    content = raw if send is body else json.dumps(send).encode()

    headers = upstream_request_headers(
        request.headers.items(), upstream_adapter.auth_headers(api_key)
    )
    if upstream_adapter.provider is Provider.ANTHROPIC:
        headers.setdefault("anthropic-version", ANTHROPIC_VERSION)
    upstream_request = state.upstream.build_request(
        "POST", _upstream_url(state, upstream_adapter, request), content=content, headers=headers
    )
    try:
        upstream = await state.upstream.send(upstream_request, stream=True)
    except httpx.TransportError as e:
        timeout = isinstance(e, httpx.TimeoutException)
        if not last:
            logger.warning(
                "route %s: %s failed (%s); trying the next target",
                meter.route,
                target.model,
                type(e).__name__,
            )
            return None
        status = 504 if timeout else 502
        await meter.record(
            status_code=status,
            outcome=Outcome.UPSTREAM_UNREACHABLE,
            error_type="timeout" if timeout else type(e).__name__,
        )
        if timeout:
            return _error(client, 504, "timeout_error", "upstream provider timed out")
        return _error(client, 502, "api_error", "upstream provider is unreachable")

    if not upstream.is_success and not last and retryable(upstream.status_code):
        await upstream.aclose()
        logger.warning(
            "route %s: %s returned %s; trying the next target",
            meter.route,
            target.model,
            upstream.status_code,
        )
        return None

    request_id = upstream.headers.get(upstream_adapter.request_id_header)
    response_headers = client_response_headers(upstream.headers.multi_items())
    if target.model:
        response_headers["x-tollbooth-model"] = target.model
    if stream_meter is not None and upstream.is_success:
        translator = (
            stream_translator(client.provider, body or {}, target.model or "")
            if translate
            else None
        )
        relay = _relay(upstream, meter, stream_meter, request_id, translator)
        return _MeteredStreamingResponse(
            relay, status_code=upstream.status_code, headers=response_headers
        )

    try:
        payload = await upstream.aread()
    except httpx.HTTPError as e:
        await meter.record(
            status_code=502,
            outcome=Outcome.UPSTREAM_UNREACHABLE,
            error_type=type(e).__name__,
            upstream_request_id=request_id,
        )
        return _error(client, 502, "api_error", "upstream provider connection failed")
    finally:
        await upstream.aclose()

    parsed = _json_object(payload)
    if upstream.is_success:
        await meter.record(
            status_code=upstream.status_code,
            outcome=Outcome.SUCCESS,
            usage=upstream_adapter.usage_from_response(parsed) if parsed else None,
            model=_str(parsed.get("model")) if parsed else None,
            upstream_request_id=request_id,
        )
        if translate and parsed:
            payload = json.dumps(
                translate_response(client.provider, parsed, target.model or "")
            ).encode()
    else:
        error_type = upstream_adapter.error_type(parsed) or f"http_{upstream.status_code}"
        await meter.record(
            status_code=upstream.status_code,
            outcome=Outcome.UPSTREAM_ERROR,
            error_type=error_type,
            upstream_request_id=request_id,
        )
        if translate:
            message = (
                f"upstream {upstream_adapter.provider.value} returned HTTP {upstream.status_code}"
            )
            payload = json.dumps(error_body(client.provider, error_type, message)).encode()
    if translate:
        response_headers["content-type"] = "application/json"
    return Response(payload, status_code=upstream.status_code, headers=response_headers)


class _Translator(Protocol):
    def feed(self, event: SSEEvent) -> bytes: ...

    def finish(self) -> bytes: ...


async def _relay(
    upstream: httpx.Response,
    meter: RequestMeter,
    stream_meter: StreamMeter,
    request_id: str | None,
    translator: _Translator | None = None,
) -> AsyncGenerator[bytes]:
    parser = SSEParser()
    outcome = Outcome.CLIENT_DISCONNECTED
    error_type: str | None = None
    try:
        async for chunk in upstream.aiter_bytes():
            meter.mark_first_byte()
            forward = bytearray()
            for event in parser.feed(chunk):
                keep = stream_meter.observe(event)
                if translator is not None:
                    forward += translator.feed(event)
                elif keep:
                    forward += event.raw
            if forward:
                yield bytes(forward)
        rest = parser.flush()
        if tail := (translator.finish() if translator is not None else rest):
            yield tail
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


async def _provider_key(credential_id: str, state: AppState) -> str:
    encrypted = await state.credentials.get_encrypted_key(credential_id)
    if encrypted is None:
        raise DecryptionError(f"credential {credential_id} not found")
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
