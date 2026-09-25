from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from tollbooth.api.fields import Text
from tollbooth.api.ledger_schemas import UTCDatetime
from tollbooth.deps import State, require_admin
from tollbooth.domain import AuditEvent

router = APIRouter(prefix="/admin/audit", tags=["audit"], dependencies=[Depends(require_admin)])


class AuditEventOut(BaseModel):
    id: str
    created_at: datetime
    actor_type: str
    actor_id: str | None
    actor_label: str
    action: str
    target_type: str | None
    target_id: str | None
    details: dict[str, Any]

    @classmethod
    def of(cls, event: AuditEvent) -> "AuditEventOut":
        return cls(
            id=event.id,
            created_at=event.created_at,
            actor_type=event.actor_type,
            actor_id=event.actor_id,
            actor_label=event.actor_label,
            action=event.action,
            target_type=event.target_type,
            target_id=event.target_id,
            details=event.details,
        )


@router.get("")
async def list_audit_events(
    state: State,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    before: UTCDatetime = None,
    action: Text | None = None,
    actor_id: Text | None = None,
) -> list[AuditEventOut]:
    """Newest first. Page with `before` = the `created_at` of the last event you received."""
    events = await state.audit.recent(limit, before, action, actor_id)
    return [AuditEventOut.of(e) for e in events]
