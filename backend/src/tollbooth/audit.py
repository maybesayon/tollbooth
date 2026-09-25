import logging
from datetime import UTC, datetime

from tollbooth.auth import Principal
from tollbooth.domain import AuditEvent
from tollbooth.repositories.base import AuditRepository
from tollbooth.security import new_id

logger = logging.getLogger("tollbooth.audit")


async def record(
    audit: AuditRepository,
    principal: Principal | None,
    action: str,
    target_type: str | None = None,
    target_id: str | None = None,
    details: dict[str, object] | None = None,
    actor_label: str | None = None,
) -> None:
    """Best effort: a failed audit write is logged but never undoes or blocks the action."""
    event = AuditEvent(
        id=new_id(),
        created_at=datetime.now(UTC),
        actor_type=principal.via.value if principal else "anonymous",
        actor_id=principal.user.id if principal and principal.user else None,
        actor_label=actor_label or (principal.label if principal else "anonymous"),
        action=action,
        target_type=target_type,
        target_id=target_id,
        details=details or {},
    )
    try:
        await audit.record(event)
    except Exception:
        logger.exception("failed to write audit event %s (%s)", event.id, action)


def changes(before: dict[str, object], after: dict[str, object]) -> dict[str, dict[str, object]]:
    """The fields that differ, as {"field": {"from": old, "to": new}}."""
    return {k: {"from": before[k], "to": after[k]} for k in before if before[k] != after.get(k)}
