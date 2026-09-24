from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from tollbooth.domain import (
    GroupBy,
    LedgerEntry,
    Provider,
    ProviderCredential,
    SpendRow,
    VirtualKey,
)


class DuplicateNameError(Exception):
    pass


@dataclass(frozen=True)
class SpendFilter:
    start: datetime | None = None
    end: datetime | None = None
    team: str | None = None
    provider: Provider | None = None
    model: str | None = None
    virtual_key_id: str | None = None


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

    async def recent(self, limit: int = 100) -> list[LedgerEntry]: ...

    async def spend(self, group_by: GroupBy, spend_filter: SpendFilter) -> list[SpendRow]: ...
