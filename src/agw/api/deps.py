from __future__ import annotations

import logging
import uuid
from typing import AsyncIterator

from fastapi import Depends, Request

from agw.config import Settings
from agw.core.errors import enrollment_required, forbidden, not_found, unauthenticated
from agw.core.security import decode_session_token, parse_token, verify_secret
from agw.core.time import utcnow
from agw.db.models import Agent, RoleDefinition, Workspace
from agw.policy.engine import Principal, require_permission
from agw.store.base import Store

logger = logging.getLogger(__name__)


async def get_store(request: Request) -> AsyncIterator[Store]:
    async with request.app.state.store_provider.store() as store:
        yield store


async def _touch_user(request: Request, user_id: uuid.UUID) -> None:
    """Record last-seen in its own short transaction.

    Keeping this write out of the request session matters for SQLite: a session
    that reads first and then writes can fail while another request commits.
    """
    provider = getattr(request.app.state, "store_provider", None)
    if provider is None:
        return
    try:
        async with provider.store() as store:
            user = await store.get_user(user_id)
            if user is not None:
                await store.touch_user(user, utcnow())
                await store.commit()
    except Exception:  # noqa: BLE001 - presence tracking must not fail requests
        logger.debug("last_seen update failed", exc_info=True)


async def _touch_credential(request: Request, prefix: str) -> None:
    provider = getattr(request.app.state, "store_provider", None)
    if provider is None:
        return
    try:
        async with provider.store() as store:
            credential = await store.get_credential_by_prefix(prefix, "api_key")
            if credential is not None:
                await store.touch_credential(credential, utcnow())
                await store.commit()
    except Exception:  # noqa: BLE001 - presence tracking must not fail requests
        logger.debug("credential last_used update failed", exc_info=True)


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


async def _load_role(store: Store, role_id: uuid.UUID) -> RoleDefinition:
    role = await store.get_role(role_id)
    if role is None:
        raise unauthenticated("role no longer exists")
    return role


async def _agent_principal(request: Request, store: Store, token: str) -> Principal:
    parsed = parse_token(token, "live")
    if parsed is None:
        raise unauthenticated("invalid API key")
    prefix, secret = parsed
    credential = await store.get_credential_by_prefix(prefix, "api_key")
    if credential is None or credential.revoked_at is not None:
        raise unauthenticated("invalid API key")
    if credential.expires_at is not None and credential.expires_at <= utcnow():
        raise unauthenticated("API key expired")
    if not verify_secret(credential.secret_hash, secret):
        raise unauthenticated("invalid API key")
    agent = await store.get_agent(credential.agent_id)
    if agent is None or agent.status != "active":
        raise unauthenticated("agent is not active")
    membership = await store.get_membership(
        agent.workspace_id, "agent", agent.id
    )
    if membership is None:
        raise forbidden("agent has no role")
    role = await _load_role(store, membership.role_id)
    identity = (
        await store.get_identity(membership.identity_id)
        if membership.identity_id is not None
        else None
    )
    await _touch_credential(request, prefix)
    return Principal(
        kind="agent",
        id=agent.id,
        workspace_id=agent.workspace_id,
        permissions=frozenset(role.permissions),
        role=role.name,
        agent_id=agent.id,
        ceiling=agent.ceiling or {},
        identity_id=membership.identity_id,
        identity_name=identity.name if identity is not None else None,
        is_identity_admin=bool(membership.is_identity_admin),
    )


async def _session_principal(
    request: Request, store: Store, token: str, secret: str
) -> Principal:
    try:
        payload = decode_session_token(token, secret)
    except Exception as exc:  # noqa: BLE001 - jwt raises several subclasses
        raise unauthenticated("invalid session token") from exc
    try:
        user_id = uuid.UUID(payload["sub"])
        workspace_id = uuid.UUID(payload["ws"])
    except (KeyError, ValueError) as exc:
        raise unauthenticated("invalid session token") from exc
    user = await store.get_user(user_id)
    if user is None:
        raise unauthenticated("user no longer exists")
    membership = await store.get_membership(workspace_id, "user", user.id)
    if membership is None:
        raise forbidden("user is not a member of this workspace")
    if membership.status == "pending":
        raise forbidden("approval_pending", "your access request is waiting for approval")
    if membership.status == "rejected":
        raise forbidden("signup_rejected", "your access request was rejected")
    role = await _load_role(store, membership.role_id)
    identity = (
        await store.get_identity(membership.identity_id)
        if membership.identity_id is not None
        else None
    )
    await _touch_user(request, user.id)
    return Principal(
        kind="user",
        id=user.id,
        workspace_id=workspace_id,
        permissions=frozenset(role.permissions),
        identity_id=membership.identity_id,
        identity_name=identity.name if identity is not None else None,
        is_identity_admin=bool(membership.is_identity_admin),
        role=role.name,
        email=user.email,
    )


async def get_principal(
    request: Request, store: Store = Depends(get_store)
) -> Principal:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise enrollment_required()
    token = header[7:].strip()
    if token.startswith("agw_live_"):
        principal = await _agent_principal(request, store, token)
    else:
        principal = await _session_principal(
            request, store, token, request.app.state.settings.session_secret
        )
    # The tracing middleware reads these after the response is produced.
    request.state.principal = principal
    request.state.workspace_id = principal.workspace_id
    return principal


async def get_workspace(
    ws: str, principal: Principal = Depends(get_principal), store: Store = Depends(get_store)
) -> Workspace:
    workspace = await store.get_workspace_by_slug(ws)
    if workspace is None or workspace.deleted_at is not None:
        raise not_found("workspace")
    if workspace.id != principal.workspace_id:
        raise not_found("workspace")
    return workspace


def ensure_self_or_admin(principal: Principal, agent: Agent) -> None:
    if principal.kind == "user":
        return
    if principal.agent_id == agent.id or principal.role == "agent:admin":
        return
    raise forbidden("forbidden", "agent can only access its own resources")


async def require_agent(
    workspace_id: uuid.UUID, agent_id: uuid.UUID, store: Store
) -> Agent:
    agent = await store.get_agent(agent_id)
    if agent is None or agent.workspace_id != workspace_id:
        raise not_found("agent")
    return agent


__all__ = [
    "ensure_self_or_admin",
    "get_principal",
    "get_settings",
    "get_store",
    "get_workspace",
    "require_agent",
    "require_permission",
]
