from datetime import datetime
from decimal import Decimal
from typing import Annotated, Self

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from tollbooth.api.fields import Name, Text
from tollbooth.api.ledger_schemas import USD
from tollbooth.budgets import BudgetUsage
from tollbooth.cost import NANOUSD_PER_USD, nanousd_to_usd
from tollbooth.domain import Budget, BudgetPeriod, BudgetScope, Enforcement

DEFAULT_THRESHOLDS = (50, 80, 100)


def _limit(value: Decimal) -> Decimal:
    if value <= 0:
        raise ValueError("must be greater than zero")
    if (value * NANOUSD_PER_USD) % 1 != 0:
        raise ValueError("must not be finer than one nanodollar")
    return value


def _thresholds(value: list[int]) -> list[int]:
    if any(t < 1 or t > 1000 for t in value):
        raise ValueError("each threshold must be between 1 and 1000 percent")
    return sorted(set(value))


LimitUSD = Annotated[Decimal, AfterValidator(_limit)]
Thresholds = Annotated[list[int], Field(max_length=10), AfterValidator(_thresholds)]
ChannelIds = Annotated[
    list[Text],
    Field(max_length=20, description="Alert channels notified when a threshold is crossed."),
    AfterValidator(lambda ids: sorted(set(ids))),
]


class Scope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: BudgetScope
    value: Text | None = Field(None, description="Team name or virtual key id; omit for global.")

    @model_validator(mode="after")
    def _value_matches_type(self) -> Self:
        if self.type is BudgetScope.GLOBAL and self.value is not None:
            raise ValueError("a global budget takes no scope value")
        if self.type is not BudgetScope.GLOBAL and not (self.value and self.value.strip()):
            raise ValueError(f"a {self.type.value} budget needs a scope value")
        return self


class BudgetCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name
    scope: Scope
    period: BudgetPeriod
    limit_usd: LimitUSD
    enforcement: Enforcement = Enforcement.SOFT
    thresholds: Thresholds = Field(default_factory=lambda: list(DEFAULT_THRESHOLDS))
    enabled: bool = True
    channel_ids: ChannelIds = Field(default_factory=list)


class BudgetUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name | None = None
    scope: Scope | None = None
    period: BudgetPeriod | None = None
    limit_usd: LimitUSD | None = None
    enforcement: Enforcement | None = None
    thresholds: Thresholds | None = None
    enabled: bool | None = None
    channel_ids: ChannelIds | None = None


class UsageOut(BaseModel):
    period_start: datetime
    period_end: datetime
    spend_usd: USD
    percent_used: float
    exhausted: bool


class BudgetOut(BaseModel):
    id: str
    name: str
    scope: Scope
    period: BudgetPeriod
    limit_usd: USD
    enforcement: Enforcement
    thresholds: list[int]
    enabled: bool
    channel_ids: list[str]
    created_at: datetime
    updated_at: datetime
    usage: UsageOut

    @classmethod
    def of(cls, usage: BudgetUsage) -> "BudgetOut":
        b = usage.budget
        return cls(
            id=b.id,
            name=b.name,
            scope=Scope(type=b.scope, value=b.scope_value),
            period=b.period,
            limit_usd=nanousd_to_usd(b.limit_nanousd),
            enforcement=b.enforcement,
            thresholds=list(b.thresholds),
            enabled=b.enabled,
            channel_ids=list(b.channel_ids),
            created_at=b.created_at,
            updated_at=b.updated_at,
            usage=UsageOut(
                period_start=usage.period_start,
                period_end=usage.period_end,
                spend_usd=nanousd_to_usd(usage.spend_nanousd),
                percent_used=round(usage.spend_nanousd * 100 / b.limit_nanousd, 1),
                exhausted=usage.exhausted,
            ),
        )


def to_nanousd(value: Decimal) -> int:
    return int(value * NANOUSD_PER_USD)


def scope_value(scope: Scope) -> str | None:
    return scope.value.strip() if scope.value is not None else None


def apply_update(budget: Budget, update: BudgetUpdate, now: datetime) -> Budget:
    return Budget(
        id=budget.id,
        name=update.name or budget.name,
        scope=update.scope.type if update.scope else budget.scope,
        scope_value=scope_value(update.scope) if update.scope else budget.scope_value,
        period=update.period or budget.period,
        limit_nanousd=to_nanousd(update.limit_usd) if update.limit_usd else budget.limit_nanousd,
        enforcement=update.enforcement or budget.enforcement,
        thresholds=tuple(update.thresholds) if update.thresholds is not None else budget.thresholds,
        enabled=update.enabled if update.enabled is not None else budget.enabled,
        created_at=budget.created_at,
        updated_at=now,
        channel_ids=(
            tuple(update.channel_ids) if update.channel_ids is not None else budget.channel_ids
        ),
    )
