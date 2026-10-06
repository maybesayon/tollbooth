import logging
import math
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tollbooth.domain import Provider, ProviderCredential
from tollbooth.pricing import PricingTable
from tollbooth.translate import translatable

logger = logging.getLogger("tollbooth.routing")

STRATEGIES = ("fallback", "cheapest")


class RoutingError(ValueError):
    pass


@dataclass(frozen=True)
class RouteTarget:
    credential: str
    model: str


@dataclass(frozen=True)
class Route:
    """A name clients send as `model`, served by the first target that succeeds."""

    name: str
    strategy: str
    targets: tuple[RouteTarget, ...]


def load_routes(path: Path) -> dict[str, Route]:
    """Routes from a TOML file; a missing file means no routes."""
    try:
        with path.open("rb") as f:
            raw = tomllib.load(f)
    except FileNotFoundError:
        return {}
    except tomllib.TOMLDecodeError as e:
        raise RoutingError(f"invalid TOML in {path}: {e}") from e
    return parse_routes(raw)


def parse_routes(raw: dict[str, Any]) -> dict[str, Route]:
    unknown = set(raw) - {"routes"}
    if unknown:
        raise RoutingError(f"unknown top-level keys: {sorted(unknown)}")
    routes: dict[str, Route] = {}
    for name, spec in raw.get("routes", {}).items():
        if not isinstance(spec, dict) or set(spec) - {"strategy", "targets"}:
            raise RoutingError(f"route {name}: expected only 'strategy' and 'targets'")
        strategy = spec.get("strategy", "fallback")
        if strategy not in STRATEGIES:
            raise RoutingError(f"route {name}: strategy must be one of {STRATEGIES}")
        targets = spec.get("targets")
        if not isinstance(targets, list) or not targets:
            raise RoutingError(f"route {name}: needs a non-empty 'targets' list")
        parsed = []
        for t in targets:
            if (
                not isinstance(t, dict)
                or set(t) != {"credential", "model"}
                or not all(isinstance(v, str) and v for v in t.values())
            ):
                raise RoutingError(f"route {name}: each target needs 'credential' and 'model'")
            parsed.append(RouteTarget(t["credential"], t["model"]))
        routes[name] = Route(name, strategy, tuple(parsed))
    return routes


def plan(
    route: Route,
    credentials: list[ProviderCredential],
    pricing: PricingTable,
    client: Provider,
    body: dict[str, Any],
) -> list[tuple[ProviderCredential, str]]:
    """The targets that can serve this request, in the order to try them.

    Targets on the client's own API always qualify; targets on the other API need the request to
    be translatable (text only). Targets naming an unknown credential are skipped.
    """
    by_name = {c.name: c for c in credentials}
    eligible = []
    for target in route.targets:
        credential = by_name.get(target.credential)
        if credential is None:
            logger.warning("route %s: unknown credential %r", route.name, target.credential)
            continue
        if credential.provider is client or translatable(client, body):
            eligible.append((credential, target.model))
    if route.strategy == "cheapest":

        def price(item: tuple[ProviderCredential, str]) -> float:
            p = pricing.lookup(item[0].provider, item[1])
            return float(p.input + p.output) if p else math.inf

        eligible.sort(key=price)
    return eligible


def retryable(status: int) -> bool:
    """Failures another target may not share: credentials, rate limits, overload, outages."""
    return status in (401, 403, 408, 409, 429) or status >= 500
