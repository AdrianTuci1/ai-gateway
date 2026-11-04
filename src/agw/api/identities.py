from __future__ import annotations

import re
import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, Request

from agw.api.auth import _base_url
from agw.api.deps import get_principal, get_settings, get_store, get_workspace
from agw.api.identity_service import can_manage_identity
from agw.api.schemas import (
    IdentityEntityOut,
    IdentityGroupOut,
    IdentityInviteAccept,
    IdentityInviteAccepted,
    IdentityInviteCreate,
    IdentityInviteCreated,
    IdentityInvitePreview,
    UserOut,
)
from agw.audit.service import record
from agw.config import Settings
from agw.core.errors import ApiError, not_found
from agw.core.security import create_session_token, hash_opaque, hash_secret, new_opaque
from agw.core.time import utcnow
from agw.db.models import Identity, Membership, Workspace
from agw.policy.engine import Principal, require_permission
from agw.store.base import Store

router = APIRouter()

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _email(value: str | None) -> str:
    cleaned = (value or "").strip().lower()
    if not _EMAIL.match(cleaned):
        raise ApiError(422, "invalid_request", "a valid e-mail address is required")
    return cleaned


def _entity_name(kind: str, user, agent) -> str:
    if kind == "user" and user is not None:
        return user.display_name or user.email
    if kind == "agent" and agent is not None:
        return agent.name or agent.slug
    return "Unknown"


async def _group(
    store: Store,
    identity: Identity,
    *,
    principal: Principal,
    services_by_id: dict[uuid.UUID, object],
    signup,
) -> IdentityGroupOut:
    memberships = await store.list_memberships_for_identity(identity.id)
    entities: list[IdentityEntityOut] = []
    for membership in memberships:
        role = await store.get_role(membership.role_id)
        permissions = list(role.permissions) if role is not None else []
        role_name = role.name if role is not None else "unknown"
        if membership.principal_type == "user":
            user = await store.get_user(membership.principal_id)
            if user is None:
                continue
            entities.append(
                IdentityEntityOut(
                    kind="user",
                    id=user.id,
                    name=user.display_name or user.email,
                    email=user.email,
                    role=role_name,
                    permissions=permissions,
                    status=membership.status,
                    is_identity_admin=bool(membership.is_identity_admin),
                    last_seen_at=user.last_seen_at,
                )
            )
            continue
        agent = await store.get_agent(membership.principal_id)
        if agent is None:
            continue
        grants = await store.list_active_grants(agent.id)
        group_ids = {
            service.resource_group_id
            for service in (
                services_by_id.get(grant.service_id) for grant in grants
            )
            if service is not None and service.resource_group_id is not None
        }
        entities.append(
            IdentityEntityOut(
                kind="agent",
                id=agent.id,
                name=agent.name,
                role=role_name,
                permissions=permissions,
                status=membership.status,
                is_identity_admin=bool(membership.is_identity_admin),
                agent_kind=agent.kind,
                group_count=len(group_ids),
                grant_count=len(grants),
            )
        )
    can_manage = can_manage_identity(
        permissions=principal.permissions,
        identity_id=principal.identity_id,
        is_identity_admin=principal.is_identity_admin,
        target_identity_id=identity.id,
    )
    return IdentityGroupOut(
        id=identity.id,
        name=identity.name,
        status=identity.status,
        created_at=identity.created_at,
        decided_at=identity.decided_at,
        decision_note=identity.decision_note,
        entities=entities,
        signup_id=signup.id if signup is not None else None,
        requested_role=signup.requested_role if signup is not None else None,
        owner_email=signup.owner_email if signup is not None else None,
        can_manage=can_manage,
    )


async def _signup_map(store: Store, workspace_id: uuid.UUID) -> dict[uuid.UUID, object]:
    mapping: dict[uuid.UUID, object] = {}
    for signup in await store.list_signup_requests(workspace_id):
        if signup.identity_id is not None:
            mapping.setdefault(signup.identity_id, signup)
    return mapping


@router.get(
    "/v1/workspaces/{ws}/identity-groups",
    response_model=list[IdentityGroupOut],
)
async def list_identity_groups(
    status: str | None = None,
    workspace: Workspace = Depends(get_workspace),
    principal: Principal = Depends(get_principal),
    store: Store = Depends(get_store),
) -> list[IdentityGroupOut]:
    require_permission(principal, "member:read")
    identities = await store.list_identities(workspace.id, status=status)
    services = {service.id: service for service in await store.list_services(workspace.id)}
    signups = await _signup_map(store, workspace.id)
    return [
        await _group(
            store,
            identity,
            principal=principal,
            services_by_id=services,
            signup=signups.get(identity.id),
        )
        for identity in identities
    ]


@router.get(
    "/v1/workspaces/{ws}/identity-groups/{identity_id}",
    response_model=IdentityGroupOut,
)
async def get_identity_group(
    identity_id: uuid.UUID,
    workspace: Workspace = Depends(get_workspace),
    principal: Principal = Depends(get_principal),
    store: Store = Depends(get_store),
) -> IdentityGroupOut:
    require_permission(principal, "member:read")
    identity = await store.get_identity(identity_id)
    if identity is None or identity.workspace_id != workspace.id:
        raise not_found("identity")
    services = {service.id: service for service in await store.list_services(workspace.id)}
    signups = await _signup_map(store, workspace.id)
    return await _group(
        store,
        identity,
        principal=principal,
        services_by_id=services,
        signup=signups.get(identity.id),
    )


@router.post(
    "/v1/workspaces/{ws}/identity-groups/{identity_id}/invites",
    response_model=IdentityInviteCreated,
    status_code=201,
)
async def create_identity_invite(
    identity_id: uuid.UUID,
    body: IdentityInviteCreate,
    request: Request,
    workspace: Workspace = Depends(get_workspace),
    principal: Principal = Depends(get_principal),
    store: Store = Depends(get_store),
    settings: Settings = Depends(get_settings),
) -> IdentityInviteCreated:
    identity = await store.get_identity(identity_id)
    if identity is None or identity.workspace_id != workspace.id:
        raise not_found("identity")
    if not can_manage_identity(
        permissions=principal.permissions,
        identity_id=principal.identity_id,
        is_identity_admin=principal.is_identity_admin,
        target_identity_id=identity.id,
    ):
        raise ApiError(403, "forbidden", "identity administration is required")
    if identity.status != "active":
        raise ApiError(409, "identity_not_active", "the identity is not active yet")

    signups = await _signup_map(store, workspace.id)
    signup = signups.get(identity.id)
    email = _email(body.email or (signup.owner_email if signup is not None else None))

    workspace_admin = principal.can("identity:approve")
    requested_role = body.role or "viewer"
    if not workspace_admin and requested_role != "viewer":
        raise ApiError(
            403,
            "forbidden",
            "identity administrators can invite people with the viewer role",
        )
    role = await store.resolve_role(workspace.id, requested_role)
    if role is None or role.name.startswith("agent:"):
        raise ApiError(422, "invalid_role", "a human role is required")

    token = new_opaque(32)
    invite = await store.create_identity_invite(
        identity_id=identity.id,
        workspace_id=workspace.id,
        email=email,
        role_id=role.id,
        token_hash=hash_opaque(token),
        created_by=principal.id,
        expires_at=utcnow() + timedelta(hours=settings.identity_invite_ttl_hours),
    )
    await record(
        store,
        workspace_id=workspace.id,
        actor_type=principal.kind,
        actor_id=principal.id,
        action="identity.invited",
        resource_type="identity",
        resource_id=str(identity.id),
        trace_id=request.state.trace_id,
        meta={"email": email, "role": role.name},
    )
    await store.commit()
    base = _base_url(request, settings)
    return IdentityInviteCreated(
        id=invite.id,
        identity_id=identity.id,
        identity_name=identity.name,
        email=email,
        role=role.name,
        invite_url=f"{base}/claim/{token}",
        expires_at=invite.expires_at,
    )


async def _invite(store: Store, token: str):
    invite = await store.get_identity_invite_by_hash(hash_opaque(token))
    if invite is None or invite.consumed_at is not None or invite.expires_at <= utcnow():
        raise not_found("invite")
    identity = await store.get_identity(invite.identity_id)
    if identity is None:
        raise not_found("invite")
    workspace = await store.get_workspace(invite.workspace_id)
    if workspace is None or workspace.deleted_at is not None:
        raise not_found("invite")
    return invite, identity, workspace


@router.get("/v1/identity-invites/{token}", response_model=IdentityInvitePreview)
async def preview_identity_invite(
    token: str,
    store: Store = Depends(get_store),
) -> IdentityInvitePreview:
    invite, identity, workspace = await _invite(store, token)
    role = await store.get_role(invite.role_id)
    return IdentityInvitePreview(
        identity_name=identity.name,
        workspace_slug=workspace.slug,
        workspace_name=workspace.name,
        email=invite.email,
        role=role.name if role is not None else "unknown",
        expires_at=invite.expires_at,
    )


@router.post(
    "/v1/identity-invites/{token}/accept",
    response_model=IdentityInviteAccepted,
)
async def accept_identity_invite(
    token: str,
    body: IdentityInviteAccept,
    request: Request,
    store: Store = Depends(get_store),
    settings: Settings = Depends(get_settings),
) -> IdentityInviteAccepted:
    invite, identity, workspace = await _invite(store, token)
    if identity.status != "active":
        raise ApiError(409, "identity_not_active", "the identity is not active yet")

    user = await store.get_user_by_email(invite.email)
    if user is None:
        user = await store.create_user(
            email=invite.email,
            idp_subject=f"local:{invite.email}",
            display_name=body.display_name,
        )
    if body.password and user.password_hash is None:
        user.password_hash = hash_secret(body.password)
        await store.save_user(user)
    membership = await store.get_membership(workspace.id, "user", user.id)
    if membership is not None and membership.status in (None, "active"):
        raise ApiError(409, "already_member", "this person is already a member")
    if membership is None:
        await store.create_membership(
            workspace_id=workspace.id,
            principal_type="user",
            principal_id=user.id,
            role_id=invite.role_id,
            status="active",
            identity_id=identity.id,
            is_identity_admin=False,
        )
    else:
        membership.identity_id = identity.id
        membership.role_id = invite.role_id
        membership.status = "active"
        membership.is_identity_admin = False
        await store.save_membership(membership)

    invite.consumed_at = utcnow()
    await store.save_identity_invite(invite)
    await record(
        store,
        workspace_id=workspace.id,
        actor_type="user",
        actor_id=user.id,
        action="identity.invite_accepted",
        resource_type="identity",
        resource_id=str(identity.id),
        trace_id=request.state.trace_id,
        meta={"email": invite.email, "role_id": str(invite.role_id)},
    )
    await store.commit()
    session = create_session_token(
        user.id, workspace.id, settings.session_secret, settings.session_ttl_hours
    )
    return IdentityInviteAccepted(
        token=session,
        expires_in=settings.session_ttl_hours * 3600,
        workspace_slug=workspace.slug,
        identity_id=identity.id,
        identity_name=identity.name,
        user=UserOut.model_validate(user),
    )
