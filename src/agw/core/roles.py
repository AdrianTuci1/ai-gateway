from __future__ import annotations

from typing import TYPE_CHECKING

from agw.db.models import RoleDefinition

if TYPE_CHECKING:
    from agw.store.base import Store

ALL_PERMISSIONS: tuple[str, ...] = (
    "workspace:read",
    "workspace:update",
    "workspace:delete",
    "member:read",
    "member:invite",
    "member:update_role",
    "member:remove",
    "agent:read",
    "agent:create",
    "agent:update",
    "agent:delete",
    "agent:credential_rotate",
    "service:read",
    "service:create",
    "service:update",
    "service:delete",
    "service:discover",
    "grant:read",
    "grant:request",
    "grant:write",
    "grant:approve",
    "connection:read",
    "connection:authorize",
    "connection:revoke",
    "identity:request",
    "identity:approve",
    "audit:read",
    "usage:read",
    "policy:read",
    "policy:write",
)

_READ_ONLY = (
    "workspace:read",
    "member:read",
    "agent:read",
    "service:read",
    "grant:read",
    "connection:read",
    "audit:read",
    "usage:read",
    "policy:read",
)

_AGENT_EXECUTOR = (
    "workspace:read",
    "agent:read",
    "grant:read",
    "connection:read",
    "connection:authorize",
    "usage:read",
)

BUILTIN_ROLES: dict[str, tuple[str, ...]] = {
    "owner": ALL_PERMISSIONS,
    "admin": tuple(p for p in ALL_PERMISSIONS if p != "workspace:delete"),
    "operator": (
        "workspace:read",
        "member:read",
        "agent:read",
        "agent:update",
        "service:read",
        "service:discover",
        "grant:read",
        "grant:request",
        "grant:approve",
        "connection:read",
        "connection:authorize",
        "connection:revoke",
        "identity:request",
        "identity:approve",
        "audit:read",
        "usage:read",
        "policy:read",
    ),
    "developer": (
        "workspace:read",
        "member:read",
        "agent:read",
        "agent:create",
        "agent:update",
        "agent:credential_rotate",
        "service:read",
        "service:create",
        "service:update",
        "service:discover",
        "grant:read",
        "grant:request",
        "connection:read",
        "connection:authorize",
        "identity:request",
        "usage:read",
        "policy:read",
    ),
    "viewer": _READ_ONLY,
    "agent:executor": _AGENT_EXECUTOR,
    "agent:requester": _AGENT_EXECUTOR
    + ("service:read", "service:discover", "grant:request", "identity:request"),
    "agent:editor": _AGENT_EXECUTOR
    + (
        "service:read",
        "service:discover",
        "grant:request",
        "grant:write",
        "identity:request",
        "agent:update",
        "agent:credential_rotate",
        "policy:read",
    ),
    "agent:admin": (
        "workspace:read",
        "agent:read",
        "agent:create",
        "agent:update",
        "agent:credential_rotate",
        "service:read",
        "service:create",
        "service:update",
        "service:discover",
        "grant:read",
        "grant:request",
        "grant:write",
        "grant:approve",
        "connection:read",
        "connection:authorize",
        "connection:revoke",
        "identity:request",
        "identity:approve",
        "audit:read",
        "usage:read",
        "policy:read",
    ),
}


async def seed_builtin_roles(store: "Store") -> None:
    existing = await store.list_global_roles()
    by_name = {role.name: role for role in existing}
    for name, permissions in BUILTIN_ROLES.items():
        role = by_name.get(name)
        if role is None:
            await store.create_role(
                workspace_id=None,
                name=name,
                permissions=list(permissions),
                is_builtin=True,
            )
        elif list(role.permissions) != list(permissions):
            await store.update_role_permissions(role, list(permissions))
    await store.commit()


async def get_builtin_role(store: "Store", name: str) -> RoleDefinition:
    return await store.get_builtin_role(name)
