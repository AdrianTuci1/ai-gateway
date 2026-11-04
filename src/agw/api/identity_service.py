from __future__ import annotations

import uuid

from agw.db.models import Agent, AppUser, Identity, Membership
from agw.store.base import Store


def user_identity_name(user: AppUser) -> str:
    return user.display_name or user.email


def agent_identity_name(agent: Agent) -> str:
    return agent.name or agent.slug


async def ensure_principal_identity(
    store: Store,
    *,
    workspace_id: uuid.UUID,
    principal_type: str,
    principal_id: uuid.UUID,
    name: str,
) -> Identity | None:
    """Return the umbrella identity for an existing membership.

    Legacy rows created before identities existed get one on first use. A
    membership that already points at an identity keeps its admin flag.
    """
    membership = await store.get_membership(workspace_id, principal_type, principal_id)
    if membership is None:
        return None
    if membership.identity_id is not None:
        identity = await store.get_identity(membership.identity_id)
        if identity is not None:
            return identity
    identity = await store.create_identity(
        workspace_id=workspace_id, name=name, status="active"
    )
    membership.identity_id = identity.id
    if membership.is_identity_admin is None:
        membership.is_identity_admin = principal_type == "user"
    await store.save_membership(membership)
    return identity


async def identity_for_membership(
    store: Store, membership: Membership, name: str
) -> Identity:
    if membership.identity_id is not None:
        identity = await store.get_identity(membership.identity_id)
        if identity is not None:
            return identity
    identity = await store.create_identity(
        workspace_id=membership.workspace_id, name=name, status="active"
    )
    membership.identity_id = identity.id
    if membership.is_identity_admin is None:
        membership.is_identity_admin = membership.principal_type == "user"
    await store.save_membership(membership)
    return identity


def can_manage_identity(
    *,
    permissions: frozenset[str],
    identity_id: uuid.UUID | None,
    is_identity_admin: bool,
    target_identity_id: uuid.UUID,
) -> bool:
    if "identity:approve" in permissions:
        return True
    return bool(
        is_identity_admin and identity_id is not None and identity_id == target_identity_id
    )
