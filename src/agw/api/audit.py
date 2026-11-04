from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query, Response

from agw.api.deps import (
    get_principal,
    get_store,
    get_workspace,
    require_permission,
)
from agw.api.schemas import AuditOut
from agw.core.time import as_naive_utc, utcnow
from agw.db.models import AuditEvent, Workspace
from agw.policy.engine import Principal
from agw.store.base import Store

router = APIRouter()


@router.get("/v1/workspaces/{ws}/audit", response_model=list[AuditOut])
async def list_audit(
    response: Response,
    workspace: Workspace = Depends(get_workspace),
    principal: Principal = Depends(get_principal),
    store: Store = Depends(get_store),
    since: datetime | None = Query(default=None),
    decision: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    as_of: datetime | None = Query(default=None),
) -> list[AuditEvent]:
    require_permission(principal, "audit:read")
    if as_of is not None:
        snapshot = as_naive_utc(as_of)
    else:
        newest = await store.list_audit(
            workspace.id,
            since=since,
            decision=decision,
            limit=1,
        )
        snapshot = newest[0].created_at if newest else utcnow()
    total = await store.count_audit(
        workspace.id,
        since=since,
        decision=decision,
        as_of=snapshot,
    )
    events = await store.list_audit(
        workspace.id,
        since=since,
        decision=decision,
        limit=limit,
        offset=(page - 1) * limit,
        as_of=snapshot,
    )
    response.headers["X-Total-Count"] = str(total)
    response.headers["X-Page"] = str(page)
    response.headers["X-Page-Size"] = str(limit)
    response.headers["X-Snapshot"] = snapshot.isoformat()
    return events
