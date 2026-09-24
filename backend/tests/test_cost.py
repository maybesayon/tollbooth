from decimal import Decimal

from tollbooth.cost import cost_nanousd, cost_usd, nanousd_to_usd
from tollbooth.domain import Usage
from tollbooth.pricing import ModelPrice

GPT_4O_MINI = ModelPrice(input=Decimal("0.15"), output=Decimal("0.60"), cache_read=Decimal("0.075"))
SONNET_4_6 = ModelPrice(
    input=Decimal("3.00"),
    output=Decimal("15.00"),
    cache_read=Decimal("0.30"),
    cache_write=Decimal("3.75"),
    cache_write_1h=Decimal("6.00"),
)


def test_openai_style_cost_is_exact() -> None:
    usage = Usage(input_tokens=1234, output_tokens=567, cache_read_tokens=100)
    # 1234*150 + 567*600 + 100*75 nanodollars
    assert cost_nanousd(usage, GPT_4O_MINI) == 532_800
    assert cost_usd(usage, GPT_4O_MINI) == Decimal("0.0005328")


def test_anthropic_style_cost_with_both_cache_ttls() -> None:
    usage = Usage(
        input_tokens=10,
        output_tokens=300,
        cache_read_tokens=5000,
        cache_write_tokens=2000,
        cache_write_1h_tokens=1000,
    )
    # 10*3000 + 300*15000 + 5000*300 + 2000*3750 + 1000*6000 nanodollars
    assert cost_nanousd(usage, SONNET_4_6) == 19_530_000
    assert nanousd_to_usd(19_530_000) == Decimal("0.01953")


def test_cache_rates_fall_back_to_input() -> None:
    price = ModelPrice(input=Decimal("2.00"), output=Decimal("8.00"))
    usage = Usage(cache_read_tokens=1, cache_write_tokens=1, cache_write_1h_tokens=1)
    assert cost_nanousd(usage, price) == 3 * 2000


def test_cache_write_1h_falls_back_to_cache_write() -> None:
    price = ModelPrice(input=Decimal(1), output=Decimal(1), cache_write=Decimal("1.25"))
    assert cost_nanousd(Usage(cache_write_1h_tokens=4), price) == 4 * 1250


def test_smallest_allowed_rate_is_one_nanodollar_per_token() -> None:
    price = ModelPrice(input=Decimal("0.001"), output=Decimal("0.001"))
    assert cost_nanousd(Usage(input_tokens=1, output_tokens=1), price) == 2


def test_zero_usage_costs_nothing() -> None:
    assert cost_nanousd(Usage(), SONNET_4_6) == 0
