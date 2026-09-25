from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Dialect,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    TypeDecorator,
    UniqueConstraint,
    event,
)
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


class UTCDateTime(TypeDecorator[datetime]):
    """Timezone-aware UTC datetimes on every backend (SQLite has no native timezone support)."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetimes are not allowed; use timezone-aware UTC")
        value = value.astimezone(UTC)
        return value.replace(tzinfo=None) if dialect.name == "sqlite" else value

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


metadata = MetaData(
    naming_convention={
        "ix": "ix_%(table_name)s_%(column_0_N_name)s",
        "uq": "uq_%(table_name)s_%(column_0_N_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    }
)

provider_credentials = Table(
    "provider_credentials",
    metadata,
    Column("id", String(32), primary_key=True),
    Column("name", String(200), nullable=False, unique=True),
    Column("provider", String(32), nullable=False),
    Column("encrypted_key", Text, nullable=False),
    Column("created_at", UTCDateTime, nullable=False),
)

virtual_keys = Table(
    "virtual_keys",
    metadata,
    Column("id", String(32), primary_key=True),
    Column("name", String(200), nullable=False),
    Column("team", String(200), nullable=False, index=True),
    Column("key_hash", String(64), nullable=False, unique=True),
    Column("key_prefix", String(16), nullable=False),
    Column("credential_id", String(32), ForeignKey("provider_credentials.id"), nullable=False),
    Column("created_at", UTCDateTime, nullable=False),
    Column("revoked_at", UTCDateTime, nullable=True),
)

ledger = Table(
    "ledger",
    metadata,
    Column("id", String(32), primary_key=True),
    Column("created_at", UTCDateTime, nullable=False, index=True),
    Column("team", String(200), nullable=False),
    Column("virtual_key_id", String(32), nullable=False),
    Column("provider", String(32), nullable=False),
    Column("model", String(200), nullable=False),
    Column("streamed", Boolean, nullable=False),
    Column("status_code", Integer, nullable=False),
    Column("outcome", String(32), nullable=False),
    Column("latency_ms", Integer, nullable=False),
    Column("ttfb_ms", Integer, nullable=True),
    Column("input_tokens", Integer, nullable=False),
    Column("output_tokens", Integer, nullable=False),
    Column("cache_read_tokens", Integer, nullable=False),
    Column("cache_write_tokens", Integer, nullable=False),
    Column("cache_write_1h_tokens", Integer, nullable=False),
    Column("cost_nanousd", BigInteger, nullable=True),
    Column("error_type", String(200), nullable=True),
    Column("upstream_request_id", String(200), nullable=True),
    Index(None, "team", "created_at"),
    Index(None, "virtual_key_id", "created_at"),
)


budgets = Table(
    "budgets",
    metadata,
    Column("id", String(32), primary_key=True),
    Column("name", String(200), nullable=False),
    Column("scope", String(16), nullable=False),
    Column("scope_value", String(200), nullable=True),
    Column("period", String(16), nullable=False),
    Column("limit_nanousd", BigInteger, nullable=False),
    Column("enforcement", String(16), nullable=False),
    Column("thresholds", Text, nullable=False),
    Column("enabled", Boolean, nullable=False),
    Column("created_at", UTCDateTime, nullable=False),
    Column("updated_at", UTCDateTime, nullable=False),
    Index(None, "scope", "scope_value"),
)


alert_channels = Table(
    "alert_channels",
    metadata,
    Column("id", String(32), primary_key=True),
    Column("name", String(200), nullable=False, unique=True),
    Column("type", String(16), nullable=False),
    Column("url_hint", String(200), nullable=False),
    Column("encrypted_url", Text, nullable=False),
    Column("encrypted_secret", Text, nullable=True),
    Column("created_at", UTCDateTime, nullable=False),
)

budget_channels = Table(
    "budget_channels",
    metadata,
    Column(
        "budget_id",
        String(32),
        ForeignKey("budgets.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "channel_id",
        String(32),
        ForeignKey("alert_channels.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)

budget_alerts = Table(
    "budget_alerts",
    metadata,
    Column("id", String(32), primary_key=True),
    Column("budget_id", String(32), nullable=False),
    Column("budget_name", String(200), nullable=False),
    Column("threshold", Integer, nullable=False),
    Column("period_start", UTCDateTime, nullable=False),
    Column("period_end", UTCDateTime, nullable=False),
    Column("spend_nanousd", BigInteger, nullable=False),
    Column("limit_nanousd", BigInteger, nullable=False),
    Column("created_at", UTCDateTime, nullable=False, index=True),
    UniqueConstraint("budget_id", "period_start", "threshold"),
)

alert_deliveries = Table(
    "alert_deliveries",
    metadata,
    Column("id", String(32), primary_key=True),
    Column(
        "alert_id",
        String(32),
        ForeignKey("budget_alerts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    ),
    Column("channel_id", String(32), nullable=False),
    Column("channel_name", String(200), nullable=False),
    Column("status", String(16), nullable=False),
    Column("attempts", Integer, nullable=False),
    Column("last_error", String(500), nullable=True),
    Column("updated_at", UTCDateTime, nullable=False),
)


users = Table(
    "users",
    metadata,
    Column("id", String(32), primary_key=True),
    Column("email", String(320), nullable=False, unique=True),
    Column("name", String(200), nullable=False),
    Column("role", String(16), nullable=False),
    Column("password_hash", Text, nullable=False),
    Column("created_at", UTCDateTime, nullable=False),
    Column("updated_at", UTCDateTime, nullable=False),
    Column("disabled_at", UTCDateTime, nullable=True),
    Column("last_login_at", UTCDateTime, nullable=True),
)

sessions = Table(
    "sessions",
    metadata,
    Column("id", String(64), primary_key=True),
    Column(
        "user_id",
        String(32),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    ),
    Column("created_at", UTCDateTime, nullable=False),
    Column("expires_at", UTCDateTime, nullable=False, index=True),
    Column("last_seen_at", UTCDateTime, nullable=False),
)

api_tokens = Table(
    "api_tokens",
    metadata,
    Column("id", String(32), primary_key=True),
    Column(
        "user_id",
        String(32),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    ),
    Column("name", String(200), nullable=False),
    Column("token_hash", String(64), nullable=False, unique=True),
    Column("prefix", String(16), nullable=False),
    Column("created_at", UTCDateTime, nullable=False),
    Column("last_used_at", UTCDateTime, nullable=True),
)


audit_log = Table(
    "audit_log",
    metadata,
    Column("id", String(32), primary_key=True),
    Column("created_at", UTCDateTime, nullable=False, index=True),
    Column("actor_type", String(16), nullable=False),
    Column("actor_id", String(32), nullable=True, index=True),
    Column("actor_label", String(320), nullable=False),
    Column("action", String(64), nullable=False, index=True),
    Column("target_type", String(32), nullable=True),
    Column("target_id", String(64), nullable=True),
    Column("details", Text, nullable=False),
)


def create_engine(database_url: str) -> AsyncEngine:
    url = make_url(database_url)
    backend = url.get_backend_name()
    if backend == "sqlite":
        if url.database not in (None, "", ":memory:"):
            Path(url.database).parent.mkdir(parents=True, exist_ok=True)
        engine = create_async_engine(url)
        event.listen(engine.sync_engine, "connect", _sqlite_pragmas)
        return engine
    if backend == "postgresql":
        # date_trunc() buckets by the session time zone; reports are defined in UTC.
        return create_async_engine(
            url,
            pool_pre_ping=True,
            connect_args={"server_settings": {"timezone": "UTC"}},
        )
    raise ValueError(f"unsupported database backend: {backend} (use sqlite or postgresql)")


def _sqlite_pragmas(dbapi_connection: Any, _: Any) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


def alembic_config(database_url: str) -> Config:
    config = Config()
    config.set_main_option("script_location", "tollbooth:migrations")
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def run_migrations(database_url: str) -> None:
    """Synchronous; call via asyncio.to_thread from async code (env.py runs its own event loop)."""
    command.upgrade(alembic_config(database_url), "head")
