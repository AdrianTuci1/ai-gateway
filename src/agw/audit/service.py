from __future__ import annotations

import uuid
from typing import Any

from agw.db.models import AuditEvent
from agw.store.base import Store


async def record(
    store: Store,
    *,
    workspace_id: uuid.UUID | None,
    actor_type: str,
    actor_id: uuid.UUID | None,
    action: str,
    trace_id: str,
    resource_type: str | None = None,
    resource_id: str | None = None,
    decision: str | None = None,
    reason: str | None = None,
    meta: dict[str, Any] | None = None,
) -> AuditEvent:
    return await store.record_audit(
        workspace_id=workspace_id,
        actor_type=actor_type,
        actor_id=actor_id,
        action=action,
        trace_id=trace_id,
        resource_type=resource_type,
        resource_id=resource_id,
        decision=decision,
        reason=reason,
        meta=meta or {},
    )
