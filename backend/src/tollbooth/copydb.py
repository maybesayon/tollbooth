import asyncio

from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import func, insert, select

from tollbooth.db import alembic_config, create_engine, metadata, run_migrations


class CopyError(Exception):
    pass


async def copy_database(source_url: str, target_url: str, batch_size: int = 1000) -> dict[str, int]:
    """Copy every Tollbooth table from one database to another, e.g. SQLite to Postgres.

    The source must be fully migrated; the target is migrated here and must be empty. Rows are
    copied in foreign-key order inside a single target transaction, so a failure leaves the
    target empty.
    """
    source = create_engine(source_url)
    target = create_engine(target_url)
    try:
        head = ScriptDirectory.from_config(alembic_config(source_url)).get_current_head()
        async with source.connect() as conn:
            version = await conn.run_sync(
                lambda sync: MigrationContext.configure(sync).get_current_revision()
            )
        if version != head:
            raise CopyError(
                f"source database is at migration {version}, expected {head}: start Tollbooth "
                "against it once so it upgrades, then copy"
            )

        await asyncio.to_thread(run_migrations, target_url)
        async with target.connect() as conn:
            for table in metadata.sorted_tables:
                count = (await conn.execute(select(func.count()).select_from(table))).scalar_one()
                if count:
                    raise CopyError(f"target table {table.name} is not empty ({count} rows)")

        copied: dict[str, int] = {}
        async with source.connect() as src, target.begin() as dst:
            for table in metadata.sorted_tables:
                result = await src.stream(select(table))
                copied[table.name] = 0
                async for rows in result.partitions(batch_size):
                    await dst.execute(insert(table), [dict(row._mapping) for row in rows])
                    copied[table.name] += len(rows)
        return copied
    finally:
        await source.dispose()
        await target.dispose()
