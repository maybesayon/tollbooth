from decimal import Decimal

from tollbooth.domain import Usage
from tollbooth.pricing import ModelPrice

NANOUSD_PER_USD = Decimal(1_000_000_000)
TOKENS_PER_RATE_UNIT = Decimal(1_000_000)


def cost_usd(usage: Usage, price: ModelPrice) -> Decimal:
    cache_read = price.cache_read if price.cache_read is not None else price.input
    cache_write = price.cache_write if price.cache_write is not None else price.input
    cache_write_1h = price.cache_write_1h if price.cache_write_1h is not None else cache_write
    total = (
        usage.input_tokens * price.input
        + usage.output_tokens * price.output
        + usage.cache_read_tokens * cache_read
        + usage.cache_write_tokens * cache_write
        + usage.cache_write_1h_tokens * cache_write_1h
    )
    return total / TOKENS_PER_RATE_UNIT


def cost_nanousd(usage: Usage, price: ModelPrice) -> int:
    """Exact: rates are multiples of $0.001/1M tokens, i.e. whole nanodollars per token."""
    nano = cost_usd(usage, price) * NANOUSD_PER_USD
    if nano != nano.to_integral_value():
        raise ValueError(f"cost {nano} nanoUSD is not integral; pricing validation was bypassed")
    return int(nano)


def nanousd_to_usd(nanousd: int) -> Decimal:
    return Decimal(nanousd) / NANOUSD_PER_USD
