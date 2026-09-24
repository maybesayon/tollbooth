from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, PlainSerializer, SecretStr

from tollbooth.cost import nanousd_to_usd
from tollbooth.domain import GroupBy, Provider, ProviderCredential, SpendRow, VirtualKey

Name = Annotated[str, Field(min_length=1, max_length=200, pattern=r"\S")]


class CredentialCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name
    provider: Provider
    api_key: SecretStr = Field(min_length=1)


class CredentialOut(BaseModel):
    id: str
    name: str
    provider: Provider
    created_at: datetime

    @classmethod
    def of(cls, credential: ProviderCredential) -> "CredentialOut":
        return cls(
            id=credential.id,
            name=credential.name,
            provider=credential.provider,
            created_at=credential.created_at,
        )


class KeyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name
    team: Name
    credential_id: str


class KeyOut(BaseModel):
    id: str
    name: str
    team: str
    key_prefix: str
    provider: Provider
    credential_id: str
    created_at: datetime
    revoked_at: datetime | None

    @classmethod
    def of(cls, key: VirtualKey) -> "KeyOut":
        return cls(
            id=key.id,
            name=key.name,
            team=key.team,
            key_prefix=key.key_prefix,
            provider=key.provider,
            credential_id=key.credential_id,
            created_at=key.created_at,
            revoked_at=key.revoked_at,
        )


class KeyCreated(KeyOut):
    key: str = Field(description="The virtual key. Shown only once; store it now.")


def _assume_utc(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


UTCDatetime = Annotated[datetime | None, AfterValidator(_assume_utc)]
USD = Annotated[
    Decimal,
    PlainSerializer(lambda value: format(value, "f"), return_type=str, when_used="json"),
    Field(description='Exact fixed-point decimal string, e.g. "0.000517801".'),
]


class SpendQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    group_by: GroupBy = GroupBy.TEAM
    start: UTCDatetime = Field(None, description="Inclusive. ISO 8601; naive values are UTC.")
    end: UTCDatetime = Field(None, description="Exclusive. ISO 8601; naive values are UTC.")
    team: str | None = None
    provider: Provider | None = None
    model: str | None = None
    key_id: str | None = None


class SpendTotals(BaseModel):
    requests: int
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    cost_usd: USD
    unpriced_requests: int = Field(description="Requests whose model had no price configured.")


class SpendGroup(SpendTotals):
    group: str

    @classmethod
    def of(cls, row: SpendRow) -> "SpendGroup":
        return cls(
            group=row.group,
            requests=row.requests,
            input_tokens=row.input_tokens,
            output_tokens=row.output_tokens,
            cache_read_tokens=row.cache_read_tokens,
            cache_write_tokens=row.cache_write_tokens,
            cost_usd=nanousd_to_usd(row.cost_nanousd),
            unpriced_requests=row.unpriced_requests,
        )


class SpendReport(BaseModel):
    group_by: GroupBy
    start: datetime | None
    end: datetime | None
    currency: str = "USD"
    total: SpendTotals
    groups: list[SpendGroup]

    @classmethod
    def of(cls, query: SpendQuery, rows: list[SpendRow]) -> "SpendReport":
        total = SpendTotals(
            requests=sum(r.requests for r in rows),
            input_tokens=sum(r.input_tokens for r in rows),
            output_tokens=sum(r.output_tokens for r in rows),
            cache_read_tokens=sum(r.cache_read_tokens for r in rows),
            cache_write_tokens=sum(r.cache_write_tokens for r in rows),
            cost_usd=nanousd_to_usd(sum(r.cost_nanousd for r in rows)),
            unpriced_requests=sum(r.unpriced_requests for r in rows),
        )
        return cls(
            group_by=query.group_by,
            start=query.start,
            end=query.end,
            total=total,
            groups=[SpendGroup.of(r) for r in rows],
        )
