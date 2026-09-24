import re
import tomllib
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from tollbooth.domain import Provider

PRICE_QUANTUM = Decimal("0.001")
_DATE_SUFFIX = re.compile(r"-(\d{4}-\d{2}-\d{2}|\d{8})$")
_RATE_FIELDS = ("input", "output", "cache_read", "cache_write", "cache_write_1h")


class PricingError(ValueError):
    pass


@dataclass(frozen=True)
class ModelPrice:
    """USD per 1M tokens. Cache rates fall back to the input rate when not configured."""

    input: Decimal
    output: Decimal
    cache_read: Decimal | None = None
    cache_write: Decimal | None = None
    cache_write_1h: Decimal | None = None


class PricingTable:
    def __init__(self, prices: dict[tuple[Provider, str], ModelPrice]) -> None:
        self._prices = prices

    def __len__(self) -> int:
        return len(self._prices)

    def lookup(self, provider: Provider, model: str) -> ModelPrice | None:
        """Resolve a model name, falling back to the name without a dated snapshot suffix."""
        price = self._prices.get((provider, model))
        if price is None:
            undated = _DATE_SUFFIX.sub("", model)
            if undated != model:
                price = self._prices.get((provider, undated))
        return price


def load_pricing(path: Path) -> PricingTable:
    try:
        with path.open("rb") as f:
            raw = tomllib.load(f, parse_float=Decimal)
    except FileNotFoundError as e:
        raise PricingError(f"pricing file not found: {path}") from e
    except tomllib.TOMLDecodeError as e:
        raise PricingError(f"invalid TOML in {path}: {e}") from e
    return parse_pricing(raw)


def parse_pricing(raw: dict[str, object]) -> PricingTable:
    prices: dict[tuple[Provider, str], ModelPrice] = {}
    for provider_name, models in raw.items():
        try:
            provider = Provider(provider_name)
        except ValueError as e:
            raise PricingError(f"unknown provider section: [{provider_name}]") from e
        if not isinstance(models, dict):
            raise PricingError(f"[{provider_name}] must be a table of models")
        for model, entry in models.items():
            if not isinstance(entry, dict):
                raise PricingError(f"{provider_name}.{model} must be a table")
            price = _parse_entry(f"{provider_name}.{model}", entry)
            aliases = entry.get("aliases", [])
            if not isinstance(aliases, list) or not all(isinstance(a, str) for a in aliases):
                raise PricingError(f"{provider_name}.{model}.aliases must be a list of strings")
            for name in (model, *aliases):
                if (provider, name) in prices:
                    raise PricingError(f"duplicate model name for {provider_name}: {name}")
                prices[(provider, name)] = price
    return PricingTable(prices)


def _parse_entry(where: str, entry: dict[str, object]) -> ModelPrice:
    unknown = set(entry) - {*_RATE_FIELDS, "aliases"}
    if unknown:
        raise PricingError(f"{where}: unknown fields {sorted(unknown)}")

    def optional(field: str) -> Decimal | None:
        value = entry.get(field)
        return None if value is None else _parse_rate(f"{where}.{field}", value)

    def required(field: str) -> Decimal:
        rate = optional(field)
        if rate is None:
            raise PricingError(f"{where}: missing required field '{field}'")
        return rate

    return ModelPrice(
        input=required("input"),
        output=required("output"),
        cache_read=optional("cache_read"),
        cache_write=optional("cache_write"),
        cache_write_1h=optional("cache_write_1h"),
    )


def _parse_rate(where: str, value: object) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, int | Decimal):
        raise PricingError(f"{where}: must be a number")
    rate = Decimal(value)
    if rate < 0:
        raise PricingError(f"{where}: must not be negative")
    if rate % PRICE_QUANTUM != 0:
        raise PricingError(f"{where}: {rate} is finer than ${PRICE_QUANTUM} per 1M tokens")
    return rate
