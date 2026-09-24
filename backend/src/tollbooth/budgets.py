import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from tollbooth.domain import Budget, BudgetScope, Enforcement, LedgerEntry, VirtualKey
from tollbooth.periods import period_window
from tollbooth.repositories.base import BudgetRepository, LedgerFilter, LedgerRepository

Clock = Callable[[], datetime]


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class BudgetUsage:
    budget: Budget
    period_start: datetime
    period_end: datetime
    spend_nanousd: int

    @property
    def exhausted(self) -> bool:
        return self.spend_nanousd >= self.budget.limit_nanousd

    def crossed(self, threshold_percent: int) -> bool:
        return self.spend_nanousd * 100 >= self.budget.limit_nanousd * threshold_percent


@dataclass
class _CachedSpend:
    nanousd: int
    fetched_at: float


class BudgetTracker:
    """Current-period spend per budget, cached briefly and advanced by each recorded request.

    Hard limits are checked before a request is forwarded, but its cost is only known after it
    completes, so concurrent requests can overshoot a limit by what they cost. Cached spend is
    re-read from the ledger at least every `ttl_seconds`, which bounds any drift (other processes'
    requests, or a cost counted twice when a refresh races a write) to that window.
    """

    def __init__(
        self,
        budgets: BudgetRepository,
        ledger: LedgerRepository,
        clock: Clock = utcnow,
        ttl_seconds: float = 5.0,
    ) -> None:
        self._budgets = budgets
        self._ledger = ledger
        self._clock = clock
        self._ttl = ttl_seconds
        self._budget_list: list[Budget] | None = None
        self._budget_list_at = 0.0
        self._spend: dict[tuple[str, datetime], _CachedSpend] = {}

    def invalidate(self) -> None:
        """Forget cached budgets and spend; call after budgets change."""
        self._budget_list = None
        self._spend.clear()

    async def usage(self, budget: Budget) -> BudgetUsage:
        start, end = period_window(budget.period, self._clock())
        cache_key = (budget.id, start)
        cached = self._spend.get(cache_key)
        if cached is None or time.monotonic() - cached.fetched_at > self._ttl:
            spend = await self._ledger.total_cost(_filter_for(budget, start, end))
            cached = _CachedSpend(spend, time.monotonic())
            self._spend[cache_key] = cached
        return BudgetUsage(budget, start, end, cached.nanousd)

    async def applicable(self, team: str, virtual_key_id: str) -> list[Budget]:
        return [b for b in await self._active() if b.applies_to(team, virtual_key_id)]

    async def blocking(self, key: VirtualKey) -> BudgetUsage | None:
        """The exhausted hard budget that resets last, if any applies to this key."""
        blocked: BudgetUsage | None = None
        for budget in await self.applicable(key.team, key.id):
            if budget.enforcement is not Enforcement.HARD:
                continue
            usage = await self.usage(budget)
            if usage.exhausted and (blocked is None or usage.period_end > blocked.period_end):
                blocked = usage
        return blocked

    async def record(self, entry: LedgerEntry) -> list[BudgetUsage]:
        """Count a just-written ledger entry and return the usage of every budget it touches."""
        usages = []
        for budget in await self.applicable(entry.team, entry.virtual_key_id):
            start, _ = period_window(budget.period, self._clock())
            cached = self._spend.get((budget.id, start))
            if cached is not None and entry.cost_nanousd and entry.created_at >= start:
                cached.nanousd += entry.cost_nanousd
            usages.append(await self.usage(budget))
        return usages

    async def _active(self) -> list[Budget]:
        if self._budget_list is None or time.monotonic() - self._budget_list_at > self._ttl:
            self._budget_list = [b for b in await self._budgets.list_all() if b.enabled]
            self._budget_list_at = time.monotonic()
        return self._budget_list


def _filter_for(budget: Budget, start: datetime, end: datetime) -> LedgerFilter:
    match budget.scope:
        case BudgetScope.GLOBAL:
            return LedgerFilter(start=start, end=end)
        case BudgetScope.TEAM:
            return LedgerFilter(start=start, end=end, team=budget.scope_value)
        case BudgetScope.KEY:
            return LedgerFilter(start=start, end=end, virtual_key_id=budget.scope_value)
