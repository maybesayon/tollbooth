import pytest

from tollbooth.domain import Provider
from tollbooth.translate import translatable, translate_request

USER = {"role": "user", "content": "hi"}


@pytest.mark.parametrize(
    "body",
    [
        {"messages": [USER], "tools": []},
        {"messages": [USER], "n": 2},
        {"messages": [USER], "response_format": {"type": "json_object"}},
        {"messages": [{"role": "user", "content": [{"type": "image_url", "image_url": {}}]}]},
        {"messages": [{"role": "tool", "content": "x", "tool_call_id": "1"}]},
        {"messages": []},
    ],
)
def test_openai_requests_that_cannot_be_translated(body: dict) -> None:
    assert not translatable(Provider.OPENAI, {"model": "m", **body})


@pytest.mark.parametrize(
    "body",
    [
        {"messages": [USER], "tools": []},
        {"messages": [USER], "thinking": {"type": "adaptive"}},
        {"messages": [USER], "top_k": 5},
        {"messages": [{"role": "user", "content": [{"type": "image", "source": {}}]}]},
        {"messages": [USER], "system": [{"type": "text", "text": "a"}, {"type": "image"}]},
    ],
)
def test_anthropic_requests_that_cannot_be_translated(body: dict) -> None:
    assert not translatable(Provider.ANTHROPIC, {"model": "m", "max_tokens": 5, **body})


def test_openai_to_anthropic_parameters() -> None:
    out = translate_request(
        Provider.OPENAI,
        {
            "model": "route",
            "messages": [
                {"role": "developer", "content": "rule one"},
                {"role": "system", "content": [{"type": "text", "text": "rule two"}]},
                USER,
                {"role": "assistant", "content": "hello"},
            ],
            "max_tokens": 50,
            "temperature": 1.7,
            "top_p": 0.9,
            "stop": "END",
            "stream": True,
            "user": "u1",
        },
        "claude-haiku-4-5",
    )
    assert out == {
        "model": "claude-haiku-4-5",
        "system": "rule one\n\nrule two",
        "messages": [USER, {"role": "assistant", "content": "hello"}],
        "max_tokens": 50,
        "temperature": 1.0,
        "top_p": 0.9,
        "stop_sequences": ["END"],
        "stream": True,
    }


def test_anthropic_to_openai_parameters() -> None:
    out = translate_request(
        Provider.ANTHROPIC,
        {
            "model": "route",
            "max_tokens": 64,
            "system": [
                {"type": "text", "text": "be brief", "cache_control": {"type": "ephemeral"}}
            ],
            "messages": [USER],
            "stop_sequences": ["END", "STOP"],
            "metadata": {"user_id": "u1"},
        },
        "gpt-5.4",
    )
    assert out == {
        "model": "gpt-5.4",
        "messages": [{"role": "system", "content": "be brief"}, USER],
        "max_completion_tokens": 64,
        "stop": ["END", "STOP"],
    }


def test_untranslatable_requests_raise() -> None:
    with pytest.raises(ValueError, match="not translatable"):
        translate_request(Provider.OPENAI, {"model": "m", "messages": [USER], "tools": []}, "x")
