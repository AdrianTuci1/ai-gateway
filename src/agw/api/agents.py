from __future__ import annotations

import uuid
from datetime import timedelta, timezone

from fastapi import APIRouter, Depends, Request

from agw.api.auth import _resolve_role, ensure_agent_role, issue_credential
from agw.api.deps import (
    ensure_self_or_admin,
    get_principal,
    get_store,
    get_workspace,
    require_agent,
    require_permission,
)
from agw.api.identity_service import ensure_principal_identity
from agw.api.schemas import (
    AgentCreate,
    AgentCreated,
    AgentOut,
    AgentUpdate,
    ConnectionOut,
    CredentialCreated,
    EnrollmentTokenCreate,
    EnrollmentTokenCreated,
    GrantOut,
    GrantPut,
    WorkspaceCreate,
    WorkspaceOut,
)
from agw.audit.service import record
from agw.core.errors import ApiError, forbidden, not_found
from agw.core.roles import get_builtin_role
from agw.core.security import hash_secret, new_token
from agw.core.time import utcnow
from agw.db.models import Agent, AgentGrant, Workspace
from agw.policy.engine import Principal
from agw.store.base import Store

router = APIRouter()


@router.get("/v1/workspaces", response_model=list[WorkspaceOut])
async def list_workspaces(
    principal: Principal = Depends(get_principal),
    store: Store = Depends(get_store),
) -> list[Workspace]:
    require_permission(principal, "workspace:read")
    if principal.kind == "agent":
        workspace = await store.get_workspace(principal.workspace_id)
        return [workspace] if workspace else []
    return await store.list_workspaces_for_user(principal.id)


@router.post("/v1/workspaces", response_model=WorkspaceOut, status_code=201)
async def create_workspace(
    body: WorkspaceCreate,
    request: Request,
    principal: Principal = Depends(get_principal),
    store: Store = Depends(get_store),
) -> Workspace:
    if principal.kind != "user":
        raise forbidden("forbidden", "agents cannot create workspaces")
    exists = await store.get_workspace_by_slug(body.slug)
    if exists:
        raise ApiError(409, "conflict", "workspace slug already exists")
    workspace = await store.create_workspace(slug=body.slug, name=body.name)
    owner = await get_builtin_role(store, "owner")
    user = await store.get_user(principal.id)
    identity = await store.create_identity(
        workspace_id=workspace.id,
        name=(user.display_name or user.email) if user is not None else "identity",
        status="active",
    )
    await store.create_membership(
        workspace_id=workspace.id,
        principal_type="user",
        principal_id=principal.id,
        role_id=owner.id,
        identity_id=identity.id,
        is_identity_admin=True,
    )
    await record(
        store,
        workspace_id=workspace.id,
        actor_type="user",
        actor_id=principal.id,
        action="workspace.created",
        resource_type="workspace",
        resource_id=str(workspace.id),
        trace_id=request.state.trace_id,
    )
    await store.commit()
    return workspace


def _validate_ceiling_subset(parent: dict, child: dict) -> None:
    parent_services = (parent or {}).get("services")
    if not parent_services:
        return
    child_services = (child or {}).get("services") or {}
    for service_id, entry in child_services.items():
        parent_entry = parent_services.get(service_id)
        if not parent_entry:
            raise forbidden("forbidden", f"ceiling grants unknown service {service_id}")
        if not set(entry.get("tools", [])) <= set(parent_entry.get("tools", [])):
            raise forbidden("forbidden", f"ceiling exceeds parent for service {service_id}")


@router.get("/v1/workspaces/{ws}/agents", response_model=list[AgentOut])
async def list_agents(
    workspace: Workspace = Depends(get_workspace),
    principal: Principal = Depends(get_principal),
    store: Store = Depends(get_store),
) -> list[Agent]:
    require_permission(principal, "agent:read")
    only_agent_id = None
    if principal.kind == "agent" and principal.role != "agent:admin":
        only_agent_id = principal.agent_id
    agents = await store.list_agents(workspace.id, only_agent_id=only_agent_id)
    return [agent for agent in agents if agent.status != "pending"]


@router.post("/v1/workspaces/{ws}/agents", response_model=AgentCreated, status_code=201)
async def create_agent(
    body: AgentCreate,
    request: Request,
    workspace: Workspace = Depends(get_workspace),
    principal: Principal = Depends(get_principal),
    store: Store = Depends(get_store),
) -> AgentCreated:
    require_permission(principal, "agent:create")
    if principal.kind == "agent":
        _validate_ceiling_subset(principal.ceiling, body.ceiling)
    exists = await store.get_agent_by_slug(workspace.id, body.slug)
    if exists:
        raise ApiError(409, "conflict", "agent slug already exists")
    if body.resource_group_id is not None:
        group = await store.get_resource_group(body.resource_group_id)
        if group is None or group.workspace_id != workspace.id:
            raise not_found("resource group")
    role = await _resolve_role(store, workspace.id, body.role)
    ensure_agent_role(role)
    agent = await store.create_agent(
        workspace_id=workspace.id,
        slug=body.slug,
        name=body.name,
        kind=body.kind,
        ceiling=body.ceiling,
        created_by=principal.id,
    )
    if body.resource_group_id is not None:
        agent.resource_group_id = body.resource_group_id
        await store.save_agent(agent)
    creator_name = principal.identity_name
    if creator_name is None:
        if principal.kind == "user":
            creator = await store.get_user(principal.id)
            creator_name = (
                (creator.display_name or creator.email) if creator else "identity"
            )
        else:
            creator = await store.get_agent(principal.id)
            creator_name = (creator.name or creator.slug) if creator else "identity"
    identity = await ensure_principal_identity(
        store,
        workspace_id=workspace.id,
        principal_type=principal.kind,
        principal_id=principal.id,
        name=creator_name,
    )
    is_admin = identity is None
    if identity is None:
        identity = await store.create_identity(
            workspace_id=workspace.id, name=body.name, status="active"
        )
    await store.create_membership(
        workspace_id=workspace.id,
        principal_type="agent",
        principal_id=agent.id,
        role_id=role.id,
        identity_id=identity.id,
        is_identity_admin=is_admin,
    )
    api_key = None
    if body.issue_credential:
        credential = await issue_credential(request, store, agent, "api_key", None)
        api_key = credential["api_key"]
    await record(
        store,
        workspace_id=workspace.id,
        actor_type=principal.kind,
        actor_id=principal.id,
        action="agent.created",
        resource_type="agent",
        resource_id=str(agent.id),
        trace_id=request.state.trace_id,
        meta={"role": role.name},
    )
    await store.commit()
    return AgentCreated(agent=AgentOut.model_validate(agent), api_key=api_key, role=role.name)


@router.get("/v1/workspaces/{ws}/agents/{agent_id}", response_model=AgentOut)
async def get_agent(
    agent_id: uuid.UUID,
    workspace: Workspace = Depends(get_workspace),
    principal: Principal = Depends(get_principal),
    store: Store = Depends(get_store),
) -> Agent:
    require_permission(principal, "agent:read")
    agent = await require_agent(workspace.id, agent_id, store)
    ensure_self_or_admin(principal, agent)
    return agent


@router.patch("/v1/workspaces/{ws}/agents/{agent_id}", response_model=AgentOut)
async def update_agent(
    agent_id: uuid.UUID,
    body: AgentUpdate,
    request: Request,
    workspace: Workspace = Depends(get_workspace),
    principal: Principal = Depends(get_principal),
    store: Store = Depends(get_store),
) -> Agent:
    require_permission(principal, "agent:update")
    agent = await require_agent(workspace.id, agent_id, store)
    ensure_self_or_admin(principal, agent)
    if body.name is not None:
        agent.name = body.name
    if body.slug is not None and body.slug != agent.slug:
        duplicate = await store.get_agent_by_slug(workspace.id, body.slug)
        if duplicate is not None and duplicate.id != agent.id:
            raise ApiError(409, "conflict", "agent slug already exists")
        agent.slug = body.slug
    if body.kind is not None:
        agent.kind = body.kind
    if body.ceiling is not None:
        if principal.kind == "agent":
            _validate_ceiling_subset(principal.ceiling, body.ceiling)
        agent.ceiling = body.ceiling
    if body.status is not None:
        if principal.kind == "agent" and body.status != "active":
            raise forbidden("forbidden", "agents cannot suspend themselves")
        agent.status = body.status
    if "resource_group_id" in body.model_fields_set:
        if body.resource_group_id is not None:
            group = await store.get_resource_group(body.resource_group_id)
            if group is None or group.workspace_id != workspace.id:
                raise not_found("resource group")
        agent.resource_group_id = body.resource_group_id
    await store.save_agent(agent)
    await record(
        store,
        workspace_id=workspace.id,
        actor_type=principal.kind,
        actor_id=principal.id,
        action="agent.updated",
        resource_type="agent",
        resource_id=str(agent.id),
        trace_id=request.state.trace_id,
    )
    await store.commit()
    return agent


@router.delete("/v1/workspaces/{ws}/agents/{agent_id}", status_code=204)
async def delete_agent(
    agent_id: uuid.UUID,
    request: Request,
    workspace: Workspace = Depends(get_workspace),
    principal: Principal = Depends(get_principal),
    store: Store = Depends(get_store),
) -> None:
    require_permission(principal, "agent:delete")
    agent = await require_agent(workspace.id, agent_id, store)
    agent.status = "revoked"
    await store.save_agent(agent)
    await store.revoke_credentials_for_agent(agent.id, utcnow())
    await store.revoke_grants_for_agent(agent.id)
    await record(
        store,
        workspace_id=workspace.id,
        actor_type=principal.kind,
        actor_id=principal.id,
        action="agent.revoked",
        resource_type="agent",
        resource_id=str(agent.id),
        trace_id=request.state.trace_id,
    )
    await store.commit()


@router.post(
    "/v1/workspaces/{ws}/agents/{agent_id}/credentials",
    response_model=CredentialCreated,
    status_code=201,
)
async def create_credential(
    agent_id: uuid.UUID,
    request: Request,
    workspace: Workspace = Depends(get_workspace),
    principal: Principal = Depends(get_principal),
    store: Store = Depends(get_store),
) -> CredentialCreated:
    require_permission(principal, "agent:credential_rotate")
    agent = await require_agent(workspace.id, agent_id, store)
    ensure_self_or_admin(principal, agent)
    credential = await issue_credential(request, store, agent, "api_key", None)
    await record(
        store,
        workspace_id=workspace.id,
        actor_type=principal.kind,
        actor_id=principal.id,
        action="agent.credential_created",
        resource_type="agent",
        resource_id=str(agent.id),
        trace_id=request.state.trace_id,
    )
    await store.commit()
    return CredentialCreated(
        id=credential["id"],
        type="api_key",
        api_key=credential["api_key"],
        prefix=credential["prefix"],
        expires_at=credential["expires_at"],
    )


@router.post("/v1/workspaces/{ws}/agents/{agent_id}/credentials/{credential_id}/revoke")
async def revoke_credential(
    agent_id: uuid.UUID,
    credential_id: uuid.UUID,
    request: Request,
    workspace: Workspace = Depends(get_workspace),
    principal: Principal = Depends(get_principal),
    store: Store = Depends(get_store),
) -> dict:
    require_permission(principal, "agent:credential_rotate")
    agent = await require_agent(workspace.id, agent_id, store)
    ensure_self_or_admin(principal, agent)
    credential = await store.get_credential(agent.id, credential_id)
    if credential is None:
        raise not_found("credential")
    await store.revoke_credential(credential, utcnow())
    await record(
        store,
        workspace_id=workspace.id,
        actor_type=principal.kind,
        actor_id=principal.id,
        action="agent.credential_revoked",
        resource_type="agent",
        resource_id=str(agent.id),
        trace_id=request.state.trace_id,
    )
    await store.commit()
    return {"status": "revoked"}


@router.post(
    "/v1/workspaces/{ws}/enrollment-tokens",
    response_model=EnrollmentTokenCreated,
    status_code=201,
)
async def create_enrollment_token(
    body: EnrollmentTokenCreate,
    request: Request,
    workspace: Workspace = Depends(get_workspace),
    principal: Principal = Depends(get_principal),
    store: Store = Depends(get_store),
) -> EnrollmentTokenCreated:
    require_permission(principal, "agent:create")
    settings = request.app.state.settings
    role = await _resolve_role(store, workspace.id, body.role)
    ensure_agent_role(role)
    ttl = body.ttl_minutes or settings.enrollment_token_ttl_minutes
    if ttl > settings.enrollment_token_max_ttl_minutes:
        raise ApiError(422, "invalid_request", "ttl_minutes exceeds the maximum")
    token, prefix, secret = new_token("enroll")
    record_model = await store.create_enrollment_token(
        workspace_id=workspace.id,
        agent_slug=body.agent_slug,
        role_id=role.id,
        ceiling=body.ceiling,
        prefix=prefix,
        secret_hash=hash_secret(secret),
        expires_at=utcnow() + timedelta(minutes=ttl),
        created_by=principal.id,
    )
    await record(
        store,
        workspace_id=workspace.id,
        actor_type=principal.kind,
        actor_id=principal.id,
        action="enrollment.token_created",
        resource_type="enrollment_token",
        resource_id=str(record_model.id),
        trace_id=request.state.trace_id,
        meta={"agent_slug": body.agent_slug, "role": role.name},
    )
    await store.commit()
    return EnrollmentTokenCreated(
        id=record_model.id,
        token=token,
        agent_slug=body.agent_slug,
        role=role.name,
        expires_at=record_model.expires_at,
    )


@router.delete("/v1/workspaces/{ws}/enrollment-tokens/{token_id}", status_code=204)
async def revoke_enrollment_token(
    token_id: uuid.UUID,
    request: Request,
    workspace: Workspace = Depends(get_workspace),
    principal: Principal = Depends(get_principal),
    store: Store = Depends(get_store),
) -> None:
    require_permission(principal, "agent:create")
    token = await store.get_enrollment_token(token_id)
    if token is None or token.workspace_id != workspace.id:
        raise not_found("enrollment token")
    await store.set_enrollment_token_state(token, "failed")
    await record(
        store,
        workspace_id=workspace.id,
        actor_type=principal.kind,
        actor_id=principal.id,
        action="enrollment.token_revoked",
        resource_type="enrollment_token",
        resource_id=str(token.id),
        trace_id=request.state.trace_id,
    )
    await store.commit()


@router.get(
    "/v1/workspaces/{ws}/agents/{agent_id}/grants", response_model=list[GrantOut]
)
async def list_grants(
    agent_id: uuid.UUID,
    workspace: Workspace = Depends(get_workspace),
    principal: Principal = Depends(get_principal),
    store: Store = Depends(get_store),
) -> list[AgentGrant]:
    require_permission(principal, "grant:read")
    agent = await require_agent(workspace.id, agent_id, store)
    ensure_self_or_admin(principal, agent)
    return await store.list_grants(agent.id)


@router.put(
    "/v1/workspaces/{ws}/agents/{agent_id}/grants/{service_id}",
    response_model=GrantOut,
)
async def put_grant(
    agent_id: uuid.UUID,
    service_id: uuid.UUID,
    body: GrantPut,
    request: Request,
    workspace: Workspace = Depends(get_workspace),
    principal: Principal = Depends(get_principal),
    store: Store = Depends(get_store),
) -> AgentGrant:
    require_permission(principal, "grant:write")
    agent = await require_agent(workspace.id, agent_id, store)
    ensure_self_or_admin(principal, agent)
    service = await store.get_service(service_id)
    if service is None or service.workspace_id != workspace.id:
        raise not_found("service")
    known_tools = await store.tool_names(service.id)
    requested = set(body.tools)
    if not requested:
        raise ApiError(422, "invalid_request", "tools cannot be empty")
    if not requested <= known_tools:
        raise ApiError(
            422,
            "tool_unknown",
            "grant references tools that are not in the catalog",
            detail={"unknown": sorted(requested - known_tools)},
        )

    ceiling_services = (agent.ceiling or {}).get("services")
    if ceiling_services:
        entry = ceiling_services.get(str(service.id)) or ceiling_services.get(service.id)
        if not entry or not requested <= set(entry.get("tools", [])):
            raise forbidden("forbidden", "grant exceeds the agent ceiling")

    if principal.kind == "agent":
        own = await store.get_grant(principal.agent_id, service.id)
        if own is None or own.status != "active" or not requested <= set(own.tools or []):
            raise forbidden("forbidden", "grant exceeds the caller's own tools")

    grant = await store.get_grant(agent.id, service.id)
    if grant is None:
        grant = AgentGrant(
            workspace_id=workspace.id,
            agent_id=agent.id,
            service_id=service.id,
            created_by=principal.id,
        )
    grant.tools = sorted(requested)
    grant.arg_constraints = body.arg_constraints
    expires_at = body.expires_at
    if expires_at is not None and expires_at.tzinfo is not None:
        expires_at = expires_at.astimezone(timezone.utc).replace(tzinfo=None)
    grant.expires_at = expires_at
    grant.status = "active"
    grant.updated_at = utcnow()
    await store.save_grant(grant)
    await record(
        store,
        workspace_id=workspace.id,
        actor_type=principal.kind,
        actor_id=principal.id,
        action="grant.updated",
        resource_type="agent_grant",
        resource_id=str(grant.id),
        trace_id=request.state.trace_id,
        meta={"agent_id": str(agent.id), "service_id": str(service.id), "tools": sorted(requested)},
    )
    await store.commit()
    return grant


@router.delete("/v1/workspaces/{ws}/agents/{agent_id}/grants/{service_id}", status_code=204)
async def delete_grant(
    agent_id: uuid.UUID,
    service_id: uuid.UUID,
    request: Request,
    workspace: Workspace = Depends(get_workspace),
    principal: Principal = Depends(get_principal),
    store: Store = Depends(get_store),
) -> None:
    require_permission(principal, "grant:write")
    agent = await require_agent(workspace.id, agent_id, store)
    ensure_self_or_admin(principal, agent)
    grant = await store.get_grant(agent.id, service_id)
    if grant is None:
        raise not_found("grant")
    await store.revoke_grant(grant)
    await record(
        store,
        workspace_id=workspace.id,
        actor_type=principal.kind,
        actor_id=principal.id,
        action="grant.revoked",
        resource_type="agent_grant",
        resource_id=str(grant.id),
        trace_id=request.state.trace_id,
    )
    await store.commit()


@router.get(
    "/v1/workspaces/{ws}/agents/{agent_id}/connections",
    response_model=list[ConnectionOut],
)
async def list_connections(
    agent_id: uuid.UUID,
    workspace: Workspace = Depends(get_workspace),
    principal: Principal = Depends(get_principal),
    store: Store = Depends(get_store),
):
    require_permission(principal, "connection:read")
    agent = await require_agent(workspace.id, agent_id, store)
    ensure_self_or_admin(principal, agent)
    return await store.list_connections(workspace.id, agent.id)
