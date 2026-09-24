import json
from typing import Any

from tollbooth.domain import Provider, Usage
from tollbooth.providers.base import as_int
from tollbooth.proxy.sse import SSEEvent

_USAGE_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
    "cache_creation",
)


def _usage(raw: dict[str, Any]) -> Usage:
    breakdown = raw.get("cache_creation")
    if isinstance(breakdown, dict):
        write_5m = as_int(breakdown.get("ephemeral_5m_input_tokens"))
        write_1h = as_int(breakdown.get("ephemeral_1h_input_tokens"))
    else:
        write_5m, write_1h = as_int(raw.get("cache_creation_input_tokens")), 0
    return Usage(
        input_tokens=as_int(raw.get("input_tokens")),
        output_tokens=as_int(raw.get("output_tokens")),
        cache_read_tokens=as_int(raw.get("cache_read_input_tokens")),
        cache_write_tokens=write_5m,
        cache_write_1h_tokens=write_1h,
    )


def _error_type(body: Any) -> str | None:
    if not isinstance(body, dict) or not isinstance(body.get("error"), dict):
        return None
    value = body["error"].get("type")
    return str(value) if value else None


class AnthropicStreamMeter:
    """Usage arrives in `message_start` and is updated by `message_delta`, whose counts are
    cumulative, so later values replace earlier ones field by field."""

    def __init__(self) -> None:
        self.model: str | None = None
        self.error_type: str | None = None
        self._raw_usage: dict[str, Any] = {}

    @property
    def usage(self) -> Usage | None:
        return _usage(self._raw_usage) if self._raw_usage else None

    def observe(self, event: SSEEvent) -> bool:
        if event.data is None:
            return True
        try:
            payload = json.loads(event.data)
        except json.JSONDecodeError:
            return True
        if not isinstance(payload, dict):
            return True
        kind = payload.get("type")
        if kind == "message_start" and isinstance(payload.get("message"), dict):
            message = payload["message"]
            if isinstance(message.get("model"), str):
                self.model = message["model"]
            self._merge(message.get("usage"))
        elif kind == "message_delta":
            self._merge(payload.get("usage"))
        elif kind == "error":
            self.error_type = _error_type(payload) or "error"
        return True

    def _merge(self, usage: object) -> None:
        if isinstance(usage, dict):
            self._raw_usage.update(
                {k: v for k, v in usage.items() if k in _USAGE_FIELDS and v is not None}
            )


class AnthropicAdapter:
    provider = Provider.ANTHROPIC
    path = "/v1/messages"
    request_id_header = "request-id"

    def auth_headers(self, api_key: str) -> dict[str, str]:
        return {"x-api-key": api_key}

    def prepare_stream_body(
        self, body: dict[str, Any]
    ) -> tuple[dict[str, Any], AnthropicStreamMeter]:
        return body, AnthropicStreamMeter()

    def usage_from_response(self, body: dict[str, Any]) -> Usage | None:
        usage = body.get("usage")
        return _usage(usage) if isinstance(usage, dict) else None

    def error_type(self, body: Any) -> str | None:
        return _error_type(body)

    def error_body(self, error_type: str, message: str) -> dict[str, Any]:
        return {"type": "error", "error": {"type": error_type, "message": message}}
