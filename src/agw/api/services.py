from __future__ import annotations

import hashlib
import json
import uuid

from fastapi import APIRouter, Depends, Query, Request

from agw.adapters.mcp import MCPHTTPClient, UpstreamError
from agw.adapters.openapi import OpenAPIDiscoveryError, fetch_openapi, openapi_tools
from agw.api.deps import (
    ensure_self_or_admin,
    get_principal,
    get_store,
    get_workspace,
    require_agent,
    require_permission,
)
from agw.api.schemas import (
    CatalogResponse,
    CatalogTool,
    DiscoverResponse,
    ServiceCreate,
    ServiceOut,
    ServiceUpdate,
    ToolOut,
)
from agw.audit.service import record
from agw.core.errors import ApiError, feature_unavailable, not_found
from agw.core.pagination import decode_cursor, encode_cursor, query_fingerprint
from agw.core.runtime import require_feature
from agw.core.time import utcnow
from agw.db.models import ServiceTool, UpstreamService, Workspace
from agw.policy.engine import Principal
from agw.store.base import Store

router = APIRouter()


@router.get("/v1/workspaces/{ws}/services", response_model=list[ServiceOut])
async def list_services(
    workspace: Workspace = Depends(get_workspace),
    principal: Principal = Depends(get_principal),
    store: Store = Depends(get_store),
) -> list[UpstreamService]:
    require_permission(principal, "service:read")
    return await store.list_services(workspace.id)


@router.post("/v1/workspaces/{ws}/services", response_model=ServiceOut, status_code=201)
async def create_service(
    body: ServiceCreate,
    request: Request,
    workspace: Workspace = Depends(get_workspace),
    principal: Principal = Depends(get_principal),
    store: Store = Depends(get_store),
) -> UpstreamService:
    require_permission(principal, "service:create")
    if body.kind == "mcp_stdio":
        require_feature(request.app.state.settings, "stdio")
    exists = any(
        service.name == body.name for service in await store.list_services(workspace.id)
    )
    if exists:
        raise ApiError(409, "conflict", "service name already exists")
    if body.kind in {"mcp_http", "a2a"} and not body.endpoint:
        raise ApiError(422, "invalid_request", "endpoint is required for this service kind")
    if body.resource_group_id is not None:
        group = await store.get_resource_group(body.resource_group_id)
        if group is None or group.workspace_id != workspace.id:
            raise not_found("resource group")
    service = await store.create_service(
        workspace_id=workspace.id,
        name=body.name,
        kind=body.kind,
        endpoint=body.endpoint,
        auth_type=body.auth_type,
        credential_policy=body.credential_policy,
        created_by=principal.id,
    )
    if body.resource_group_id is not None:
        service.resource_group_id = body.resource_group_id
        await store.save_service(service)
    await record(
        store,
        workspace_id=workspace.id,
        actor_type=principal.kind,
        actor_id=principal.id,
        action="service.created",
        resource_type="upstream_service",
        resource_id=str(service.id),
        trace_id=request.state.trace_id,
    )
    await store.commit()
    return service


@router.get("/v1/workspaces/{ws}/services/{service_id}", response_model=ServiceOut)
async def get_service(
    service_id: uuid.UUID,
    workspace: Workspace = Depends(get_workspace),
    principal: Principal = Depends(get_principal),
    store: Store = Depends(get_store),
) -> UpstreamService:
    require_permission(principal, "service:read")
    service = await store.get_service(service_id)
    if service is None or service.workspace_id != workspace.id:
        raise not_found("service")
    return service


@router.patch("/v1/workspaces/{ws}/services/{service_id}", response_model=ServiceOut)
async def update_service(
    service_id: uuid.UUID,
    body: ServiceUpdate,
    request: Request,
    workspace: Workspace = Depends(get_workspace),
    principal: Principal = Depends(get_principal),
    store: Store = Depends(get_store),
) -> UpstreamService:
    require_permission(principal, "service:update")
    service = await store.get_service(service_id)
    if service is None or service.workspace_id != workspace.id:
        raise not_found("service")
    if body.name is not None and body.name != service.name:
        duplicate = any(
            other.name == body.name and other.id != service.id
            for other in await store.list_services(workspace.id)
        )
        if duplicate:
            raise ApiError(409, "conflict", "service name already exists")
        service.name = body.name
    if body.endpoint is not None:
        service.endpoint = body.endpoint
    if body.auth_type is not None:
        service.auth_type = body.auth_type
    if body.credential_policy is not None:
        service.credential_policy = body.credential_policy
    if body.status is not None:
        service.status = body.status
    if "resource_group_id" in body.model_fields_set:
        if body.resource_group_id is not None:
            group = await store.get_resource_group(body.resource_group_id)
            if group is None or group.workspace_id != workspace.id:
                raise not_found("resource group")
        service.resource_group_id = body.resource_group_id
    await store.save_service(service)
    await record(
        store,
        workspace_id=workspace.id,
        actor_type=principal.kind,
        actor_id=principal.id,
        action="service.updated",
        resource_type="upstream_service",
        resource_id=str(service.id),
        trace_id=request.state.trace_id,
    )
    await store.commit()
    return service


@router.delete("/v1/workspaces/{ws}/services/{service_id}", status_code=204)
async def delete_service(
    service_id: uuid.UUID,
    request: Request,
    workspace: Workspace = Depends(get_workspace),
    principal: Principal = Depends(get_principal),
    store: Store = Depends(get_store),
) -> None:
    require_permission(principal, "service:delete")
    service = await store.get_service(service_id)
    if service is None or service.workspace_id != workspace.id:
        raise not_found("service")
    service.status = "disabled"
    await store.save_service(service)
    await store.revoke_grants_for_service(service.id)
    await record(
        store,
        workspace_id=workspace.id,
        actor_type=principal.kind,
        actor_id=principal.id,
        action="service.disabled",
        resource_type="upstream_service",
        resource_id=str(service.id),
        trace_id=request.state.trace_id,
    )
    await store.commit()


@router.post(
    "/v1/workspaces/{ws}/services/{service_id}/discover",
    response_model=DiscoverResponse,
)
async def discover_service(
    service_id: uuid.UUID,
    request: Request,
    workspace: Workspace = Depends(get_workspace),
    principal: Principal = Depends(get_principal),
    store: Store = Depends(get_store),
) -> DiscoverResponse:
    require_permission(principal, "service:discover")
    service = await store.get_service(service_id)
    if service is None or service.workspace_id != workspace.id:
        raise not_found("service")
    if service.kind not in {"mcp_http", "http"}:
        raise feature_unavailable("discovery for this service kind")
    if service.auth_type != "none":
        raise ApiError(
            409,
            "connection_required",
            "this service requires a user connection before discovery",
        )
    if not service.endpoint:
        raise ApiError(422, "invalid_request", "service has no endpoint")
    if service.kind == "http":
        try:
            document = await fetch_openapi(service.endpoint)
        except OpenAPIDiscoveryError as exc:
            raise ApiError(502, "upstream_error", str(exc)) from exc
        remote_tools = openapi_tools(document)
        runtime_requirements = {
            "streaming": False,
            "session": False,
            "stdio": False,
            "push": False,
        }
    else:
        client = MCPHTTPClient(service.endpoint, timeout=10)
        try:
            remote_tools = await client.list_tools()
        except UpstreamError as exc:
            raise ApiError(
                502,
                "upstream_error",
                str(exc),
                detail={"retryable": exc.retryable},
            ) from exc
        runtime_requirements = {
            "streaming": False,
            "session": bool(client.session_id),
            "stdio": False,
            "push": False,
        }

    existing = {tool.name: tool for tool in await store.list_tools(service.id)}
    for remote in remote_tools:
        name = remote.get("name")
        if not name:
            continue
        schema = remote.get("inputSchema") or remote.get("input_schema") or {}
        description = remote.get("description")
        annotations = remote.get("annotations") or {}
        definition_hash = hashlib.sha256(
            json.dumps(remote, sort_keys=True).encode()
        ).hexdigest()
        tool = existing.get(name)
        if tool is None:
            tool = ServiceTool(
                service_id=service.id,
                name=name,
                description=description,
                input_schema=schema,
                annotations=annotations,
                definition_hash=definition_hash,
            )
            existing[name] = tool
        else:
            tool.description = description
            tool.input_schema = schema
            tool.annotations = annotations
            tool.definition_hash = definition_hash
            tool.last_seen_at = utcnow()
        await store.save_tool(tool)

    service.manifest_hash = hashlib.sha256(
        json.dumps(remote_tools, sort_keys=True).encode()
    ).hexdigest()
    service.manifest_synced_at = utcnow()
    service.runtime_requirements = runtime_requirements
    await store.save_service(service)
    await record(
        store,
        workspace_id=workspace.id,
        actor_type=principal.kind,
        actor_id=principal.id,
        action="service.discovered",
        resource_type="upstream_service",
        resource_id=str(service.id),
        trace_id=request.state.trace_id,
        meta={"tools": len(remote_tools)},
    )
    await store.commit()
    return DiscoverResponse(
        service=ServiceOut.model_validate(service),
        tools=[ToolOut.model_validate(tool) for tool in existing.values()],
    )


@router.get(
    "/v1/workspaces/{ws}/services/{service_id}/tools", response_model=list[ToolOut]
)
async def list_service_tools(
    service_id: uuid.UUID,
    workspace: Workspace = Depends(get_workspace),
    principal: Principal = Depends(get_principal),
    store: Store = Depends(get_store),
) -> list[ServiceTool]:
    require_permission(principal, "service:read")
    service = await store.get_service(service_id)
    if service is None or service.workspace_id != workspace.id:
        raise not_found("service")
    return await store.list_tools(service.id)


@router.get("/v1/catalog", response_model=CatalogResponse)
async def catalog(
    request: Request,
    q: str | None = Query(default=None, max_length=200),
    kind: str | None = Query(default=None),
    granted: bool | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = Query(default=None),
    principal: Principal = Depends(get_principal),
    store: Store = Depends(get_store),
) -> CatalogResponse:
    require_permission(principal, "service:discover")
    settings = request.app.state.settings
    filters = {"kind": kind, "granted": granted}
    fingerprint = query_fingerprint(q, filters)
    offset = 0
    if cursor:
        payload = decode_cursor(cursor, settings.session_secret)
        if payload.get("qh") != fingerprint:
            raise ApiError(400, "cursor_query_mismatch", "filters changed between pages")
        offset = int(payload.get("o", 0))

    rows = await store.list_catalog(principal.workspace_id, kind)

    grants_by_service: dict[uuid.UUID, set[str]] = {}
    if principal.kind == "agent" and principal.agent_id:
        for grant in await store.list_active_grants(principal.agent_id):
            if grant.expires_at is not None and grant.expires_at <= utcnow():
                continue
            grants_by_service.setdefault(grant.service_id, set()).update(grant.tools or [])

    needle = (q or "").lower()
    items: list[CatalogTool] = []
    for tool, service in rows:
        if needle and not (
            needle in (tool.name or "").lower()
            or needle in (tool.description or "").lower()
            or needle in (service.name or "").lower()
        ):
            continue
        is_granted = tool.name in grants_by_service.get(service.id, set())
        if granted is not None and granted != is_granted:
            continue
        items.append(
            CatalogTool(
                service_id=service.id,
                service_name=service.name,
                name=tool.name,
                description=tool.description,
                input_schema=tool.input_schema,
                granted=is_granted,
            )
        )
    page = items[offset : offset + limit]
    next_cursor = None
    if offset + limit < len(items):
        next_cursor = encode_cursor(
            {"v": 1, "o": offset + limit, "qh": fingerprint}, settings.session_secret
        )
    return CatalogResponse(items=page, next_cursor=next_cursor)


@router.post(
    "/v1/workspaces/{ws}/agents/{agent_id}/connections/{service_id}/authorize"
)
async def authorize_connection(
    agent_id: uuid.UUID,
    service_id: uuid.UUID,
    request: Request,
    workspace: Workspace = Depends(get_workspace),
    principal: Principal = Depends(get_principal),
    store: Store = Depends(get_store),
) -> dict:
    require_permission(principal, "connection:authorize")
    agent = await require_agent(workspace.id, agent_id, store)
    ensure_self_or_admin(principal, agent)
    service = await store.get_service(service_id)
    if service is None or service.workspace_id != workspace.id:
        raise not_found("service")
    if service.auth_type == "none":
        return {"status": "not_required", "service_id": str(service.id)}
    raise feature_unavailable("OAuth connection flow")
