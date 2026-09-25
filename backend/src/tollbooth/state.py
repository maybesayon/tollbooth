from dataclasses import dataclass

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine

from tollbooth.alerts import AlertManager
from tollbooth.auth import LoginThrottle
from tollbooth.budgets import BudgetTracker
from tollbooth.pricing import PricingTable
from tollbooth.repositories.base import (
    AlertRepository,
    ApiTokenRepository,
    AuditRepository,
    BudgetRepository,
    ChannelRepository,
    CredentialRepository,
    KeyRepository,
    LedgerRepository,
    SessionRepository,
    UserRepository,
)
from tollbooth.security import SecretBox
from tollbooth.settings import Settings


@dataclass(frozen=True)
class AppState:
    settings: Settings
    pricing: PricingTable
    engine: AsyncEngine
    upstream: httpx.AsyncClient
    secret_box: SecretBox
    credentials: CredentialRepository
    keys: KeyRepository
    ledger: LedgerRepository
    budgets: BudgetRepository
    budget_tracker: BudgetTracker
    channels: ChannelRepository
    alerts: AlertRepository
    alert_manager: AlertManager
    users: UserRepository
    sessions: SessionRepository
    api_tokens: ApiTokenRepository
    login_throttle: LoginThrottle
    audit: AuditRepository
