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


@dataclass(frozen=True)
class SpendRow:
    group: str
    requests: int
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    cost_nanousd: int
    unpriced_requests: int
