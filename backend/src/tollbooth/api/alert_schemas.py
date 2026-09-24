from datetime import datetime
from typing import Annotated

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field

from tollbooth.api.ledger_schemas import USD
from tollbooth.cost import nanousd_to_usd
from tollbooth.domain import Alert, Channel, ChannelType, Delivery, DeliveryStatus

Name = Annotated[str, Field(min_length=1, max_length=200, pattern=r"\S")]


class ChannelCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name
    type: ChannelType
    url: AnyHttpUrl = Field(description="Stored encrypted; only the host is shown afterwards.")


class ChannelOut(BaseModel):
    id: str
    name: str
    type: ChannelType
    url_hint: str
    created_at: datetime

    @classmethod
    def of(cls, channel: Channel) -> "ChannelOut":
        return cls(
            id=channel.id,
            name=channel.name,
            type=channel.type,
            url_hint=channel.url_hint,
            created_at=channel.created_at,
        )


class ChannelCreated(ChannelOut):
    signing_secret: str | None = Field(
        description="Webhook channels only: verify X-Tollbooth-Signature with it. Shown once."
    )


class ChannelTestResult(BaseModel):
    ok: bool
    status_code: int | None
    error: str | None


class DeliveryOut(BaseModel):
    channel_id: str
    channel_name: str
    status: DeliveryStatus
    attempts: int
    last_error: str | None
    updated_at: datetime

    @classmethod
    def of(cls, delivery: Delivery) -> "DeliveryOut":
        return cls(
            channel_id=delivery.channel_id,
            channel_name=delivery.channel_name,
            status=delivery.status,
            attempts=delivery.attempts,
            last_error=delivery.last_error,
            updated_at=delivery.updated_at,
        )


class AlertOut(BaseModel):
    id: str
    budget_id: str
    budget_name: str
    threshold_percent: int
    spend_usd: USD
    limit_usd: USD
    period_start: datetime
    period_end: datetime
    created_at: datetime
    deliveries: list[DeliveryOut]

    @classmethod
    def of(cls, alert: Alert) -> "AlertOut":
        return cls(
            id=alert.id,
            budget_id=alert.budget_id,
            budget_name=alert.budget_name,
            threshold_percent=alert.threshold,
            spend_usd=nanousd_to_usd(alert.spend_nanousd),
            limit_usd=nanousd_to_usd(alert.limit_nanousd),
            period_start=alert.period_start,
            period_end=alert.period_end,
            created_at=alert.created_at,
            deliveries=[DeliveryOut.of(d) for d in alert.deliveries],
        )
