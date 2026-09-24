import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from tollbooth.api import admin_routes, budget_routes, ledger_routes, proxy_routes
from tollbooth.budgets import BudgetTracker
from tollbooth.dashboard import mount_dashboard
from tollbooth.db import create_engine, run_migrations
from tollbooth.pricing import load_pricing
from tollbooth.repositories.sql import (
    SqlBudgetRepository,
    SqlCredentialRepository,
    SqlKeyRepository,
    SqlLedgerRepository,
)
from tollbooth.security import SecretBox
from tollbooth.settings import Settings
from tollbooth.state import AppState


def create_app(
    settings: Settings | None = None,
    upstream_transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    """`upstream_transport` lets tests route provider traffic to in-process mock providers."""
    resolved = settings or Settings()  # type: ignore[call-arg]

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        _configure_logging(resolved.log_level)
        pricing = load_pricing(resolved.pricing_file)
        if resolved.auto_migrate:
            await asyncio.to_thread(run_migrations, resolved.database_url)
        engine = create_engine(resolved.database_url)
        timeout = httpx.Timeout(
            resolved.upstream_read_timeout, connect=resolved.upstream_connect_timeout
        )
        async with httpx.AsyncClient(timeout=timeout, transport=upstream_transport) as upstream:
            ledger = SqlLedgerRepository(engine)
            budgets = SqlBudgetRepository(engine)
            app.state.tollbooth = AppState(
                settings=resolved,
                pricing=pricing,
                engine=engine,
                upstream=upstream,
                secret_box=SecretBox(resolved.encryption_key.get_secret_value()),
                credentials=SqlCredentialRepository(engine),
                keys=SqlKeyRepository(engine),
                ledger=ledger,
                budgets=budgets,
                budget_tracker=BudgetTracker(budgets, ledger),
            )
            try:
                yield
            finally:
                await engine.dispose()

    app = FastAPI(title="Tollbooth", lifespan=lifespan)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(admin_routes.router)
    app.include_router(ledger_routes.router)
    app.include_router(budget_routes.router)
    app.include_router(proxy_routes.router)
    if resolved.dashboard_dir is not None:
        mount_dashboard(app, resolved.dashboard_dir)
    return app


def _configure_logging(level: str) -> None:
    logger = logging.getLogger("tollbooth")
    logger.setLevel(level)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        logger.addHandler(handler)
