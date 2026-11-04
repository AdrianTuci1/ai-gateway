from __future__ import annotations

import re
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request

from agw.api.auth import ensure_agent_role, issue_credential
from agw.api.deps import get_principal, get_settings, get_store, get_workspace
from agw.api.schemas import (
    CredentialCreated,
    SignupCreate,
    SignupDecision,
    SignupDecisionOut,
    SignupRequestOut,
)
from agw.audit.service import record
from agw.config import Settings
from agw.core.errors import ApiError, not_found
from agw.core.security import hash_secret
from agw.core.time import utcnow
from agw.db.models import Identity, SignupRequest, Workspace
from agw.policy.engine import Principal, require_permission
from agw.store.base import Store

router = APIRouter()

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

SignupStatus = Literal["pending", "approved", "rejected"]


def _text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _email(value: str | None) -> str:
    cleaned = (value or "").strip().lower()
    if not _EMAIL.match(cleaned):
        raise ApiError(422, "invalid_request", "a valid e-mail address is required")
    return cleaned


def _signup_out(signup: SignupRequest) -> SignupRequestOut:
    return SignupRequestOut.model_validate(signup)


async def _workspace_by_slug(store: Store, slug: str) -> Workspace:
    workspace = await store.get_workspace_by_slug(slug)
    if workspace is None or workspace.deleted_at is not None:
        raise not_found("workspace")
    return workspace


async def _signup_identity(
    store: Store, signup: SignupRequest, workspace: Workspace
) -> Identity:
    if signup.identity_id is not None:
        identity = await store.get_identity(signup.identity_id)
        if identity is not None:
            return identity
    identity = await store.create_identity(
        workspace_id=workspace.id,
        name=signup.identity_name
        or signup.display_name
        or signup.email
        or signup.agent_name
        or "Identity",
        status="pending",
    )
    signup.identity_id = identity.id
    signup.identity_name = identity.name
    await store.save_signup_request(signup)
    return identity


async def _set_identity_status(
    store: Store,
    identity: Identity,
    *,
    status: str,
    decided_by: uuid.UUID | None,
    note: str | None,
) -> None:
    identity.status = status
    identity.decided_by = decided_by
    identity.decided_at = utcnow()
    identity.decision_note = note
    await store.save_identity(identity)


@router.post(
    "/v1/workspaces/{ws}/signup",
    response_model=SignupRequestOut,
    status_code=201,
)
async def request_signup(
    ws: str,
    body: SignupCreate,
    request: Request,
    store: Store = Depends(get_store),
    settings: Settings = Depends(get_settings),
) -> SignupRequestOut:
    if not settings.signup_enabled:
        raise ApiError(403, "signup_disabled", "self-service signup is disabled")

    workspace = await _workspace_by_slug(store, ws)
    pending = await store.list_signup_requests(workspace.id, status="pending")
    message = _text(body.message)
    requested_role = _text(body.requested_role)
    identity_name = _text(body.identity_name)

    if body.kind == "user":
        email = _email(body.email)
        display_name = _text(body.display_name)
        user = await store.get_user_by_email(email)
        membership = (
            await store.get_membership(workspace.id, "user", user.id)
            if user is not None
            else None
        )
        if membership is not None and membership.status in (None, "active"):
            raise ApiError(409, "already_member", "this e-mail is already a member")
        if any(entry.kind == "user" and entry.email == email for entry in pending):
            raise ApiError(
                409, "signup_pending", "a signup request for this e-mail is already pending"
            )

        viewer = await store.resolve_role(workspace.id, "viewer")
        if viewer is None:
            raise ApiError(500, "internal_error", "the viewer role is not configured")
        if user is None:
            user = await store.create_user(
                email=email,
                idp_subject=f"local:{email}",
                display_name=display_name,
            )
        if body.password and user.password_hash is None:
            user.password_hash = hash_secret(body.password)
            await store.save_user(user)

        identity = None
        if membership is not None and membership.identity_id is not None:
            identity = await store.get_identity(membership.identity_id)
        if identity is None:
            # A person may request access after their agent was already approved
            # under an identity. Attach the request to that identity instead of
            # creating a second umbrella with the same owner e-mail.
            owner_link = next(
                (
                    entry
                    for entry in await store.list_signup_requests(workspace.id)
                    if entry.kind == "agent"
                    and entry.owner_email == email
                    and entry.identity_id is not None
                ),
                None,
            )
            if owner_link is not None:
                linked = await store.get_identity(owner_link.identity_id)
                if linked is not None and linked.status != "rejected":
                    identity = linked
        if identity is None:
            identity = await store.create_identity(
                workspace_id=workspace.id,
                name=identity_name or display_name or email,
                status="pending",
            )
        elif identity.status != "active":
            identity.name = identity_name or display_name or identity.name
            identity.status = "pending"
            identity.decided_by = None
            identity.decided_at = None
            identity.decision_note = None
            await store.save_identity(identity)

        if membership is None:
            await store.create_membership(
                workspace_id=workspace.id,
                principal_type="user",
                principal_id=user.id,
                role_id=viewer.id,
                status="pending",
                identity_id=identity.id,
            )
        else:
            membership.status = "pending"
            membership.role_id = viewer.id
            membership.identity_id = identity.id
            membership.is_identity_admin = False
            await store.save_membership(membership)
        signup = await store.create_signup_request(
            workspace_id=workspace.id,
            kind="user",
            email=email,
            display_name=display_name,
            agent_name=None,
            agent_slug=None,
            requested_role=requested_role,
            message=message,
            identity_id=identity.id,
            identity_name=identity.name,
            owner_email=email,
        )
    else:
        agent_slug = _text(body.agent_slug)
        if not agent_slug:
            raise ApiError(422, "invalid_request", "agent_slug is required")
        agent_name = _text(body.agent_name) or agent_slug
        identity_name = identity_name or agent_name
        owner_email = _text(body.owner_email)
        if owner_email is not None:
            owner_email = _email(owner_email)
        if any(
            entry.kind == "agent" and entry.agent_slug == agent_slug
            for entry in pending
        ):
            raise ApiError(
                409, "signup_pending", "a signup request for this agent is already pending"
            )
        existing_agent = await store.get_agent_by_slug(workspace.id, agent_slug)
        if existing_agent is not None and existing_agent.status != "rejected":
            raise ApiError(409, "agent_exists", "an agent with this slug already exists")
        role = await store.resolve_role(
            workspace.id, requested_role or "agent:executor"
        )
        if role is None:
            raise ApiError(422, "invalid_role", "an agent role is required")
        ensure_agent_role(role)

        identity = await store.create_identity(
            workspace_id=workspace.id, name=identity_name, status="pending"
        )
        if existing_agent is None:
            agent = await store.create_agent(
                workspace_id=workspace.id,
                slug=agent_slug,
                name=agent_name,
                kind="autonomous",
                ceiling={},
                created_by=None,
                status="pending",
            )
        else:
            agent = existing_agent
            agent.name = agent_name
            agent.status = "pending"
            await store.save_agent(agent)
        membership = await store.get_membership(workspace.id, "agent", agent.id)
        if membership is None:
            await store.create_membership(
                workspace_id=workspace.id,
                principal_type="agent",
                principal_id=agent.id,
                role_id=role.id,
                status="pending",
                identity_id=identity.id,
                is_identity_admin=False,
            )
        else:
            membership.status = "pending"
            membership.role_id = role.id
            membership.identity_id = identity.id
            membership.is_identity_admin = False
            await store.save_membership(membership)
        signup = await store.create_signup_request(
            workspace_id=workspace.id,
            kind="agent",
            email=None,
            display_name=None,
            agent_name=agent_name,
            agent_slug=agent_slug,
            requested_role=requested_role or role.name,
            message=message,
            identity_id=identity.id,
            identity_name=identity.name,
            owner_email=owner_email,
        )

    await record(
        store,
        workspace_id=workspace.id,
        actor_type="anonymous",
        actor_id=None,
        action="signup.requested",
        resource_type="signup_request",
        resource_id=str(signup.id),
        trace_id=request.state.trace_id,
        meta={
            "kind": signup.kind,
            "email": signup.email,
            "agent_slug": signup.agent_slug,
            "identity_id": str(signup.identity_id),
        },
    )
    await store.commit()
    return _signup_out(signup)


@router.get(
    "/v1/workspaces/{ws}/signups", response_model=list[SignupRequestOut]
)
async def list_signups(
    status: SignupStatus | None = Query(default=None),
    workspace: Workspace = Depends(get_workspace),
    principal: Principal = Depends(get_principal),
    store: Store = Depends(get_store),
) -> list[SignupRequestOut]:
    require_permission(principal, "member:read")
    signups = await store.list_signup_requests(workspace.id, status=status)
    return [_signup_out(signup) for signup in signups]


@router.get(
    "/v1/workspaces/{ws}/signups/{request_id}", response_model=SignupRequestOut
)
async def get_signup(
    request_id: uuid.UUID,
    workspace: Workspace = Depends(get_workspace),
    principal: Principal = Depends(get_principal),
    store: Store = Depends(get_store),
) -> SignupRequestOut:
    require_permission(principal, "member:read")
    signup = await store.get_signup_request(request_id)
    if signup is None or signup.workspace_id != workspace.id:
        raise not_found("signup request")
    return _signup_out(signup)


async def _pending_signup(
    store: Store, workspace: Workspace, request_id: uuid.UUID
) -> SignupRequest:
    signup = await store.get_signup_request(request_id)
    if signup is None or signup.workspace_id != workspace.id:
        raise not_found("signup request")
    if signup.status != "pending":
        raise ApiError(409, "already_decided", "this signup request was already decided")
    return signup


async def _role_for(
    store: Store, workspace: Workspace, kind: str, requested: str | None
):
    default = "viewer" if kind == "user" else "agent:executor"
    role = await store.resolve_role(workspace.id, requested or default)
    if role is None:
        raise ApiError(422, "invalid_role", f"unknown role: {requested or default}")
    if kind == "user" and role.name.startswith("agent:"):
        raise ApiError(422, "invalid_role", "agent roles cannot be assigned to people")
    if kind == "agent" and not role.name.startswith("agent:"):
        raise ApiError(422, "invalid_role", "agents require an agent role")
    return role


@router.post(
    "/v1/workspaces/{ws}/signups/{request_id}/approve",
    response_model=SignupDecisionOut,
)
async def approve_signup(
    request_id: uuid.UUID,
    body: SignupDecision,
    request: Request,
    workspace: Workspace = Depends(get_workspace),
    principal: Principal = Depends(get_principal),
    store: Store = Depends(get_store),
) -> SignupDecisionOut:
    require_permission(principal, "identity:approve")
    signup = await _pending_signup(store, workspace, request_id)
    role = await _role_for(store, workspace, signup.kind, body.role)
    identity = await _signup_identity(store, signup, workspace)
    credential: dict | None = None

    if signup.kind == "user":
        if not signup.email:
            raise ApiError(422, "invalid_request", "the signup request has no e-mail")
        user = await store.get_user_by_email(signup.email)
        if user is None:
            user = await store.create_user(
                email=signup.email,
                idp_subject=f"local:{signup.email}",
                display_name=signup.display_name,
            )
        membership = await store.get_membership(workspace.id, "user", user.id)
        if membership is not None and membership.status in (None, "active"):
            raise ApiError(409, "already_member", "the person is already an active member")
        if membership is None:
            await store.create_membership(
                workspace_id=workspace.id,
                principal_type="user",
                principal_id=user.id,
                role_id=role.id,
                status="active",
                identity_id=identity.id,
                is_identity_admin=True,
            )
        else:
            membership.status = "active"
            membership.role_id = role.id
            membership.identity_id = identity.id
            membership.is_identity_admin = True
            await store.save_membership(membership)
        signup.principal_id = user.id
    else:
        if not signup.agent_slug:
            raise ApiError(422, "invalid_request", "the signup request has no agent slug")
        agent = await store.get_agent_by_slug(workspace.id, signup.agent_slug)
        if agent is None:
            agent = await store.create_agent(
                workspace_id=workspace.id,
                slug=signup.agent_slug,
                name=signup.agent_name or signup.agent_slug,
                kind="autonomous",
                ceiling={},
                created_by=principal.id if principal.kind == "user" else None,
                status="active",
            )
        else:
            agent.status = "active"
            await store.save_agent(agent)
        membership = await store.get_membership(workspace.id, "agent", agent.id)
        if membership is not None and membership.status in (None, "active"):
            raise ApiError(409, "already_member", "the agent is already an active member")
        if membership is None:
            await store.create_membership(
                workspace_id=workspace.id,
                principal_type="agent",
                principal_id=agent.id,
                role_id=role.id,
                status="active",
                identity_id=identity.id,
                is_identity_admin=True,
            )
        else:
            membership.status = "active"
            membership.role_id = role.id
            membership.identity_id = identity.id
            membership.is_identity_admin = True
            await store.save_membership(membership)
        credential = await issue_credential(request, store, agent, "api_key", None)
        signup.principal_id = agent.id
        await record(
            store,
            workspace_id=workspace.id,
            actor_type=principal.kind,
            actor_id=principal.id,
            action="agent.created",
            resource_type="agent",
            resource_id=str(agent.id),
            trace_id=request.state.trace_id,
            meta={"role": role.name, "via": "signup"},
        )

    await _set_identity_status(
        store,
        identity,
        status="active",
        decided_by=principal.id if principal.kind == "user" else None,
        note=_text(body.note),
    )
    signup.status = "approved"
    signup.decided_by = principal.id if principal.kind == "user" else None
    signup.decided_at = utcnow()
    signup.decision_note = _text(body.note)
    await store.save_signup_request(signup)
    await record(
        store,
        workspace_id=workspace.id,
        actor_type=principal.kind,
        actor_id=principal.id,
        action="identity.approved",
        resource_type="identity",
        resource_id=str(identity.id),
        trace_id=request.state.trace_id,
        decision="allow",
        reason=signup.decision_note,
        meta={"kind": signup.kind, "role": role.name},
    )
    await record(
        store,
        workspace_id=workspace.id,
        actor_type=principal.kind,
        actor_id=principal.id,
        action="signup.approved",
        resource_type="signup_request",
        resource_id=str(signup.id),
        trace_id=request.state.trace_id,
        decision="allow",
        reason=signup.decision_note,
        meta={
            "kind": signup.kind,
            "role": role.name,
            "principal_id": str(signup.principal_id),
        },
    )
    await store.commit()
    return SignupDecisionOut(
        request=_signup_out(signup),
        credential=CredentialCreated(**credential) if credential else None,
    )


@router.post(
    "/v1/workspaces/{ws}/signups/{request_id}/reject",
    response_model=SignupDecisionOut,
)
async def reject_signup(
    request_id: uuid.UUID,
    body: SignupDecision,
    request: Request,
    workspace: Workspace = Depends(get_workspace),
    principal: Principal = Depends(get_principal),
    store: Store = Depends(get_store),
) -> SignupDecisionOut:
    require_permission(principal, "identity:approve")
    signup = await _pending_signup(store, workspace, request_id)
    identity = await _signup_identity(store, signup, workspace)

    if signup.kind == "user" and signup.email:
        user = await store.get_user_by_email(signup.email)
        if user is not None:
            membership = await store.get_membership(workspace.id, "user", user.id)
            if membership is not None and membership.status == "pending":
                membership.status = "rejected"
                await store.save_membership(membership)
    if signup.kind == "agent" and signup.agent_slug:
        agent = await store.get_agent_by_slug(workspace.id, signup.agent_slug)
        if agent is not None:
            agent.status = "rejected"
            await store.save_agent(agent)
            membership = await store.get_membership(workspace.id, "agent", agent.id)
            if membership is not None and membership.status == "pending":
                membership.status = "rejected"
                await store.save_membership(membership)

    await _set_identity_status(
        store,
        identity,
        status="rejected",
        decided_by=principal.id if principal.kind == "user" else None,
        note=_text(body.note),
    )
    signup.status = "rejected"
    signup.decided_by = principal.id if principal.kind == "user" else None
    signup.decided_at = utcnow()
    signup.decision_note = _text(body.note)
    await store.save_signup_request(signup)
    await record(
        store,
        workspace_id=workspace.id,
        actor_type=principal.kind,
        actor_id=principal.id,
        action="identity.rejected",
        resource_type="identity",
        resource_id=str(identity.id),
        trace_id=request.state.trace_id,
        decision="deny",
        reason=signup.decision_note,
        meta={"kind": signup.kind},
    )
    await record(
        store,
        workspace_id=workspace.id,
        actor_type=principal.kind,
        actor_id=principal.id,
        action="signup.rejected",
        resource_type="signup_request",
        resource_id=str(signup.id),
        trace_id=request.state.trace_id,
        decision="deny",
        reason=signup.decision_note,
        meta={"kind": signup.kind, "email": signup.email, "agent_slug": signup.agent_slug},
    )
    await store.commit()
    return SignupDecisionOut(request=_signup_out(signup))
