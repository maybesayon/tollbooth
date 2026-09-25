import base64
import binascii
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    PlainSerializer,
    model_validator,
)

from tollbooth.api.fields import Text
from tollbooth.cost import nanousd_to_usd
from tollbooth.domain import (
    GroupBy,
    Interval,
    LedgerEntry,
    Outcome,
    Provider,
    SpendMetrics,
    SpendPoint,
    SpendRow,
)
from tollbooth.repositories.base import LedgerCursor, LedgerFilter

MAX_BUCKETS = {Interval.HOUR: 24 * 31, Interval.DAY: 3660}


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


class LedgerQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: UTCDatetime = Field(None, description="Inclusive. ISO 8601; naive values are UTC.")
    end: UTCDatetime = Field(None, description="Exclusive. ISO 8601; naive values are UTC.")
    team: Text | None = None
    provider: Provider | None = None
    model: Text | None = None
    key_id: Text | None = None
    outcome: Outcome | None = None

    @model_validator(mode="after")
    def _start_before_end(self) -> Self:
        if self.start and self.end and self.start >= self.end:
            raise ValueError("start must be before end")
        return self

    def to_filter(self) -> LedgerFilter:
        return LedgerFilter(
            start=self.start,
            end=self.end,
            team=self.team,
            provider=self.provider,
            model=self.model,
            virtual_key_id=self.key_id,
            outcome=self.outcome,
        )


class SpendQuery(LedgerQuery):
    group_by: GroupBy = GroupBy.TEAM


class TimeseriesQuery(LedgerQuery):
    start: Annotated[datetime, AfterValidator(_assume_utc)]  # type: ignore[assignment]
    end: Annotated[datetime, AfterValidator(_assume_utc)]  # type: ignore[assignment]
    interval: Interval = Interval.DAY
    group_by: GroupBy | None = None

    @model_validator(mode="after")
    def _bounded(self) -> Self:
        size = timedelta(hours=1) if self.interval is Interval.HOUR else timedelta(days=1)
        if (self.end - self.start) / size > MAX_BUCKETS[self.interval]:
            raise ValueError(f"range too long for interval={self.interval.value}")
        return self


def _valid_cursor(value: str | None) -> str | None:
    if value is not None:
        decode_cursor(value)
    return value


class RequestsQuery(LedgerQuery):
    limit: int = Field(50, ge=1, le=200)
    cursor: Annotated[str | None, AfterValidator(_valid_cursor)] = Field(
        None, description="`next_cursor` from the previous page."
    )

    def decoded_cursor(self) -> LedgerCursor | None:
        return decode_cursor(self.cursor) if self.cursor else None


class Metrics(BaseModel):
    requests: int
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    cost_usd: USD
    unpriced_requests: int = Field(description="Requests whose model had no price configured.")
    error_requests: int = Field(description="Requests whose outcome was not success.")

    @staticmethod
    def fields_of(metrics: SpendMetrics) -> dict[str, int | Decimal]:
        return {
            "requests": metrics.requests,
            "input_tokens": metrics.input_tokens,
            "output_tokens": metrics.output_tokens,
            "cache_read_tokens": metrics.cache_read_tokens,
            "cache_write_tokens": metrics.cache_write_tokens,
            "cost_usd": nanousd_to_usd(metrics.cost_nanousd),
            "unpriced_requests": metrics.unpriced_requests,
            "error_requests": metrics.error_requests,
        }

    @classmethod
    def total(cls, rows: list[SpendRow]) -> "Metrics":
        return cls(
            **cls.fields_of(
                SpendMetrics(
                    requests=sum(r.requests for r in rows),
                    input_tokens=sum(r.input_tokens for r in rows),
                    output_tokens=sum(r.output_tokens for r in rows),
                    cache_read_tokens=sum(r.cache_read_tokens for r in rows),
                    cache_write_tokens=sum(r.cache_write_tokens for r in rows),
                    cost_nanousd=sum(r.cost_nanousd for r in rows),
                    unpriced_requests=sum(r.unpriced_requests for r in rows),
                    error_requests=sum(r.error_requests for r in rows),
                )
            )
        )


class SpendGroup(Metrics):
    group: str


class SpendReport(BaseModel):
    group_by: GroupBy
    start: datetime | None
    end: datetime | None
    currency: str = "USD"
    total: Metrics
    groups: list[SpendGroup]

    @classmethod
    def of(cls, query: SpendQuery, rows: list[SpendRow]) -> "SpendReport":
        return cls(
            group_by=query.group_by,
            start=query.start,
            end=query.end,
            total=Metrics.total(rows),
            groups=[SpendGroup(group=r.group, **Metrics.fields_of(r)) for r in rows],
        )


class TimeseriesPoint(Metrics):
    bucket: datetime = Field(description="UTC start of the bucket.")
    group: str | None


class TimeseriesReport(BaseModel):
    interval: Interval
    group_by: GroupBy | None
    start: datetime
    end: datetime
    currency: str = "USD"
    points: list[TimeseriesPoint] = Field(description="Only buckets with requests are included.")

    @classmethod
    def of(cls, query: TimeseriesQuery, points: list[SpendPoint]) -> "TimeseriesReport":
        return cls(
            interval=query.interval,
            group_by=query.group_by,
            start=query.start,
            end=query.end,
            points=[
                TimeseriesPoint(bucket=p.bucket, group=p.group, **Metrics.fields_of(p))
                for p in points
            ],
        )


class RequestOut(BaseModel):
    id: str
    created_at: datetime
    team: str
    key_id: str
    provider: Provider
    model: str
    streamed: bool
    status_code: int
    outcome: Outcome
    latency_ms: int
    ttfb_ms: int | None
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    cost_usd: USD | None
    error_type: str | None
    upstream_request_id: str | None

    @classmethod
    def of(cls, entry: LedgerEntry) -> "RequestOut":
        usage = entry.usage
        return cls(
            id=entry.id,
            created_at=entry.created_at,
            team=entry.team,
            key_id=entry.virtual_key_id,
            provider=entry.provider,
            model=entry.model,
            streamed=entry.streamed,
            status_code=entry.status_code,
            outcome=entry.outcome,
            latency_ms=entry.latency_ms,
            ttfb_ms=entry.ttfb_ms,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_read_tokens=usage.cache_read_tokens,
            cache_write_tokens=usage.cache_write_tokens + usage.cache_write_1h_tokens,
            cost_usd=None if entry.cost_nanousd is None else nanousd_to_usd(entry.cost_nanousd),
            error_type=entry.error_type,
            upstream_request_id=entry.upstream_request_id,
        )


class RequestPage(BaseModel):
    items: list[RequestOut]
    next_cursor: str | None

    @classmethod
    def of(cls, entries: list[LedgerEntry], limit: int) -> "RequestPage":
        more = len(entries) > limit
        page = entries[:limit]
        cursor = encode_cursor(LedgerCursor(page[-1].created_at, page[-1].id)) if more else None
        return cls(items=[RequestOut.of(e) for e in page], next_cursor=cursor)


def encode_cursor(cursor: LedgerCursor) -> str:
    raw = f"{cursor.created_at.isoformat()}|{cursor.id}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(value: str) -> LedgerCursor:
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)).decode()
        created_at, key_id = raw.split("|", 1)
        parsed = datetime.fromisoformat(created_at)
    except (binascii.Error, UnicodeDecodeError, ValueError) as e:
        raise ValueError("invalid cursor") from e
    if parsed.tzinfo is None or not key_id:
        raise ValueError("invalid cursor")
    return LedgerCursor(created_at=parsed, id=key_id)
