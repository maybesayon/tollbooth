from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TOLLBOOTH_", env_file=".env", extra="ignore")

    admin_token: SecretStr
    encryption_key: SecretStr
    database_url: str = "sqlite+aiosqlite:///./data/tollbooth.db"
    auto_migrate: bool = True
    pricing_file: Path = Path("pricing.toml")
    openai_base_url: str = "https://api.openai.com"
    anthropic_base_url: str = "https://api.anthropic.com"
    upstream_connect_timeout: float = 10.0
    upstream_read_timeout: float = 600.0
