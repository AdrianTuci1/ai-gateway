from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from agw.core.errors import forbidden

PermissionScope = Literal["self", "workspace"]


@dataclass(frozen=True)
class Principal:
    kind: Literal["user", "agent"]
    id: uuid.UUID
    workspace_id: uuid.UUID
    permissions: frozenset[str]
    role: str
    agent_id: uuid.UUID | None = None
    ceiling: dict[str, Any] = field(default_factory=dict)
    email: str | None = None
    identity_id: uuid.UUID | None = None
    identity_name: str | None = None
    is_identity_admin: bool = False

    def can(self, permission: str, scope: PermissionScope = "self") -> bool:
        if permission in self.permissions:
            return True
        if scope == "workspace" and f"{permission}:workspace" in self.permissions:
            return True
        return False


def require_permission(
    principal: Principal, permission: str, scope: PermissionScope = "self"
) -> None:
    if not principal.can(permission, scope):
        raise forbidden("forbidden", f"missing permission: {permission}")


@dataclass(frozen=True)
class Decision:
    allowed: bool
    code: str
    reason: str


def _check_constraints(constraints: dict[str, Any], arguments: dict[str, Any]) -> Decision:
    for name, rule in constraints.items():
        if not isinstance(rule, dict):
            return Decision(False, "policy_invalid_constraint", f"constraint for {name} is invalid")
        if "equals" in rule and arguments.get(name) != rule["equals"]:
            return Decision(False, "arg_rejected", f"argument {name} does not match")
        if "one_of" in rule and arguments.get(name) not in rule["one_of"]:
            return Decision(False, "arg_rejected", f"argument {name} is not allowed")
        if rule.get("required") and name not in arguments:
            return Decision(False, "arg_rejected", f"argument {name} is required")
        known = {"equals", "one_of", "required"}
        if set(rule) - known:
            return Decision(False, "policy_invalid_constraint", f"unknown rule for {name}")
    return Decision(True, "allowed", "argument constraints satisfied")


def _ceiling_allows(ceiling: dict[str, Any], service_id: uuid.UUID, tool: str) -> bool:
    services = ceiling.get("services") if ceiling else None
    if not services:
        return True
    entry = services.get(str(service_id)) or services.get(service_id)
    if not entry:
        return False
    return tool in entry.get("tools", [])


def evaluate_tool_call(
    principal: Principal,
    *,
    agent,
    service,
    tool_name: str,
    grant,
    arguments: dict[str, Any],
    now: datetime,
) -> Decision:
    if agent.workspace_id != service.workspace_id:
        return Decision(False, "tool_not_allowed", "service is outside the agent workspace")
    if agent.status != "active":
        return Decision(False, "tool_not_allowed", "agent is not active")
    if principal.kind == "agent" and principal.agent_id != agent.id:
        return Decision(False, "tool_not_allowed", "credential does not belong to this agent")
    if grant is None or grant.status != "active":
        return Decision(False, "tool_not_allowed", "no active grant for this service")
    if grant.expires_at is not None and grant.expires_at <= now:
        return Decision(False, "tool_not_allowed", "grant expired")
    if tool_name not in (grant.tools or []):
        return Decision(False, "tool_not_allowed", f"{tool_name} is not in the grant")
    if not _ceiling_allows(agent.ceiling or {}, service.id, tool_name):
        return Decision(False, "tool_not_allowed", f"{tool_name} is outside the agent ceiling")
    constraints = (grant.arg_constraints or {}).get(tool_name, {})
    return _check_constraints(constraints, arguments)
