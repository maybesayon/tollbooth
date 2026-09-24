import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path

import httpx
import pytest
from cryptography.fernet import Fernet
from fake_webhooks import WebhookReceiver
from fastapi import FastAPI
from mock_providers import ANTHROPIC_REAL_KEY, OPENAI_REAL_KEY, MockProviders
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncEngine

from tollbooth.db import create_engine, run_migrations
from tollbooth.domain import Provider
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
