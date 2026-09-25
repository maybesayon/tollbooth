from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TOLLBOOTH_", env_file=".env", extra="ignore")

    encryption_key: SecretStr
    admin_token: SecretStr | None = None
    """Break-glass admin credential for scripts and first-time setup; optional once users exist."""
    session_ttl_hours: float = 168.0
    cookie_secure: bool | None = None
    """Mark the session cookie Secure; unset means secure whenever the request came over HTTPS."""
    database_url: str = "sqlite+aiosqlite:///./data/tollbooth.db"
    auto_migrate: bool = True
    pricing_file: Path = Path("pricing.toml")
    openai_base_url: str = "https://api.openai.com"
    anthropic_base_url: str = "https://api.anthropic.com"
    upstream_connect_timeout: float = 10.0
    upstream_read_timeout: float = 600.0
    dashboard_dir: Path | None = None
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
