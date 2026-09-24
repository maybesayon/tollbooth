from dataclasses import dataclass

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine

from tollbooth.alerts import AlertManager
from tollbooth.budgets import BudgetTracker
from tollbooth.pricing import PricingTable
from tollbooth.repositories.base import (
    AlertRepository,
    BudgetRepository,
    ChannelRepository,
    CredentialRepository,
    KeyRepository,
    LedgerRepository,
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
