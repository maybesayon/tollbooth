from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from tollbooth.domain import (
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


class LedgerRepository(Protocol):
    async def record(self, entry: LedgerEntry) -> None: ...

    async def page(
        self, ledger_filter: LedgerFilter, limit: int = 100, after: LedgerCursor | None = None
    ) -> list[LedgerEntry]:
        """Entries newest first, starting after `after`."""
        ...

    async def spend(self, group_by: GroupBy, ledger_filter: LedgerFilter) -> list[SpendRow]: ...

    async def timeseries(
        self, interval: Interval, group_by: GroupBy | None, ledger_filter: LedgerFilter
    ) -> list[SpendPoint]:
        """Only buckets with at least one request are returned, ordered by bucket then group."""
        ...
