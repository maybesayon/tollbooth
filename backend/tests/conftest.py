import asyncio
import os
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Coroutine, Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import asyncpg
import httpx
import pytest
from cryptography.fernet import Fernet
from fake_webhooks import WebhookReceiver
from fastapi import FastAPI
from mock_providers import ANTHROPIC_REAL_KEY, OPENAI_REAL_KEY, MockProviders
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine

from tollbooth.db import create_engine, metadata, run_migrations
from tollbooth.domain import Provider
from tollbooth.main import create_app
from tollbooth.settings import Settings
from tollbooth.state import AppState

ADMIN_TOKEN = "test-admin-token"
PRICING_FILE = Path(__file__).parent.parent / "pricing.toml"


POSTGRES_URL = os.environ.get("TOLLBOOTH_TEST_POSTGRES_URL")
"""e.g. postgresql+asyncpg://user@127.0.0.1:5432/postgres; when set, every test gets a fresh
Postgres database instead of a SQLite file."""


def _in_thread[T](coro: Coroutine[object, object, T]) -> T:
    """Run admin coroutines on their own loop so pytest-asyncio's loop is untouched."""
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


async def _admin_sql(statement: str) -> None:
    assert POSTGRES_URL is not None
    url = make_url(POSTGRES_URL).set(drivername="postgresql")
    conn = await asyncpg.connect(url.render_as_string(hide_password=False))
    try:
        await conn.execute(statement)
    finally:
        await conn.close()


@pytest.fixture(scope="session")
def postgres_template() -> Iterator[str | None]:
    """A database migrated once per session; each test clones it."""
    if POSTGRES_URL is None:
        yield None
        return
    name = f"tollbooth_template_{uuid.uuid4().hex[:8]}"
    _in_thread(_admin_sql(f'CREATE DATABASE "{name}"'))
    run_migrations(make_url(POSTGRES_URL).set(database=name).render_as_string(False))
    yield name
    _in_thread(_admin_sql(f'DROP DATABASE "{name}" WITH (FORCE)'))


@pytest.fixture
def database_url(tmp_path: Path, postgres_template: str | None) -> Iterator[str]:
    if POSTGRES_URL is None or postgres_template is None:
        yield f"sqlite+aiosqlite:///{tmp_path / 'tollbooth.db'}"
        return
    name = f"tollbooth_test_{uuid.uuid4().hex[:12]}"
    _in_thread(_admin_sql(f'CREATE DATABASE "{name}" TEMPLATE "{postgres_template}"'))
    yield make_url(POSTGRES_URL).set(database=name).render_as_string(hide_password=False)
    _in_thread(_admin_sql(f'DROP DATABASE "{name}" WITH (FORCE)'))


async def persisted_bytes(engine: AsyncEngine, directory: Path) -> bytes:
    """Everything the database holds: every row of every table, plus the raw files for SQLite
    (which also catches content left in free pages or the WAL)."""
    async with engine.connect() as conn:
        dump = [
            repr((await conn.execute(select(table))).all()).encode()
            for table in metadata.sorted_tables
        ]
    await engine.dispose()
    if engine.dialect.name == "sqlite":
        dump.append(await asyncio.to_thread(_read_files, directory))
    return b"".join(dump)


def _read_files(directory: Path) -> bytes:
    return b"".join(p.read_bytes() for p in sorted(directory.iterdir()) if p.is_file())


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    await asyncio.to_thread(run_migrations, database_url)
    engine = create_engine(database_url)
    yield engine
    await engine.dispose()


@pytest.fixture
def settings(database_url: str) -> Settings:
    return Settings(
        admin_token=SecretStr(ADMIN_TOKEN),
        encryption_key=SecretStr(Fernet.generate_key().decode()),
        database_url=database_url,
        pricing_file=PRICING_FILE,
        _env_file=None,  # type: ignore[call-arg]
    )


@pytest.fixture
def providers() -> MockProviders:
    return MockProviders()


@pytest.fixture
def upstream_transport(providers: MockProviders) -> httpx.AsyncBaseTransport:
    return providers.transport


@pytest.fixture
def webhooks() -> WebhookReceiver:
    return WebhookReceiver()


@pytest.fixture
async def app(
    settings: Settings,
    upstream_transport: httpx.AsyncBaseTransport,
    webhooks: WebhookReceiver,
) -> AsyncIterator[FastAPI]:
    app = create_app(
        settings,
        upstream_transport=upstream_transport,
        notification_transport=webhooks.transport,
        alert_retry_delays=(0.0, 0.0, 0.0),
    )
    async with app.router.lifespan_context(app):
        yield app


@pytest.fixture
def state(app: FastAPI) -> AppState:
    return app.state.tollbooth


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://tollbooth") as client:
        yield client


@pytest.fixture
def admin_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {ADMIN_TOKEN}"}


MakeKey = Callable[..., Awaitable[str]]


@pytest.fixture
def make_key(client: httpx.AsyncClient, admin_headers: dict[str, str]) -> MakeKey:
    """Creates a credential plus a virtual key through the admin API; returns the plaintext key."""

    async def make(provider: Provider, team: str = "search") -> str:
        real = OPENAI_REAL_KEY if provider is Provider.OPENAI else ANTHROPIC_REAL_KEY
        cred = await client.post(
            "/admin/credentials",
            json={"name": f"{provider}-{team}", "provider": provider, "api_key": real},
            headers=admin_headers,
        )
        key = await client.post(
            "/admin/keys",
            json={"name": "svc", "team": team, "credential_id": cred.json()["id"]},
            headers=admin_headers,
        )
        return key.json()["key"]

    return make
