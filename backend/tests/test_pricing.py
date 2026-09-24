from decimal import Decimal
from pathlib import Path

import pytest

from tollbooth.domain import Provider
from tollbooth.pricing import ModelPrice, PricingError, load_pricing, parse_pricing

REPO_PRICING = Path(__file__).parent.parent / "pricing.toml"


def test_repo_pricing_file_is_valid() -> None:
    table = load_pricing(REPO_PRICING)
    assert table.lookup(Provider.OPENAI, "gpt-4o-mini") == ModelPrice(
        input=Decimal("0.15"), output=Decimal("0.60"), cache_read=Decimal("0.075")
    )
    assert table.lookup(Provider.ANTHROPIC, "claude-haiku-4-5") == ModelPrice(
        input=Decimal("1.00"),
        output=Decimal("5.00"),
        cache_read=Decimal("0.10"),
        cache_write=Decimal("1.25"),
        cache_write_1h=Decimal("2.00"),
    )


def test_floats_parse_exactly(tmp_path: Path) -> None:
    path = tmp_path / "p.toml"
    path.write_text("[openai.m]\ninput = 0.1\noutput = 0.3\n")
    price = load_pricing(path).lookup(Provider.OPENAI, "m")
    assert price is not None
    assert price.input == Decimal("0.1")
    assert price.output == Decimal("0.3")


@pytest.mark.parametrize(
    ("model", "resolves"),
    [
        ("gpt-4o", True),
        ("gpt-4o-2024-08-06", True),
        ("claude-haiku-4-5-20251001", True),
        ("gpt-4o-audio-preview", False),
        ("gpt-4o-2024-08", False),
        ("unknown-model", False),
    ],
)
def test_lookup_strips_only_date_suffixes(model: str, resolves: bool) -> None:
    table = parse_pricing(
        {
            "openai": {"gpt-4o": {"input": Decimal("2.5"), "output": Decimal(10)}},
            "anthropic": {"claude-haiku-4-5": {"input": Decimal(1), "output": Decimal(5)}},
        }
    )
    provider = Provider.ANTHROPIC if model.startswith("claude") else Provider.OPENAI
    assert (table.lookup(provider, model) is not None) is resolves


def test_lookup_is_scoped_to_provider() -> None:
    table = parse_pricing({"openai": {"m": {"input": Decimal(1), "output": Decimal(1)}}})
    assert table.lookup(Provider.ANTHROPIC, "m") is None


def test_aliases() -> None:
    table = parse_pricing(
        {"openai": {"m": {"input": Decimal(1), "output": Decimal(2), "aliases": ["m-latest"]}}}
    )
    assert table.lookup(Provider.OPENAI, "m-latest") == table.lookup(Provider.OPENAI, "m")


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ({"gemini": {}}, "unknown provider"),
        ({"openai": {"m": {"input": Decimal(1)}}}, "missing required field 'output'"),
        ({"openai": {"m": {"input": Decimal(1), "output": "2"}}}, "must be a number"),
        ({"openai": {"m": {"input": Decimal(-1), "output": Decimal(1)}}}, "negative"),
        ({"openai": {"m": {"input": Decimal("0.0001"), "output": Decimal(1)}}}, "finer than"),
        ({"openai": {"m": {"input": Decimal(1), "output": Decimal(1), "x": 1}}}, "unknown fields"),
        (
            {
                "openai": {
                    "a": {"input": Decimal(1), "output": Decimal(1), "aliases": ["b"]},
                    "b": {"input": Decimal(1), "output": Decimal(1)},
                }
            },
            "duplicate",
        ),
    ],
)
def test_invalid_pricing_is_rejected(raw: dict[str, object], message: str) -> None:
    with pytest.raises(PricingError, match=message):
        parse_pricing(raw)


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(PricingError, match="not found"):
        load_pricing(tmp_path / "nope.toml")
