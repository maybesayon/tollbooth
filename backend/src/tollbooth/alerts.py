import asyncio
import hashlib
import hmac
import json
import logging
import secrets
import time
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

import httpx

from tollbooth.budgets import BudgetUsage, Clock, utcnow
from tollbooth.cost import nanousd_to_usd
from tollbooth.domain import (
    Alert,
    Budget,
    BudgetPeriod,
    BudgetScope,
    Channel,
    ChannelType,
    Delivery,
    DeliveryStatus,
    Enforcement,
)
from tollbooth.repositories.base import AlertRepository, ChannelRepository
from tollbooth.security import SecretBox, new_id

logger = logging.getLogger("tollbooth.alerts")

SIGNATURE_HEADER = "x-tollbooth-signature"
TIMESTAMP_HEADER = "x-tollbooth-timestamp"
EVENT_HEADER = "x-tollbooth-event"


def new_signing_secret() -> str:
    return "whsec_" + secrets.token_urlsafe(32)


def url_hint(url: str) -> str:
    """Enough to recognize a channel without revealing the secret path of e.g. a Slack URL."""
    return urlsplit(url).netloc


def sign(secret: str, timestamp: str, body: bytes) -> str:
    """HMAC-SHA256 over "{timestamp}.{body}"; receivers should reject stale timestamps."""
    mac = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256)
    return f"v1={mac.hexdigest()}"


@dataclass(frozen=True)
class SendResult:
    ok: bool
    status_code: int | None = None
    error: str | None = None


class AlertManager:
    """Turns threshold crossings into alerts (once per budget, period, and threshold) and
    delivers them to the budget's channels in the background, with retries."""

    def __init__(
        self,
        alerts: AlertRepository,
        channels: ChannelRepository,
        secret_box: SecretBox,
        http: httpx.AsyncClient,
        clock: Clock = utcnow,
        retry_delays: Sequence[float] = (1.0, 5.0, 25.0),
    ) -> None:
        self._alerts = alerts
        self._channels = channels
        self._secret_box = secret_box
        self._http = http
        self._clock = clock
        self._retry_delays = tuple(retry_delays)
        self._fired: set[tuple[str, datetime, int]] = set()
        self._tasks: set[asyncio.Task[None]] = set()

    async def evaluate(self, usages: Sequence[BudgetUsage]) -> list[Alert]:
        """Create alerts for newly crossed thresholds and schedule their delivery.

        When one evaluation crosses several thresholds of a budget at once (a budget created
        mid-period, or one expensive request), only the highest is sent; the others are recorded
        with skipped deliveries so channels get one message, not a burst.
        """
        created: list[Alert] = []
        for usage in usages:
            fresh: list[Alert] = []
            for threshold in usage.budget.thresholds:
                marker = (usage.budget.id, usage.period_start, threshold)
                if marker in self._fired or not usage.crossed(threshold):
                    continue
                if len(self._fired) > 10_000:
                    self._fired.clear()
                self._fired.add(marker)
                alert = Alert(
                    id=new_id(),
                    budget_id=usage.budget.id,
                    budget_name=usage.budget.name,
                    threshold=threshold,
                    period_start=usage.period_start,
                    period_end=usage.period_end,
                    spend_nanousd=usage.spend_nanousd,
                    limit_nanousd=usage.budget.limit_nanousd,
                    created_at=self._clock(),
                )
                if await self._alerts.create_if_absent(alert):
                    logger.info(
                        "budget %s crossed %s%% (alert %s)", alert.budget_id, threshold, alert.id
                    )
                    fresh.append(alert)
            if fresh:
                highest = max(fresh, key=lambda a: a.threshold)
                for alert in fresh:
                    if alert is not highest:
                        await self._skip(alert, usage.budget, superseded_by=highest.threshold)
                self._spawn(self._deliver_all(highest, usage.budget))
                created.extend(fresh)
        return created

    async def send_test(self, channel: Channel) -> SendResult:
        message = f"Test notification from Tollbooth for channel '{channel.name}'."
        payload: dict[str, Any] = (
            {"text": message}
            if channel.type is ChannelType.SLACK
            else {"type": "test", "message": message, "sent_at": _iso(self._clock())}
        )
        return await self._send(channel, "test", payload)

    async def drain(self) -> None:
        """Wait for scheduled deliveries (tests and graceful shutdown)."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def aclose(self, grace_seconds: float = 5.0) -> None:
        """Give in-flight deliveries a moment to finish, then cancel the rest."""
        if not self._tasks:
            return
        _, pending = await asyncio.wait(list(self._tasks), timeout=grace_seconds)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

    def _spawn(self, coro: Any) -> None:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _deliver_all(self, alert: Alert, budget: Budget) -> None:
        for channel_id in budget.channel_ids:
            channel = await self._channels.get(channel_id)
            if channel is None:
                continue
            try:
                await self._deliver(alert, budget, channel)
            except Exception:
                logger.exception("delivery of alert %s to %s crashed", alert.id, channel.id)

    async def _skip(self, alert: Alert, budget: Budget, superseded_by: int) -> None:
        for channel_id in budget.channel_ids:
            channel = await self._channels.get(channel_id)
            if channel is None:
                continue
            await self._alerts.save_delivery(
                Delivery(
                    id=new_id(),
                    alert_id=alert.id,
                    channel_id=channel.id,
                    channel_name=channel.name,
                    status=DeliveryStatus.SKIPPED,
                    attempts=0,
                    last_error=f"superseded by the {superseded_by}% alert",
                    updated_at=self._clock(),
                )
            )

    async def _deliver(self, alert: Alert, budget: Budget, channel: Channel) -> None:
        delivery = Delivery(
            id=new_id(),
            alert_id=alert.id,
            channel_id=channel.id,
            channel_name=channel.name,
            status=DeliveryStatus.PENDING,
            attempts=0,
            last_error=None,
            updated_at=self._clock(),
        )
        await self._alerts.save_delivery(delivery)
        payload = (
            slack_message(alert, budget)
            if channel.type is ChannelType.SLACK
            else webhook_payload(alert, budget)
        )
        delays = (0.0, *self._retry_delays)
        for attempt, delay in enumerate(delays, start=1):
            if delay:
                await asyncio.sleep(delay)
            result = await self._send(channel, "budget.threshold_crossed", payload)
            done = result.ok or attempt == len(delays)
            status = (
                DeliveryStatus.DELIVERED
                if result.ok
                else DeliveryStatus.FAILED
                if done
                else DeliveryStatus.PENDING
            )
            delivery = replace(
                delivery,
                status=status,
                attempts=attempt,
                last_error=result.error,
                updated_at=self._clock(),
            )
            await self._alerts.save_delivery(delivery)
            if done:
                if not result.ok:
                    logger.warning(
                        "alert %s to channel %s failed after %s attempts: %s",
                        alert.id,
                        channel.id,
                        attempt,
                        result.error,
                    )
                return

    async def _send(self, channel: Channel, event: str, payload: dict[str, Any]) -> SendResult:
        stored = await self._channels.get_secrets(channel.id)
        if stored is None:
            return SendResult(False, error="channel no longer exists")
        encrypted_url, encrypted_secret = stored
        url = self._secret_box.decrypt(encrypted_url)
        body = json.dumps(payload, separators=(",", ":")).encode()
        headers = {"content-type": "application/json", "user-agent": "Tollbooth-Alerts"}
        if channel.type is ChannelType.WEBHOOK:
            timestamp = str(int(time.time()))
            headers[EVENT_HEADER] = event
            headers[TIMESTAMP_HEADER] = timestamp
            if encrypted_secret is not None:
                secret = self._secret_box.decrypt(encrypted_secret)
                headers[SIGNATURE_HEADER] = sign(secret, timestamp, body)
        try:
            response = await self._http.post(url, content=body, headers=headers)
        except httpx.HTTPError as e:
            # Only the type: messages can include the URL, which for Slack is itself a secret.
            return SendResult(False, error=type(e).__name__)
        if response.is_success:
            return SendResult(True, status_code=response.status_code)
        return SendResult(
            False, status_code=response.status_code, error=f"HTTP {response.status_code}"
        )


def webhook_payload(alert: Alert, budget: Budget) -> dict[str, Any]:
    return {
        "type": "budget.threshold_crossed",
        "alert_id": alert.id,
        "created_at": _iso(alert.created_at),
        "threshold_percent": alert.threshold,
        "spend_usd": _usd(alert.spend_nanousd),
        "limit_usd": _usd(alert.limit_nanousd),
        "period": {
            "type": budget.period.value,
            "start": _iso(alert.period_start),
            "end": _iso(alert.period_end),
        },
        "budget": {
            "id": budget.id,
            "name": budget.name,
            "scope": {"type": budget.scope.value, "value": budget.scope_value},
            "enforcement": budget.enforcement.value,
        },
    }


def slack_message(alert: Alert, budget: Budget) -> dict[str, Any]:
    scope = {
        BudgetScope.GLOBAL: "all traffic",
        BudgetScope.TEAM: f"team {budget.scope_value}",
        BudgetScope.KEY: f"key {budget.scope_value}",
    }[budget.scope]
    text = (
        f"Tollbooth budget *{budget.name}* ({scope}) reached {alert.threshold}% of its "
        f"{_ADJECTIVE[budget.period]} limit: ${_usd(alert.spend_nanousd)} of "
        f"${_usd(alert.limit_nanousd)}."
    )
    if budget.enforcement is Enforcement.HARD and alert.spend_nanousd >= alert.limit_nanousd:
        text += f" Requests are blocked until {_iso(alert.period_end)}."
    return {"text": text}


_ADJECTIVE = {BudgetPeriod.DAY: "daily", BudgetPeriod.WEEK: "weekly", BudgetPeriod.MONTH: "monthly"}


def _usd(nanousd: int) -> str:
    return format(nanousd_to_usd(nanousd), "f")


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")
