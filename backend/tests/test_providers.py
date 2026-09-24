from mock_providers import sse

from tollbooth.domain import Usage
from tollbooth.providers import ANTHROPIC, OPENAI
from tollbooth.providers.anthropic import AnthropicStreamMeter
from tollbooth.proxy.sse import SSEParser


def _feed(meter: object, stream: bytes) -> list[bool]:
    return [meter.observe(e) for e in SSEParser().feed(stream)]  # type: ignore[attr-defined]


def test_anthropic_message_delta_overrides_cumulative_fields() -> None:
    meter = AnthropicStreamMeter()
    _feed(
        meter,
        sse(
            "message_start",
            {
                "type": "message_start",
                "message": {"model": "m", "usage": {"input_tokens": 5, "output_tokens": 1}},
            },
        )
        + sse(
            "message_delta",
            {"type": "message_delta", "usage": {"input_tokens": 7, "output_tokens": 40}},
        ),
    )
    assert meter.usage == Usage(input_tokens=7, output_tokens=40)
    assert meter.model == "m"


def test_anthropic_cache_creation_without_breakdown_counts_as_5m() -> None:
    usage = ANTHROPIC.usage_from_response({"usage": {"cache_creation_input_tokens": 9}})
    assert usage == Usage(cache_write_tokens=9)


def test_openai_usage_without_cache_details() -> None:
    usage = OPENAI.usage_from_response({"usage": {"prompt_tokens": 3, "completion_tokens": 4}})
    assert usage == Usage(input_tokens=3, output_tokens=4)


def test_openai_meter_ignores_garbage_and_records_errors() -> None:
    _, meter = OPENAI.prepare_stream_body({"stream": True})
    forwarded = _feed(
        meter,
        b"data: not json\n\n"
        + sse(None, [1, 2])
        + sse(None, {"error": {"message": "x", "type": "server_error"}}),
    )
    assert forwarded == [True, True, True]
    assert meter.error_type == "server_error"
    assert meter.usage is None


def test_openai_preserves_other_stream_options() -> None:
    body, _ = OPENAI.prepare_stream_body({"stream_options": {"include_obfuscation": False}})
    assert body["stream_options"] == {"include_obfuscation": False, "include_usage": True}


def test_error_bodies_match_provider_shapes() -> None:
    assert OPENAI.error_body("t", "m") == {
        "error": {"message": "m", "type": "t", "param": None, "code": None}
    }
    assert ANTHROPIC.error_body("t", "m") == {
        "type": "error",
        "error": {"type": "t", "message": "m"},
    }
