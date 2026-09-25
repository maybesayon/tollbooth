from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class Provider(StrEnum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"


class Outcome(StrEnum):
    SUCCESS = "success"
    UPSTREAM_ERROR = "upstream_error"
    UPSTREAM_UNREACHABLE = "upstream_unreachable"
    CLIENT_DISCONNECTED = "client_disconnected"
    PROXY_ERROR = "proxy_error"
    BUDGET_EXCEEDED = "budget_exceeded"


class GroupBy(StrEnum):
    TEAM = "team"
    MODEL = "model"
    PROVIDER = "provider"
    KEY = "key"


@dataclass(frozen=True)
class Usage:
    """Token counts normalized across providers.

    `input_tokens` excludes cached reads and cache writes, so the four input buckets are disjoint
    and each is billed at its own rate.
    """

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cache_write_1h_tokens: int = 0


@dataclass(frozen=True)
class ProviderCredential:
    id: str
    name: str
    provider: Provider
    created_at: datetime


@dataclass(frozen=True)
class VirtualKey:
    id: str
    name: str
    team: str
    key_prefix: str
    credential_id: str
    provider: Provider
    created_at: datetime
    revoked_at: datetime | None = None

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None


@dataclass(frozen=True)
class LedgerEntry:
    id: str
    created_at: datetime
    team: str
    virtual_key_id: str
    provider: Provider
    model: str
    streamed: bool
    status_code: int
    outcome: Outcome
    latency_ms: int
    usage: Usage
    cost_nanousd: int | None
    ttfb_ms: int | None = None
    error_type: str | None = None
    upstream_request_id: str | None = None


class Interval(StrEnum):
    HOUR = "hour"
    DAY = "day"


@dataclass(frozen=True)
class SpendMetrics:
    requests: int
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    cost_nanousd: int
    unpriced_requests: int
    error_requests: int


@dataclass(frozen=True)
class SpendRow(SpendMetrics):
    group: str


@dataclass(frozen=True)
class SpendPoint(SpendMetrics):
    """Metrics for one time bucket (UTC start), optionally split by a group."""

    bucket: datetime
    group: str | None


class BudgetScope(StrEnum):
    GLOBAL = "global"
    TEAM = "team"
    KEY = "key"


class BudgetPeriod(StrEnum):
    DAY = "day"
    WEEK = "week"
    MONTH = "month"


class Enforcement(StrEnum):
    SOFT = "soft"
    HARD = "hard"


@dataclass(frozen=True)
class Budget:
    """A spend limit per calendar period (UTC) for everything, one team, or one virtual key."""

    id: str
    name: str
    scope: BudgetScope
    scope_value: str | None
    period: BudgetPeriod
    limit_nanousd: int
    enforcement: Enforcement
    thresholds: tuple[int, ...]
    enabled: bool
    created_at: datetime
    updated_at: datetime
    channel_ids: tuple[str, ...] = ()

    def applies_to(self, team: str, virtual_key_id: str) -> bool:
        match self.scope:
            case BudgetScope.GLOBAL:
                return True
            case BudgetScope.TEAM:
                return self.scope_value == team
            case BudgetScope.KEY:
                return self.scope_value == virtual_key_id


class ChannelType(StrEnum):
    WEBHOOK = "webhook"
    SLACK = "slack"


@dataclass(frozen=True)
class Channel:
    """Where alerts are delivered. The URL (and webhook signing secret) are stored encrypted."""

    id: str
    name: str
    type: ChannelType
    url_hint: str
    created_at: datetime


class DeliveryStatus(StrEnum):
    PENDING = "pending"
    DELIVERED = "delivered"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class Delivery:
    id: str
    alert_id: str
    channel_id: str
    channel_name: str
    status: DeliveryStatus
    attempts: int
    last_error: str | None
    updated_at: datetime


@dataclass(frozen=True)
class Alert:
    """A budget crossing one of its thresholds, at most once per budget, period, and threshold."""

    id: str
    budget_id: str
    budget_name: str
    threshold: int
    period_start: datetime
    period_end: datetime
    spend_nanousd: int
    limit_nanousd: int
    created_at: datetime
    deliveries: tuple[Delivery, ...] = ()


class Role(StrEnum):
    """Global roles, each including the previous: viewer reads, editor also manages keys,
    budgets and alert channels, admin also manages provider credentials and users."""

    VIEWER = "viewer"
    EDITOR = "editor"
    ADMIN = "admin"

    def includes(self, other: "Role") -> bool:
        order = [Role.VIEWER, Role.EDITOR, Role.ADMIN]
        return order.index(self) >= order.index(other)


@dataclass(frozen=True)
class User:
    id: str
    email: str
    name: str
    role: Role
    created_at: datetime
    updated_at: datetime
    disabled_at: datetime | None = None
    last_login_at: datetime | None = None

    @property
    def active(self) -> bool:
        return self.disabled_at is None


@dataclass(frozen=True)
class ApiToken:
    id: str
    user_id: str
    name: str
    prefix: str
    created_at: datetime
    last_used_at: datetime | None = None
