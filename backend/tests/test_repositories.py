from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine as create_sync_engine
from sqlalchemy.ext.asyncio import AsyncEngine

from tollbooth.db import metadata
from tollbooth.domain import GroupBy, LedgerEntry, Outcome, Provider, Usage
from tollbooth.repositories.base import DuplicateNameError, LedgerFilter
from tollbooth.repositories.sql import (
    SqlCredentialRepository,
    SqlKeyRepository,
    SqlLedgerRepository,
)
from tollbooth.security import new_id

T0 = datetime(2026, 9, 1, tzinfo=UTC)


def test_migrations_match_metadata(engine: AsyncEngine, database_url: str) -> None:
    sync_engine = create_sync_engine(database_url.replace("+aiosqlite", ""))
    with sync_engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), metadata)
    sync_engine.dispose()
    assert diff == []


async def test_credentials(engine: AsyncEngine) -> None:
    repo = SqlCredentialRepository(engine)
    cred = await repo.create("openai-prod", Provider.OPENAI, "ciphertext")
    assert await repo.get(cred.id) == cred
    assert await repo.get_encrypted_key(cred.id) == "ciphertext"
    assert await repo.list_all() == [cred]
    assert await repo.get("missing") is None
    with pytest.raises(DuplicateNameError):
        await repo.create("openai-prod", Provider.OPENAI, "other")


async def test_keys_lifecycle(engine: AsyncEngine) -> None:
    cred = await SqlCredentialRepository(engine).create("c", Provider.ANTHROPIC, "x")
    repo = SqlKeyRepository(engine)
    key = await repo.create("svc", "search", "hash1", "tb_abcdefgh", cred.id)
    assert key.provider is Provider.ANTHROPIC
    assert key.created_at.tzinfo is UTC
    assert key.is_active
    assert await repo.get_by_hash("hash1") == key

    other = await repo.create("svc2", "ads", "hash2", "tb_ijklmnop", cred.id)
    assert await repo.list_all(team="ads") == [other]

    revoked = await repo.revoke(key.id)
    assert revoked is not None and revoked.revoked_at is not None
    assert (await repo.revoke(key.id)) == revoked
    assert await repo.list_all() == [other]
    assert {k.id for k in await repo.list_all(include_revoked=True)} == {key.id, other.id}
    assert await repo.revoke("missing") is None


def _entry(**overrides: object) -> LedgerEntry:
    base = LedgerEntry(
        id=new_id(),
        created_at=T0,
        team="search",
        virtual_key_id="k1",
        provider=Provider.OPENAI,
        model="gpt-4o",
        streamed=False,
        status_code=200,
        outcome=Outcome.SUCCESS,
        latency_ms=120,
        usage=Usage(input_tokens=10, output_tokens=5, cache_read_tokens=2),
        cost_nanousd=1000,
    )
    return replace(base, id=new_id(), **overrides)


async def test_ledger_round_trip(engine: AsyncEngine) -> None:
    repo = SqlLedgerRepository(engine)
    entry = _entry(
        ttfb_ms=30,
        error_type="rate_limit_error",
        upstream_request_id="req_1",
        usage=Usage(1, 2, 3, 4, 5),
    )
    await repo.record(entry)
    assert await repo.page(LedgerFilter()) == [entry]


async def test_spend_grouping_and_filters(engine: AsyncEngine) -> None:
    repo = SqlLedgerRepository(engine)
    await repo.record(_entry())
    await repo.record(_entry(created_at=T0 + timedelta(days=1), cost_nanousd=2000))
    await repo.record(_entry(team="ads", model="gpt-4o-mini", cost_nanousd=500))
    await repo.record(
        _entry(
            team="ads",
            provider=Provider.ANTHROPIC,
            model="claude-sonnet-5",
            cost_nanousd=None,
            usage=Usage(input_tokens=1, cache_write_tokens=3, cache_write_1h_tokens=4),
        )
    )

    by_team = await repo.spend(GroupBy.TEAM, LedgerFilter())
    assert [(r.group, r.requests, r.cost_nanousd, r.unpriced_requests) for r in by_team] == [
        ("search", 2, 3000, 0),
        ("ads", 2, 500, 1),
    ]
    ads = by_team[1]
    assert (ads.input_tokens, ads.cache_write_tokens) == (11, 7)

    by_provider = await repo.spend(GroupBy.PROVIDER, LedgerFilter())
    assert {r.group: r.cost_nanousd for r in by_provider} == {"openai": 3500, "anthropic": 0}

    first_day = LedgerFilter(start=T0, end=T0 + timedelta(days=1))
    assert sum(r.requests for r in await repo.spend(GroupBy.MODEL, first_day)) == 3

    only = await repo.spend(GroupBy.KEY, LedgerFilter(team="ads", provider=Provider.OPENAI))
    assert [(r.group, r.cost_nanousd) for r in only] == [("k1", 500)]
    assert await repo.spend(GroupBy.TEAM, LedgerFilter(model="nope")) == []
