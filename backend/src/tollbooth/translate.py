"""Translate text conversations between the OpenAI chat and Anthropic messages formats.

Only plain text is translated. Requests with tools, images, or parameters that have no equivalent
are not translatable, so routing never sends a silently degraded request to the other API.
"""

import json
import time
from typing import Any

from tollbooth.domain import Provider
from tollbooth.proxy.sse import SSEEvent

DEFAULT_MAX_TOKENS = 4096
_OPENAI_KEYS = {
    "model", "messages", "max_tokens", "max_completion_tokens", "temperature", "top_p", "stop",
    "stream", "stream_options", "user", "n",
}  # fmt: skip
_ANTHROPIC_KEYS = {
    "model", "messages", "max_tokens", "system", "temperature", "top_p", "stop_sequences",
    "stream", "metadata",
}  # fmt: skip
_TO_OPENAI_FINISH = {"end_turn": "stop", "stop_sequence": "stop", "max_tokens": "length"}
_TO_ANTHROPIC_STOP = {"stop": "end_turn", "length": "max_tokens"}


def translatable(client: Provider, body: dict[str, Any]) -> bool:
    convert = _openai_to_anthropic if client is Provider.OPENAI else _anthropic_to_openai
    return convert(body, "probe") is not None


def translate_request(client: Provider, body: dict[str, Any], model: str) -> dict[str, Any]:
    convert = _openai_to_anthropic if client is Provider.OPENAI else _anthropic_to_openai
    out = convert(body, model)
    if out is None:
        raise ValueError("request is not translatable")
    return out


def translate_response(client: Provider, body: dict[str, Any], model: str) -> dict[str, Any]:
    if client is Provider.OPENAI:
        return _anthropic_response_to_openai(body, model)
    return _openai_response_to_anthropic(body, model)


def stream_translator(
    client: Provider, body: dict[str, Any], model: str
) -> "AnthropicToOpenAIStream | OpenAIToAnthropicStream":
    if client is Provider.OPENAI:
        options = body.get("stream_options") or {}
        return AnthropicToOpenAIStream(model, include_usage=options.get("include_usage") is True)
    return OpenAIToAnthropicStream(model)


def error_body(client: Provider, error_type: str, message: str) -> dict[str, Any]:
    if client is Provider.OPENAI:
        return {"error": {"message": message, "type": error_type, "param": None, "code": None}}
    return {"type": "error", "error": {"type": error_type, "message": message}}


# --- Requests ------------------------------------------------------------------------------------


def _text(content: Any) -> str | None:
    """A message's content as plain text, or None if it holds anything but text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if not isinstance(part, dict) or part.get("type") != "text":
                return None
            if set(part) - {"type", "text", "cache_control"} or not isinstance(
                part.get("text"), str
            ):
                return None
            parts.append(part["text"])
        return "".join(parts)
    return None


def _openai_to_anthropic(body: dict[str, Any], model: str) -> dict[str, Any] | None:
    if set(body) - _OPENAI_KEYS or body.get("n", 1) != 1:
        return None
    messages, system = body.get("messages"), []
    if not isinstance(messages, list) or not messages:
        return None
    out_messages = []
    for m in messages:
        if not isinstance(m, dict) or set(m) - {"role", "content", "name"}:
            return None
        text = _text(m.get("content"))
        if text is None or m.get("role") not in ("system", "developer", "user", "assistant"):
            return None
        if m["role"] in ("system", "developer"):
            system.append(text)
        else:
            out_messages.append({"role": m["role"], "content": text})
    out: dict[str, Any] = {
        "model": model,
        "messages": out_messages,
        "max_tokens": body.get("max_completion_tokens")
        or body.get("max_tokens")
        or DEFAULT_MAX_TOKENS,
    }
    if system:
        out["system"] = "\n\n".join(system)
    if isinstance(body.get("temperature"), int | float):
        out["temperature"] = min(float(body["temperature"]), 1.0)
    if "top_p" in body:
        out["top_p"] = body["top_p"]
    if stop := body.get("stop"):
        out["stop_sequences"] = [stop] if isinstance(stop, str) else list(stop)
    if body.get("stream") is True:
        out["stream"] = True
    return out


def _anthropic_to_openai(body: dict[str, Any], model: str) -> dict[str, Any] | None:
    if set(body) - _ANTHROPIC_KEYS:
        return None
    out_messages = []
    if "system" in body:
        system = _text(body["system"])
        if system is None:
            return None
        out_messages.append({"role": "system", "content": system})
    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        return None
    for m in messages:
        if not isinstance(m, dict) or set(m) - {"role", "content"}:
            return None
        text = _text(m.get("content"))
        if text is None or m.get("role") not in ("user", "assistant"):
            return None
        out_messages.append({"role": m["role"], "content": text})
    out: dict[str, Any] = {
        "model": model,
        "messages": out_messages,
        "max_completion_tokens": body.get("max_tokens") or DEFAULT_MAX_TOKENS,
    }
    for key in ("temperature", "top_p"):
        if key in body:
            out[key] = body[key]
    if stops := body.get("stop_sequences"):
        out["stop"] = stops
    if body.get("stream") is True:
        out["stream"] = True
    return out


# --- Responses -----------------------------------------------------------------------------------


def _openai_usage(usage: dict[str, Any]) -> dict[str, Any]:
    cached = usage.get("cache_read_input_tokens") or 0
    prompt = (
        (usage.get("input_tokens") or 0) + cached + (usage.get("cache_creation_input_tokens") or 0)
    )
    completion = usage.get("output_tokens") or 0
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": prompt + completion,
        "prompt_tokens_details": {"cached_tokens": cached},
    }


def _anthropic_usage(usage: dict[str, Any]) -> dict[str, Any]:
    cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
    return {
        "input_tokens": max((usage.get("prompt_tokens") or 0) - cached, 0),
        "output_tokens": usage.get("completion_tokens") or 0,
        "cache_read_input_tokens": cached,
        "cache_creation_input_tokens": 0,
    }


def _anthropic_response_to_openai(body: dict[str, Any], model: str) -> dict[str, Any]:
    text = "".join(b.get("text", "") for b in body.get("content") or [] if b.get("type") == "text")
    return {
        "id": f"chatcmpl-{body.get('id', '')}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": body.get("model") or model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": _TO_OPENAI_FINISH.get(body.get("stop_reason") or "", "stop"),
            }
        ],
        "usage": _openai_usage(body.get("usage") or {}),
    }


def _openai_response_to_anthropic(body: dict[str, Any], model: str) -> dict[str, Any]:
    choice = (body.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    return {
        "id": f"msg_{body.get('id', '')}",
        "type": "message",
        "role": "assistant",
        "model": body.get("model") or model,
        "content": [{"type": "text", "text": message.get("content") or ""}],
        "stop_reason": _TO_ANTHROPIC_STOP.get(choice.get("finish_reason") or "", "end_turn"),
        "stop_sequence": None,
        "usage": _anthropic_usage(body.get("usage") or {}),
    }


# --- Streams -------------------------------------------------------------------------------------


def _payload(event: SSEEvent) -> Any:
    if event.data is None or event.data == "[DONE]":
        return event.data
    try:
        return json.loads(event.data)
    except json.JSONDecodeError:
        return None


class AnthropicToOpenAIStream:
    """Anthropic message events in, OpenAI chat.completion.chunk events out."""

    def __init__(self, model: str, include_usage: bool) -> None:
        self.model, self.include_usage = model, include_usage
        self.id, self.created = "chatcmpl-", int(time.time())
        self.usage: dict[str, Any] = {}

    def feed(self, event: SSEEvent) -> bytes:
        data = _payload(event)
        if not isinstance(data, dict):
            return b""
        kind = data.get("type")
        if kind == "message_start":
            message = data.get("message") or {}
            self.id = f"chatcmpl-{message.get('id', '')}"
            self.model = message.get("model") or self.model
            self.usage.update(message.get("usage") or {})
            return self._chunk({"role": "assistant", "content": ""})
        if kind == "content_block_delta" and (data.get("delta") or {}).get("type") == "text_delta":
            return self._chunk({"content": data["delta"].get("text", "")})
        if kind == "message_delta":
            self.usage.update(data.get("usage") or {})
            stop = (data.get("delta") or {}).get("stop_reason") or ""
            return self._chunk({}, _TO_OPENAI_FINISH.get(stop, "stop"))
        if kind == "message_stop":
            out = b""
            if self.include_usage:
                out += self._sse(
                    {**self._base(), "choices": [], "usage": _openai_usage(self.usage)}
                )
            return out + b"data: [DONE]\n\n"
        if kind == "error":
            error = data.get("error") or {}
            return self._sse(
                {"error": {"type": error.get("type"), "message": error.get("message")}}
            )
        return b""

    def finish(self) -> bytes:
        return b""

    def _base(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "object": "chat.completion.chunk",
            "created": self.created,
            "model": self.model,
        }

    def _chunk(self, delta: dict[str, Any], finish: str | None = None) -> bytes:
        choice = {"index": 0, "delta": delta, "finish_reason": finish}
        return self._sse({**self._base(), "choices": [choice]})

    @staticmethod
    def _sse(data: dict[str, Any]) -> bytes:
        return f"data: {json.dumps(data)}\n\n".encode()


class OpenAIToAnthropicStream:
    """OpenAI chat.completion.chunk events in, Anthropic message events out."""

    def __init__(self, model: str) -> None:
        self.model = model
        self.started = self.closed = False
        self.stop_reason = "end_turn"
        self.usage: dict[str, Any] = {}

    def feed(self, event: SSEEvent) -> bytes:
        data = _payload(event)
        if data == "[DONE]":
            return self._close()
        if not isinstance(data, dict):
            return b""
        if isinstance(data.get("error"), dict):
            error = data["error"]
            return self._sse(
                "error",
                {
                    "type": "error",
                    "error": {"type": error.get("type"), "message": error.get("message")},
                },
            )
        out = b""
        if not self.started:
            self.started = True
            self.model = data.get("model") or self.model
            message = {
                "id": f"msg_{data.get('id', '')}", "type": "message", "role": "assistant",
                "model": self.model, "content": [], "stop_reason": None, "stop_sequence": None,
                "usage": {"input_tokens": 0, "output_tokens": 0},
            }  # fmt: skip
            out += self._sse("message_start", {"type": "message_start", "message": message})
            out += self._sse(
                "content_block_start",
                {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {"type": "text", "text": ""},
                },
            )
        if isinstance(data.get("usage"), dict):
            self.usage = data["usage"]
        for choice in data.get("choices") or []:
            if text := (choice.get("delta") or {}).get("content"):
                delta = {"type": "text_delta", "text": text}
                out += self._sse(
                    "content_block_delta",
                    {"type": "content_block_delta", "index": 0, "delta": delta},
                )
            if finish := choice.get("finish_reason"):
                self.stop_reason = _TO_ANTHROPIC_STOP.get(finish, "end_turn")
        return out

    def finish(self) -> bytes:
        return self._close()

    def _close(self) -> bytes:
        if not self.started or self.closed:
            return b""
        self.closed = True
        usage = _anthropic_usage(self.usage)
        return (
            self._sse("content_block_stop", {"type": "content_block_stop", "index": 0})
            + self._sse(
                "message_delta",
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": self.stop_reason, "stop_sequence": None},
                    "usage": usage,
                },
            )
            + self._sse("message_stop", {"type": "message_stop"})
        )

    @staticmethod
    def _sse(event: str, data: dict[str, Any]) -> bytes:
        return f"event: {event}\ndata: {json.dumps(data)}\n\n".encode()
