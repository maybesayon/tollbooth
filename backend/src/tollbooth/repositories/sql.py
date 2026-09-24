import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    ColumnElement,
    Row,
    Select,
    and_,
    case,
    delete,
    func,
    insert,
    or_,
    select,
    update,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from tollbooth.db import budgets, ledger, provider_credentials, virtual_keys
from tollbooth.domain import (
    Budget,
    BudgetPeriod,
    BudgetScope,
    Enforcement,
    GroupBy,
    Interval,
    LedgerEntry,
    Outcome,
    Provider,
    ProviderCredential,
    SpendPoint,
    SpendRow,
    Usage,
    VirtualKey,
)
from tollbooth.repositories.base import DuplicateNameError, LedgerCursor, LedgerFilter
from tollbooth.security import new_id


def _now() -> datetime:
    return datetime.now(UTC)


class SqlCredentialRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def create(self, name: str, provider: Provider, encrypted_key: str) -> ProviderCredential:
        credential = ProviderCredential(
            id=new_id(), name=name, provider=provider, created_at=_now()
        )
        try:
            async with self._engine.begin() as conn:
                await conn.execute(
                    insert(provider_credentials).values(
                        id=credential.id,
                        name=credential.name,
                        provider=credential.provider.value,
                        encrypted_key=encrypted_key,
                        created_at=credential.created_at,
                    )
                )
        except IntegrityError as e:
            raise DuplicateNameError(f"credential name already exists: {name}") from e
        return credential

    async def get(self, credential_id: str) -> ProviderCredential | None:
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(
                    _credential_columns().where(provider_credentials.c.id == credential_id)
                )
            ).first()
        return _to_credential(row) if row else None

    async def get_encrypted_key(self, credential_id: str) -> str | None:
        async with self._engine.connect() as conn:
            return (
                await conn.execute(
                    select(provider_credentials.c.encrypted_key).where(
                        provider_credentials.c.id == credential_id
                    )
                )
            ).scalar_one_or_none()

    async def list_all(self) -> list[ProviderCredential]:
        async with self._engine.connect() as conn:
            rows = await conn.execute(
                _credential_columns().order_by(provider_credentials.c.created_at)
            )
        return [_to_credential(r) for r in rows]


class SqlKeyRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def create(
        self, name: str, team: str, key_hash: str, key_prefix: str, credential_id: str
    ) -> VirtualKey:
        key_id = new_id()
        async with self._engine.begin() as conn:
            await conn.execute(
                insert(virtual_keys).values(
                    id=key_id,
                    name=name,
                    team=team,
                    key_hash=key_hash,
                    key_prefix=key_prefix,
                    credential_id=credential_id,
                    created_at=_now(),
                )
            )
        key = await self.get(key_id)
        assert key is not None
        return key

    async def get(self, key_id: str) -> VirtualKey | None:
        return await self._one(_key_columns().where(virtual_keys.c.id == key_id))

    async def get_by_hash(self, key_hash: str) -> VirtualKey | None:
        return await self._one(_key_columns().where(virtual_keys.c.key_hash == key_hash))

    async def list_all(
        self, team: str | None = None, include_revoked: bool = False
    ) -> list[VirtualKey]:
        query = _key_columns().order_by(virtual_keys.c.created_at)
        if team is not None:
            query = query.where(virtual_keys.c.team == team)
        if not include_revoked:
            query = query.where(virtual_keys.c.revoked_at.is_(None))
        async with self._engine.connect() as conn:
            rows = await conn.execute(query)
        return [_to_key(r) for r in rows]

    async def revoke(self, key_id: str) -> VirtualKey | None:
        async with self._engine.begin() as conn:
            await conn.execute(
                update(virtual_keys)
                .where(virtual_keys.c.id == key_id, virtual_keys.c.revoked_at.is_(None))
                .values(revoked_at=_now())
            )
        return await self.get(key_id)

    async def _one(self, query: Select[tuple[object, ...]]) -> VirtualKey | None:
        async with self._engine.connect() as conn:
            row = (await conn.execute(query)).first()
        return _to_key(row) if row else None


_GROUP_COLUMNS = {
    GroupBy.TEAM: ledger.c.team,
    GroupBy.MODEL: ledger.c.model,
    GroupBy.PROVIDER: ledger.c.provider,
    GroupBy.KEY: ledger.c.virtual_key_id,
}


class SqlLedgerRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def record(self, entry: LedgerEntry) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                insert(ledger).values(
                    id=entry.id,
                    created_at=entry.created_at,
                    team=entry.team,
                    virtual_key_id=entry.virtual_key_id,
                    provider=entry.provider.value,
                    model=entry.model,
                    streamed=entry.streamed,
                    status_code=entry.status_code,
                    outcome=entry.outcome.value,
                    latency_ms=entry.latency_ms,
                    ttfb_ms=entry.ttfb_ms,
                    input_tokens=entry.usage.input_tokens,
                    output_tokens=entry.usage.output_tokens,
                    cache_read_tokens=entry.usage.cache_read_tokens,
                    cache_write_tokens=entry.usage.cache_write_tokens,
                    cache_write_1h_tokens=entry.usage.cache_write_1h_tokens,
                    cost_nanousd=entry.cost_nanousd,
                    error_type=entry.error_type,
                    upstream_request_id=entry.upstream_request_id,
                )
            )

    async def page(
        self, ledger_filter: LedgerFilter, limit: int = 100, after: LedgerCursor | None = None
    ) -> list[LedgerEntry]:
        query = _filtered(select(ledger), ledger_filter)
        if after is not None:
            query = query.where(
                or_(
                    ledger.c.created_at < after.created_at,
                    and_(ledger.c.created_at == after.created_at, ledger.c.id < after.id),
                )
            )
        query = query.order_by(ledger.c.created_at.desc(), ledger.c.id.desc()).limit(limit)
        async with self._engine.connect() as conn:
            rows = await conn.execute(query)
        return [_to_entry(r) for r in rows]

    async def spend(self, group_by: GroupBy, ledger_filter: LedgerFilter) -> list[SpendRow]:
        group = _GROUP_COLUMNS[group_by]
        query = (
            select(group.label("group"), *_metrics()).group_by(group).order_by(_COST.desc(), group)
        )
        async with self._engine.connect() as conn:
            rows = await conn.execute(_filtered(query, ledger_filter))
        return [SpendRow(group=r.group, **_metric_values(r)) for r in rows]

    async def total_cost(self, ledger_filter: LedgerFilter) -> int:
        query = _filtered(select(_COST), ledger_filter)
        async with self._engine.connect() as conn:
            return int((await conn.execute(query)).scalar_one())

    async def timeseries(
        self, interval: Interval, group_by: GroupBy | None, ledger_filter: LedgerFilter
    ) -> list[SpendPoint]:
        bucket = _bucket(self._engine.dialect.name, interval).label("bucket")
        keys: list[ColumnElement[Any]] = [bucket]
        if group_by is not None:
            keys.append(_GROUP_COLUMNS[group_by].label("group"))
        query = select(*keys, *_metrics()).group_by(*keys).order_by(*keys)
        async with self._engine.connect() as conn:
            rows = await conn.execute(_filtered(query, ledger_filter))
        return [
            SpendPoint(
                bucket=_as_utc(r.bucket),
                group=r.group if group_by is not None else None,
                **_metric_values(r),
            )
            for r in rows
        ]


class SqlBudgetRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def create(self, budget: Budget) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(insert(budgets).values(**_budget_values(budget)))

    async def get(self, budget_id: str) -> Budget | None:
        async with self._engine.connect() as conn:
            row = (await conn.execute(select(budgets).where(budgets.c.id == budget_id))).first()
        return _to_budget(row) if row else None

    async def list_all(self) -> list[Budget]:
        async with self._engine.connect() as conn:
            rows = await conn.execute(select(budgets).order_by(budgets.c.created_at))
        return [_to_budget(r) for r in rows]

    async def update(self, budget: Budget) -> bool:
        values = _budget_values(budget)
        del values["id"], values["created_at"]
        async with self._engine.begin() as conn:
            result = await conn.execute(
                update(budgets).where(budgets.c.id == budget.id).values(**values)
            )
        return result.rowcount > 0

    async def delete(self, budget_id: str) -> bool:
        async with self._engine.begin() as conn:
            result = await conn.execute(delete(budgets).where(budgets.c.id == budget_id))
        return result.rowcount > 0


def _budget_values(budget: Budget) -> dict[str, Any]:
    return {
        "id": budget.id,
        "name": budget.name,
        "scope": budget.scope.value,
        "scope_value": budget.scope_value,
        "period": budget.period.value,
        "limit_nanousd": budget.limit_nanousd,
        "enforcement": budget.enforcement.value,
        "thresholds": json.dumps(list(budget.thresholds)),
        "enabled": budget.enabled,
        "created_at": budget.created_at,
        "updated_at": budget.updated_at,
    }


def _to_budget(row: Row[Any]) -> Budget:
    m = row._mapping
    return Budget(
        id=m["id"],
        name=m["name"],
        scope=BudgetScope(m["scope"]),
        scope_value=m["scope_value"],
        period=BudgetPeriod(m["period"]),
        limit_nanousd=m["limit_nanousd"],
        enforcement=Enforcement(m["enforcement"]),
        thresholds=tuple(json.loads(m["thresholds"])),
        enabled=m["enabled"],
        created_at=m["created_at"],
        updated_at=m["updated_at"],
    )


_COST = func.coalesce(func.sum(ledger.c.cost_nanousd), 0)


def _metrics() -> list[ColumnElement[Any]]:
    return [
        func.count().label("requests"),
        func.sum(ledger.c.input_tokens).label("input_tokens"),
        func.sum(ledger.c.output_tokens).label("output_tokens"),
        func.sum(ledger.c.cache_read_tokens).label("cache_read_tokens"),
        func.sum(ledger.c.cache_write_tokens + ledger.c.cache_write_1h_tokens).label(
            "cache_write_tokens"
        ),
        _COST.label("cost_nanousd"),
        func.sum(case((ledger.c.cost_nanousd.is_(None), 1), else_=0)).label("unpriced_requests"),
        func.sum(case((ledger.c.outcome != Outcome.SUCCESS.value, 1), else_=0)).label(
            "error_requests"
        ),
    ]


def _metric_values(row: Row[Any]) -> dict[str, int]:
    return {
        name: getattr(row, name)
        for name in (
            "requests",
            "input_tokens",
            "output_tokens",
            "cache_read_tokens",
            "cache_write_tokens",
            "cost_nanousd",
            "unpriced_requests",
            "error_requests",
        )
    }


def _filtered[Q: Select[Any]](query: Q, f: LedgerFilter) -> Q:
    if f.start is not None:
        query = query.where(ledger.c.created_at >= f.start)
    if f.end is not None:
        query = query.where(ledger.c.created_at < f.end)
    if f.team is not None:
        query = query.where(ledger.c.team == f.team)
    if f.provider is not None:
        query = query.where(ledger.c.provider == f.provider.value)
    if f.model is not None:
        query = query.where(ledger.c.model == f.model)
    if f.virtual_key_id is not None:
        query = query.where(ledger.c.virtual_key_id == f.virtual_key_id)
    if f.outcome is not None:
        query = query.where(ledger.c.outcome == f.outcome.value)
    return query


def _bucket(dialect: str, interval: Interval) -> ColumnElement[Any]:
    if dialect == "sqlite":
        fmt = "%Y-%m-%d %H:00:00" if interval is Interval.HOUR else "%Y-%m-%d 00:00:00"
        return func.strftime(fmt, ledger.c.created_at)
    return func.date_trunc(interval.value, ledger.c.created_at)


def _as_utc(value: datetime | str) -> datetime:
    parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _credential_columns() -> Select[tuple[object, ...]]:
    c = provider_credentials.c
    return select(c.id, c.name, c.provider, c.created_at)


def _to_credential(row: Row[tuple[object, ...]]) -> ProviderCredential:
    m = row._mapping
    return ProviderCredential(
        id=m["id"], name=m["name"], provider=Provider(m["provider"]), created_at=m["created_at"]
    )


def _key_columns() -> Select[tuple[object, ...]]:
    k = virtual_keys.c
    return select(
        k.id,
        k.name,
        k.team,
        k.key_prefix,
        k.credential_id,
        provider_credentials.c.provider,
        k.created_at,
        k.revoked_at,
    ).join(provider_credentials, provider_credentials.c.id == k.credential_id)


def _to_key(row: Row[tuple[object, ...]]) -> VirtualKey:
    m = row._mapping
    return VirtualKey(
        id=m["id"],
        name=m["name"],
        team=m["team"],
        key_prefix=m["key_prefix"],
        credential_id=m["credential_id"],
        provider=Provider(m["provider"]),
        created_at=m["created_at"],
        revoked_at=m["revoked_at"],
    )


def _to_entry(row: Row[tuple[object, ...]]) -> LedgerEntry:
    m = row._mapping
    return LedgerEntry(
        id=m["id"],
        created_at=m["created_at"],
        team=m["team"],
        virtual_key_id=m["virtual_key_id"],
        provider=Provider(m["provider"]),
        model=m["model"],
        streamed=m["streamed"],
        status_code=m["status_code"],
        outcome=Outcome(m["outcome"]),
        latency_ms=m["latency_ms"],
        ttfb_ms=m["ttfb_ms"],
        usage=Usage(
            input_tokens=m["input_tokens"],
            output_tokens=m["output_tokens"],
            cache_read_tokens=m["cache_read_tokens"],
            cache_write_tokens=m["cache_write_tokens"],
            cache_write_1h_tokens=m["cache_write_1h_tokens"],
        ),
        cost_nanousd=m["cost_nanousd"],
        error_type=m["error_type"],
        upstream_request_id=m["upstream_request_id"],
    )
