import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from tollbooth.alerts import AlertManager
from tollbooth.api import (
    admin_routes,
    alert_routes,
    auth_routes,
    budget_routes,
    ledger_routes,
    proxy_routes,
    user_routes,
)
from tollbooth.auth import LoginThrottle
from tollbooth.budgets import BudgetTracker
from tollbooth.dashboard import mount_dashboard
from tollbooth.db import create_engine, run_migrations
from tollbooth.pricing import load_pricing
from tollbooth.repositories.sql import (
    SqlAlertRepository,
    SqlBudgetRepository,
    SqlChannelRepository,
    SqlCredentialRepository,
    SqlKeyRepository,
    SqlLedgerRepository,
)
from tollbooth.repositories.sql_auth import (
    SqlApiTokenRepository,
    SqlSessionRepository,
    SqlUserRepository,
)
from tollbooth.security import SecretBox
from tollbooth.settings import Settings
from tollbooth.state import AppState

CallNext = Callable[[Request], Awaitable[Response]]


def create_app(
    settings: Settings | None = None,
    upstream_transport: httpx.AsyncBaseTransport | None = None,
    notification_transport: httpx.AsyncBaseTransport | None = None,
    alert_retry_delays: tuple[float, ...] = (1.0, 5.0, 25.0),
) -> FastAPI:
    """The transports let tests route provider and webhook traffic to in-process fakes."""
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
        async with (
            httpx.AsyncClient(timeout=timeout, transport=upstream_transport) as upstream,
            httpx.AsyncClient(timeout=10.0, transport=notification_transport) as notifier,
        ):
            secret_box = SecretBox(resolved.encryption_key.get_secret_value())
            ledger = SqlLedgerRepository(engine)
            budgets = SqlBudgetRepository(engine)
            channels = SqlChannelRepository(engine)
            alerts = SqlAlertRepository(engine)
            alert_manager = AlertManager(
                alerts, channels, secret_box, notifier, retry_delays=alert_retry_delays
            )
            app.state.tollbooth = AppState(
                settings=resolved,
                pricing=pricing,
                engine=engine,
                upstream=upstream,
                secret_box=secret_box,
                credentials=SqlCredentialRepository(engine),
                keys=SqlKeyRepository(engine),
                ledger=ledger,
                budgets=budgets,
                budget_tracker=BudgetTracker(budgets, ledger),
                channels=channels,
                alerts=alerts,
                alert_manager=alert_manager,
                users=SqlUserRepository(engine),
                sessions=SqlSessionRepository(engine),
                api_tokens=SqlApiTokenRepository(engine),
                login_throttle=LoginThrottle(),
            )
            try:
                yield
            finally:
                await alert_manager.aclose()
                await engine.dispose()

    app = FastAPI(title="Tollbooth", lifespan=lifespan)

    @app.middleware("http")
    async def reject_nul(request: Request, call_next: CallNext) -> Response:
        # Postgres text cannot hold NUL, and path and query values reach queries as given.
        values = [request.url.path, *(x for kv in request.query_params.multi_items() for x in kv)]
        if any("\x00" in value for value in values):
            return JSONResponse({"detail": "NUL characters are not allowed"}, status_code=400)
        return await call_next(request)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(admin_routes.router)
    app.include_router(ledger_routes.router)
    app.include_router(budget_routes.router)
    app.include_router(alert_routes.router)
    app.include_router(auth_routes.router)
    app.include_router(user_routes.router)
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
