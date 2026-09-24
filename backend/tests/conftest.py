import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from tollbooth.db import create_engine, run_migrations


@pytest.fixture
def database_url(tmp_path: Path) -> str:
    return f"sqlite+aiosqlite:///{tmp_path / 'tollbooth.db'}"


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    await asyncio.to_thread(run_migrations, database_url)
    engine = create_engine(database_url)
    yield engine
    await engine.dispose()
