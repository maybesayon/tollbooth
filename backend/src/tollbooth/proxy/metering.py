import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

from tollbooth.cost import cost_nanousd
from tollbooth.domain import LedgerEntry, Outcome, Usage, VirtualKey
from tollbooth.providers.base import ProviderAdapter
from tollbooth.security import new_id
from tollbooth.state import AppState

logger = logging.getLogger("tollbooth.ledger")

UNKNOWN_MODEL = "unknown"


@dataclass
class RequestMeter:
    """Collects one request's metadata and writes exactly one ledger row. Never sees content."""

    state: AppState
    adapter: ProviderAdapter
    key: VirtualKey
    requested_model: str
    streamed: bool
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    _start: float = field(default_factory=time.perf_counter)
    _first_byte: float | None = None
    _recorded: bool = False

    def mark_first_byte(self) -> None:
        if self._first_byte is None:
            self._first_byte = time.perf_counter()

    async def record(
        self,
        *,
        status_code: int,
        outcome: Outcome,
        usage: Usage | None = None,
        model: str | None = None,
        error_type: str | None = None,
        upstream_request_id: str | None = None,
    ) -> None:
        if self._recorded:
            return
        self._recorded = True
        billed_model = _fit(model or self.requested_model) or UNKNOWN_MODEL
        price = self.state.pricing.lookup(self.adapter.provider, billed_model)
        usage = usage or Usage()
        entry = LedgerEntry(
            id=new_id(),
            created_at=self.started_at,
            team=self.key.team,
            virtual_key_id=self.key.id,
            provider=self.adapter.provider,
            model=billed_model,
            streamed=self.streamed,
            status_code=status_code,
            outcome=outcome,
            latency_ms=_ms(time.perf_counter() - self._start),
            ttfb_ms=_ms(self._first_byte - self._start) if self._first_byte else None,
            usage=usage,
            cost_nanousd=cost_nanousd(usage, price) if price else None,
            error_type=_fit(error_type),
            upstream_request_id=_fit(upstream_request_id),
        )
        try:
            await self.state.ledger.record(entry)
        except Exception:
            logger.exception("failed to write ledger entry %s", entry.id)
            return
        try:
            usages = await self.state.budget_tracker.record(entry)
            await self.state.alert_manager.evaluate(usages)
        except Exception:
            logger.exception("failed to update budgets for ledger entry %s", entry.id)
        logger.info(
            "ledger id=%s team=%s key=%s provider=%s model=%s status=%s outcome=%s "
            "cost_nanousd=%s latency_ms=%s",
            entry.id,
            entry.team,
            entry.virtual_key_id,
            entry.provider,
            entry.model,
            entry.status_code,
            entry.outcome,
            entry.cost_nanousd,
            entry.latency_ms,
        )


def _fit(value: str | None, limit: int = 200) -> str | None:
    """Make client- or provider-supplied text storable everywhere: Postgres rejects NUL and
    enforces column lengths, and a failed ledger write would leave the request unmetered."""
    if value is None:
        return None
    return value.replace("\x00", "")[:limit]


def _ms(seconds: float) -> int:
    return round(seconds * 1000)
