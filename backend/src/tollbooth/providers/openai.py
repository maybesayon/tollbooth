import json
from typing import Any

from tollbooth.domain import Provider, Usage
from tollbooth.providers.base import as_int
from tollbooth.proxy.sse import SSEEvent


def _usage(raw: object) -> Usage | None:
    if not isinstance(raw, dict):
        return None
    details = raw.get("prompt_tokens_details")
    cached = as_int(details.get("cached_tokens")) if isinstance(details, dict) else 0
    return Usage(
        input_tokens=max(as_int(raw.get("prompt_tokens")) - cached, 0),
        output_tokens=as_int(raw.get("completion_tokens")),
        cache_read_tokens=cached,
    )


def _error_type(body: Any) -> str | None:
    if not isinstance(body, dict) or not isinstance(body.get("error"), dict):
        return None
    error = body["error"]
    value = error.get("type") or error.get("code")
    return str(value) if value else None


class OpenAIStreamMeter:
    def __init__(self, client_requested_usage: bool) -> None:
        self._client_requested_usage = client_requested_usage
        self.model: str | None = None
        self.usage: Usage | None = None
        self.error_type: str | None = None

    def observe(self, event: SSEEvent) -> bool:
        if event.data is None or event.data == "[DONE]":
            return True
        try:
            chunk = json.loads(event.data)
        except json.JSONDecodeError:
            return True
        if not isinstance(chunk, dict):
            return True
        if isinstance(chunk.get("model"), str):
            self.model = chunk["model"]
        if error := _error_type(chunk):
            self.error_type = error
        usage = _usage(chunk.get("usage"))
        if usage is None:
            return True
        self.usage = usage
        is_usage_only_chunk = not chunk.get("choices")
        return self._client_requested_usage or not is_usage_only_chunk


class OpenAIAdapter:
    provider = Provider.OPENAI
    path = "/v1/chat/completions"
    request_id_header = "x-request-id"

    def auth_headers(self, api_key: str) -> dict[str, str]:
        return {"authorization": f"Bearer {api_key}"}

    def prepare_stream_body(self, body: dict[str, Any]) -> tuple[dict[str, Any], OpenAIStreamMeter]:
        options = body.get("stream_options")
        options = options if isinstance(options, dict) else {}
        requested = options.get("include_usage") is True
        prepared = {**body, "stream_options": {**options, "include_usage": True}}
        return prepared, OpenAIStreamMeter(client_requested_usage=requested)

    def usage_from_response(self, body: dict[str, Any]) -> Usage | None:
        return _usage(body.get("usage"))

    def error_type(self, body: Any) -> str | None:
        return _error_type(body)

    def error_body(self, error_type: str, message: str) -> dict[str, Any]:
        return {"error": {"message": message, "type": error_type, "param": None, "code": None}}
