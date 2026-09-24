import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncEngine

from tollbooth.db import create_engine, run_migrations
from tollbooth.main import create_app
from tollbooth.settings import Settings
from tollbooth.state import AppState

ADMIN_TOKEN = "test-admin-token"
PRICING_FILE = Path(__file__).parent.parent / "pricing.toml"


@pytest.fixture
def database_url(tmp_path: Path) -> str:
    return f"sqlite+aiosqlite:///{tmp_path / 'tollbooth.db'}"


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
def upstream_transport() -> httpx.AsyncBaseTransport | None:
    return None


@pytest.fixture
async def app(
    settings: Settings, upstream_transport: httpx.AsyncBaseTransport | None
) -> AsyncIterator[FastAPI]:
    app = create_app(settings, upstream_transport=upstream_transport)
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
