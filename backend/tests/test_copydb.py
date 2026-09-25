import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select

from tollbooth.cli import main
from tollbooth.copydb import CopyError, copy_database
from tollbooth.db import create_engine, metadata, run_migrations
from tollbooth.domain import (
    Alert,
    Budget,
    BudgetPeriod,
    BudgetScope,
    Channel,
    ChannelType,
    Delivery,
    DeliveryStatus,
    Enforcement,
    LedgerEntry,
    Outcome,
    Provider,
    Usage,
)
from tollbooth.repositories.sql import (
    SqlAlertRepository,
    SqlBudgetRepository,
    SqlChannelRepository,
    SqlCredentialRepository,
    SqlKeyRepository,
    SqlLedgerRepository,
)

NOW = datetime(2026, 9, 24, 12, 30, 15, 123456, tzinfo=UTC)


async def _seed(url: str) -> None:
    await asyncio.to_thread(run_migrations, url)
    engine = create_engine(url)
    cred = await SqlCredentialRepository(engine).create("openai", Provider.OPENAI, "enc")
    key = await SqlKeyRepository(engine).create("svc", "search", "hash", "tb_abcdefgh", cred.id)
    ledger = SqlLedgerRepository(engine)
    for i in range(2500):
        await ledger.record(
            LedgerEntry(
                id=f"e{i:05}",
                created_at=NOW,
                team="search",
                virtual_key_id=key.id,
                provider=Provider.OPENAI,
                model="gpt-4o-mini",
                streamed=i % 2 == 0,
                status_code=200,
                outcome=Outcome.SUCCESS,
                latency_ms=i,
                usage=Usage(input_tokens=i, cache_write_1h_tokens=1),
                cost_nanousd=None if i == 7 else 9_000_000_000_000 + i,
                ttfb_ms=None if i % 3 else 12,
            )
        )
    channel = Channel("c1", "slack", ChannelType.SLACK, "hooks.slack.com", NOW)
    await SqlChannelRepository(engine).create(channel, "enc-url", None)
    await SqlBudgetRepository(engine).create(
        Budget(
            id="b1",
            name="search",
            scope=BudgetScope.TEAM,
            scope_value="search",
            period=BudgetPeriod.MONTH,
            limit_nanousd=10**12,
            enforcement=Enforcement.HARD,
            thresholds=(50, 100),
            enabled=True,
            created_at=NOW,
            updated_at=NOW,
            channel_ids=("c1",),
        )
    )
    alerts = SqlAlertRepository(engine)
    await alerts.create_if_absent(
        Alert("a1", "b1", "search", 50, NOW, NOW, 5 * 10**11, 10**12, NOW)
    )
    await alerts.save_delivery(
        Delivery("d1", "a1", "c1", "slack", DeliveryStatus.FAILED, 4, "HTTP 500", NOW)
    )
    await engine.dispose()


async def _dump(url: str) -> dict[str, list[tuple[object, ...]]]:
    engine = create_engine(url)
    try:
        async with engine.connect() as conn:
            return {
                table.name: [
                    tuple(row)
                    for row in await conn.execute(
                        select(table).order_by(*table.primary_key.columns)
                    )
                ]
                for table in metadata.sorted_tables
            }
    finally:
        await engine.dispose()


async def test_copies_everything_exactly(tmp_path: Path, database_url: str) -> None:
    source = f"sqlite+aiosqlite:///{tmp_path / 'source.db'}"
    await _seed(source)

    copied = await copy_database(source, database_url, batch_size=1000)

    assert copied["ledger"] == 2500
    assert copied["budget_channels"] == 1
    assert copied["alert_deliveries"] == 1
    source_rows, target_rows = await _dump(source), await _dump(database_url)
    assert source_rows == target_rows
    first = target_rows["ledger"][0]
    assert NOW in first


async def test_refuses_a_non_empty_target(tmp_path: Path, database_url: str) -> None:
    source = f"sqlite+aiosqlite:///{tmp_path / 'source.db'}"
    await _seed(source)
    await copy_database(source, database_url)
    with pytest.raises(CopyError, match="not empty"):
        await copy_database(source, database_url)


async def test_refuses_an_unmigrated_source(tmp_path: Path, database_url: str) -> None:
    source = f"sqlite+aiosqlite:///{tmp_path / 'old.db'}"
    with pytest.raises(CopyError, match="expected"):
        await copy_database(source, database_url)


def test_cli_reports_errors(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    source = f"sqlite+aiosqlite:///{tmp_path / 'old.db'}"
    target = f"sqlite+aiosqlite:///{tmp_path / 'new.db'}"
    assert main(["copy-db", source, target]) == 1
    assert "error: source database is at migration None" in capsys.readouterr().err
