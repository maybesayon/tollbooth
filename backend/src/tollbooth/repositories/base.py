from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from tollbooth.domain import (
    Alert,
    Budget,
    Channel,
    Delivery,
    GroupBy,
    Interval,
    LedgerEntry,
    Outcome,
    Provider,
    ProviderCredential,
    SpendPoint,
    SpendRow,
    VirtualKey,
)


class DuplicateNameError(Exception):
    pass


@dataclass(frozen=True)
class LedgerFilter:
    start: datetime | None = None
    end: datetime | None = None
    team: str | None = None
    provider: Provider | None = None
    model: str | None = None
    virtual_key_id: str | None = None
    outcome: Outcome | None = None


@dataclass(frozen=True)
class LedgerCursor:
    """Position after the last entry of a page; entries are ordered newest first."""

    created_at: datetime
    id: str


class CredentialRepository(Protocol):
    async def create(self, name: str, provider: Provider, encrypted_key: str) -> ProviderCredential:
        """Raises DuplicateNameError if the name is taken."""
        ...

    async def get(self, credential_id: str) -> ProviderCredential | None: ...

    async def get_encrypted_key(self, credential_id: str) -> str | None: ...

    async def list_all(self) -> list[ProviderCredential]: ...


class KeyRepository(Protocol):
    async def create(
        self, name: str, team: str, key_hash: str, key_prefix: str, credential_id: str
    ) -> VirtualKey: ...

    async def get(self, key_id: str) -> VirtualKey | None: ...

    async def get_by_hash(self, key_hash: str) -> VirtualKey | None: ...

    async def list_all(
        self, team: str | None = None, include_revoked: bool = False
    ) -> list[VirtualKey]: ...

    async def revoke(self, key_id: str) -> VirtualKey | None:
        """Idempotent: revoking an already revoked key returns it unchanged."""
        ...


class BudgetRepository(Protocol):
    async def create(self, budget: Budget) -> None: ...

    async def get(self, budget_id: str) -> Budget | None: ...

    async def list_all(self) -> list[Budget]: ...

    async def update(self, budget: Budget) -> bool:
        """Replace a budget's fields; False if it does not exist."""
        ...

    async def delete(self, budget_id: str) -> bool: ...


class ChannelRepository(Protocol):
    async def create(
        self, channel: Channel, encrypted_url: str, encrypted_secret: str | None
    ) -> None:
        """Raises DuplicateNameError if the name is taken."""
        ...

    async def get(self, channel_id: str) -> Channel | None: ...

    async def list_all(self) -> list[Channel]: ...

    async def get_secrets(self, channel_id: str) -> tuple[str, str | None] | None:
        """(encrypted_url, encrypted_secret) for delivery."""
        ...

    async def delete(self, channel_id: str) -> bool: ...


class AlertRepository(Protocol):
    async def create_if_absent(self, alert: Alert) -> bool:
        """False when this budget already alerted for this period and threshold."""
        ...

    async def recent(self, limit: int = 50, budget_id: str | None = None) -> list[Alert]:
        """Newest first, with deliveries."""
        ...

    async def save_delivery(self, delivery: Delivery) -> None:
        """Insert or replace by id."""
        ...


class LedgerRepository(Protocol):
    async def record(self, entry: LedgerEntry) -> None: ...

    async def page(
        self, ledger_filter: LedgerFilter, limit: int = 100, after: LedgerCursor | None = None
    ) -> list[LedgerEntry]:
        """Entries newest first, starting after `after`."""
        ...

    async def spend(self, group_by: GroupBy, ledger_filter: LedgerFilter) -> list[SpendRow]: ...

    async def total_cost(self, ledger_filter: LedgerFilter) -> int:
        """Sum of priced cost in nanodollars (unpriced requests count as zero)."""
        ...

    async def timeseries(
        self, interval: Interval, group_by: GroupBy | None, ledger_filter: LedgerFilter
    ) -> list[SpendPoint]:
        """Only buckets with at least one request are returned, ordered by bucket then group."""
        ...
