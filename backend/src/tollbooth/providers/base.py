from typing import Any, Protocol

from tollbooth.domain import Provider, Usage
from tollbooth.proxy.sse import SSEEvent


class StreamMeter(Protocol):
    """Watches a provider's SSE stream and accumulates usage, model and errors."""

    model: str | None
    usage: Usage | None
    error_type: str | None

    def observe(self, event: SSEEvent) -> bool:
        """Record what the event says; return False if it must not be forwarded to the client."""
        ...


class ProviderAdapter(Protocol):
    provider: Provider
    path: str
    request_id_header: str

    def auth_headers(self, api_key: str) -> dict[str, str]: ...

    def prepare_stream_body(self, body: dict[str, Any]) -> tuple[dict[str, Any], StreamMeter]:
        """Adjust a streaming request body if needed and return a meter for its response."""
        ...

    def usage_from_response(self, body: dict[str, Any]) -> Usage | None: ...

    def error_type(self, body: Any) -> str | None: ...

    def error_body(self, error_type: str, message: str) -> dict[str, Any]:
        """A proxy-generated error in this provider's wire format, so SDKs can parse it."""
        ...


def as_int(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0
