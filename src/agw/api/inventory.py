from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response

from agw.api.deps import (
    get_principal,
    get_store,
    get_workspace,
    require_permission,
)
from agw.api.schemas import (
    GroupResourcesPut,
    IdentityOut,
    InventoryOut,
    ResourceGroupCreate,
    ResourceGroupOut,
    ResourceGroupUpdate,
    ResourceItem,
    TraceDetailOut,
    TraceSpanOut,
    TraceSummaryOut,
)
from agw.audit.service import record
from agw.core.errors import ApiError, not_found
from agw.core.time import as_naive_utc, utcnow
from agw.db.models import (
    Agent,
    ResourceGroup,
    TraceSpan,
    UpstreamService,
    Workspace,
)
from agw.policy.engine import Principal
from agw.store.base import Store

router = APIRouter()


def _service_item(service: UpstreamService, tool_count: int) -> ResourceItem:
    return ResourceItem(
        type="service",
        id=service.id,
        name=service.name,
        kind=service.kind,
        status=service.status,
        group_id=service.resource_group_id,
        detail=service.endpoint,
        children=tool_count,
    )


def _agent_item(agent: Agent, grant_count: int) -> ResourceItem:
    return ResourceItem(
        type="agent",
        id=agent.id,
        name=agent.name,
        kind=agent.kind,
        status=agent.status,
        group_id=agent.resource_group_id,
        detail=agent.slug,
        children=grant_count,
    )


async def _resource_items(
    store: Store, workspace_id: uuid.UUID
) -> list[ResourceItem]:
    items: list[ResourceItem] = []
    for service in await store.list_services(workspace_id):
        items.append(_service_item(service, len(await store.list_tools(service.id))))
    for agent in await store.list_agents(workspace_id):
        if agent.status == "pending":
            continue
        items.append(
            _agent_item(agent, len(await store.list_active_grants(agent.id)))
        )
    return items


def _group_out(group: ResourceGroup, items: list[ResourceItem]) -> ResourceGroupOut:
    members = [item for item in items if item.group_id == group.id]
    return ResourceGroupOut(
        id=group.id,
        name=group.name,
        kind=group.kind,
        description=group.description,
        created_at=group.created_at,
        resources=members,
    )


@router.get("/v1/workspaces/{ws}/inventory", response_model=InventoryOut)
async def inventory(
    workspace: Workspace = Depends(get_workspace),
    principal: Principal = Depends(get_principal),
    store: Store = Depends(get_store),
) -> InventoryOut:
    require_permission(principal, "workspace:read")
    items = await _resource_items(store, workspace.id)
    groups = [
        _group_out(group, items)
        for group in await store.list_resource_groups(workspace.id)
    ]
    known = {group.id for group in groups}
    standalone = [
        item for item in items if item.group_id is None or item.group_id not in known
    ]
    return InventoryOut(
        groups=groups,
        standalone=standalone,
        counts={
            "groups": len(groups),
            "services": sum(1 for item in items if item.type == "service"),
            "agents": sum(1 for item in items if item.type == "agent"),
        },
    )


@router.post(
    "/v1/workspaces/{ws}/resource-groups",
    response_model=ResourceGroupOut,
    status_code=201,
)
async def create_group(
    body: ResourceGroupCreate,
    request: Request,
    workspace: Workspace = Depends(get_workspace),
    principal: Principal = Depends(get_principal),
    store: Store = Depends(get_store),
) -> ResourceGroupOut:
    require_permission(principal, "workspace:update")
    existing = {group.name for group in await store.list_resource_groups(workspace.id)}
    if body.name in existing:
        raise ApiError(409, "conflict", "a resource group with this name exists")
    group = await store.create_resource_group(
        workspace_id=workspace.id,
        name=body.name,
        kind=body.kind,
        description=body.description,
    )
    await record(
        store,
        workspace_id=workspace.id,
        actor_type=principal.kind,
        actor_id=principal.id,
        action="resource_group.created",
        resource_type="resource_group",
        resource_id=str(group.id),
        trace_id=request.state.trace_id,
        meta={"name": group.name},
    )
    await store.commit()
    return _group_out(group, [])


async def _require_group(
    store: Store, workspace: Workspace, group_id: uuid.UUID
) -> ResourceGroup:
    group = await store.get_resource_group(group_id)
    if group is None or group.workspace_id != workspace.id:
        raise not_found("resource group")
    return group


@router.patch(
    "/v1/workspaces/{ws}/resource-groups/{group_id}",
    response_model=ResourceGroupOut,
)
async def update_group(
    group_id: uuid.UUID,
    body: ResourceGroupUpdate,
    request: Request,
    workspace: Workspace = Depends(get_workspace),
    principal: Principal = Depends(get_principal),
    store: Store = Depends(get_store),
) -> ResourceGroupOut:
    require_permission(principal, "workspace:update")
    group = await _require_group(store, workspace, group_id)
    if body.name is not None:
        taken = {
            other.name
            for other in await store.list_resource_groups(workspace.id)
            if other.id != group.id
        }
        if body.name in taken:
            raise ApiError(409, "conflict", "a resource group with this name exists")
        group.name = body.name
    if body.kind is not None:
        group.kind = body.kind
    if "description" in body.model_fields_set:
        group.description = body.description
    await store.save_resource_group(group)
    await record(
        store,
        workspace_id=workspace.id,
        actor_type=principal.kind,
        actor_id=principal.id,
        action="resource_group.updated",
        resource_type="resource_group",
        resource_id=str(group.id),
        trace_id=request.state.trace_id,
    )
    await store.commit()
    return _group_out(group, await _resource_items(store, workspace.id))


@router.delete("/v1/workspaces/{ws}/resource-groups/{group_id}", status_code=204)
async def delete_group(
    group_id: uuid.UUID,
    request: Request,
    workspace: Workspace = Depends(get_workspace),
    principal: Principal = Depends(get_principal),
    store: Store = Depends(get_store),
) -> None:
    require_permission(principal, "workspace:update")
    group = await _require_group(store, workspace, group_id)
    for item in await _resource_items(store, workspace.id):
        if item.group_id == group.id:
            if item.type == "service":
                service = await store.get_service(item.id)
                if service is not None:
                    service.resource_group_id = None
                    await store.save_service(service)
            else:
                agent = await store.get_agent(item.id)
                if agent is not None:
                    agent.resource_group_id = None
                    await store.save_agent(agent)
    await store.delete_resource_group(group)
    await record(
        store,
        workspace_id=workspace.id,
        actor_type=principal.kind,
        actor_id=principal.id,
        action="resource_group.deleted",
        resource_type="resource_group",
        resource_id=str(group.id),
        trace_id=request.state.trace_id,
        meta={"name": group.name},
    )
    await store.commit()


@router.put(
    "/v1/workspaces/{ws}/resource-groups/{group_id}/resources",
    response_model=ResourceGroupOut,
)
async def set_group_resources(
    group_id: uuid.UUID,
    body: GroupResourcesPut,
    request: Request,
    workspace: Workspace = Depends(get_workspace),
    principal: Principal = Depends(get_principal),
    store: Store = Depends(get_store),
) -> ResourceGroupOut:
    require_permission(principal, "workspace:update")
    group = await _require_group(store, workspace, group_id)
    wanted = {(ref.type, ref.id) for ref in body.resources}
    if len(wanted) != len(body.resources):
        raise ApiError(400, "invalid_request", "duplicate resources in the request")

    items = await _resource_items(store, workspace.id)
    known = {(item.type, item.id) for item in items}
    unknown = wanted - known
    if unknown:
        raise ApiError(400, "invalid_request", "resource does not belong to this workspace")

    for item in items:
        if item.type == "service":
            service = await store.get_service(item.id)
            if service is None:
                continue
            target = group.id if ("service", item.id) in wanted else (
                None if service.resource_group_id == group.id else service.resource_group_id
            )
            if service.resource_group_id != target:
                service.resource_group_id = target
                await store.save_service(service)
        else:
            agent = await store.get_agent(item.id)
            if agent is None:
                continue
            target = group.id if ("agent", item.id) in wanted else (
                None if agent.resource_group_id == group.id else agent.resource_group_id
            )
            if agent.resource_group_id != target:
                agent.resource_group_id = target
                await store.save_agent(agent)

    await record(
        store,
        workspace_id=workspace.id,
        actor_type=principal.kind,
        actor_id=principal.id,
        action="resource_group.resources_changed",
        resource_type="resource_group",
        resource_id=str(group.id),
        trace_id=request.state.trace_id,
        meta={"count": len(wanted)},
    )
    await store.commit()
    return _group_out(group, await _resource_items(store, workspace.id))


@router.get("/v1/workspaces/{ws}/identities", response_model=list[IdentityOut])
async def identities(
    workspace: Workspace = Depends(get_workspace),
    principal: Principal = Depends(get_principal),
    store: Store = Depends(get_store),
) -> list[IdentityOut]:
    require_permission(principal, "member:read")
    memberships = await store.list_memberships(workspace.id)
    services = {service.id: service for service in await store.list_services(workspace.id)}
    groups = await store.list_resource_groups(workspace.id)

    result: list[IdentityOut] = []
    for membership in memberships:
        if membership.status not in (None, "active"):
            continue
        role = await store.get_role(membership.role_id)
        role_name = role.name if role else "unknown"
        permissions = list(role.permissions) if role else []
        identity = (
            await store.get_identity(membership.identity_id)
            if membership.identity_id is not None
            else None
        )
        identity_fields = {
            "identity_id": membership.identity_id,
            "identity_name": identity.name if identity is not None else None,
            "is_identity_admin": bool(membership.is_identity_admin),
        }
        if membership.principal_type == "user":
            user = await store.get_user(membership.principal_id)
            if user is None:
                continue
            result.append(
                IdentityOut(
                    kind="user",
                    id=user.id,
                    name=user.display_name or user.email,
                    email=user.email,
                    role=role_name,
                    permissions=permissions,
                    status="active",
                    group_count=len(groups),
                    grant_count=0,
                    last_seen_at=user.last_seen_at,
                    **identity_fields,
                )
            )
            continue
        agent = await store.get_agent(membership.principal_id)
        if agent is None:
            continue
        grants = await store.list_active_grants(agent.id)
        granted_groups = {
            services[grant.service_id].resource_group_id
            for grant in grants
            if grant.service_id in services
            and services[grant.service_id].resource_group_id is not None
        }
        result.append(
            IdentityOut(
                kind="agent",
                id=agent.id,
                name=agent.name,
                role=role_name,
                permissions=permissions,
                status=agent.status,
                agent_kind=agent.kind,
                group_count=len(granted_groups),
                grant_count=len(grants),
                last_seen_at=None,
                **identity_fields,
            )
        )
    result.sort(key=lambda identity: (identity.kind, identity.name.lower()))
    return result


@router.get("/v1/workspaces/{ws}/traces", response_model=list[TraceSummaryOut])
async def list_traces(
    response: Response,
    workspace: Workspace = Depends(get_workspace),
    principal: Principal = Depends(get_principal),
    store: Store = Depends(get_store),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    as_of: datetime | None = Query(default=None),
) -> list[TraceSummaryOut]:
    require_permission(principal, "audit:read")
    if as_of is not None:
        snapshot = as_naive_utc(as_of)
    else:
        newest = await store.list_trace_roots(workspace.id, limit=1)
        snapshot = newest[0].started_at if newest else utcnow()
    total = await store.count_trace_roots(workspace.id, as_of=snapshot)
    roots = await store.list_trace_roots(
        workspace.id,
        limit=limit,
        offset=(page - 1) * limit,
        as_of=snapshot,
    )

    summaries: list[TraceSummaryOut] = []
    for root in roots:
        spans = await store.list_trace_spans(workspace.id, root.trace_id)
        summaries.append(
            TraceSummaryOut(
                trace_id=root.trace_id,
                root_name=root.name,
                status="error"
                if any(span.status == "error" for span in spans)
                else root.status,
                duration_ms=root.duration_ms,
                span_count=len(spans),
                actor_type=root.actor_type,
                actor_id=root.actor_id,
                started_at=root.started_at,
            )
        )
    response.headers["X-Total-Count"] = str(total)
    response.headers["X-Page"] = str(page)
    response.headers["X-Page-Size"] = str(limit)
    response.headers["X-Snapshot"] = snapshot.isoformat()
    return summaries


@router.get(
    "/v1/workspaces/{ws}/traces/{trace_id}", response_model=TraceDetailOut
)
async def trace_detail(
    trace_id: str,
    workspace: Workspace = Depends(get_workspace),
    principal: Principal = Depends(get_principal),
    store: Store = Depends(get_store),
) -> TraceDetailOut:
    require_permission(principal, "audit:read")
    spans = await store.list_trace_spans(workspace.id, trace_id)
    if not spans:
        raise not_found("trace")
    return TraceDetailOut(
        trace_id=trace_id,
        spans=[TraceSpanOut.model_validate(span) for span in spans],
    )


__all__: list[Any] = ["router"]
