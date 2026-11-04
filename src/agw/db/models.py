from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from agw.core.time import utcnow
from agw.db.base import Base

JSONType = JSON().with_variant(JSONB, "postgresql")


class Workspace(Base):
    __tablename__ = "workspace"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AppUser(Base):
    __tablename__ = "app_user"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    idp_subject: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(320), index=True)
    display_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    password_hash: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Identity(Base):
    """An umbrella identity that groups one person and their agents."""

    __tablename__ = "identity"
    __table_args__ = (
        Index("ix_identity_workspace_status", "workspace_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("workspace.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(16), default="pending")
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("app_user.id"), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class IdentityInvite(Base):
    """A one-time link that lets a person join an already-approved identity."""

    __tablename__ = "identity_invite"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    identity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("identity.id", ondelete="CASCADE"), index=True
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("workspace.id", ondelete="CASCADE"), index=True
    )
    email: Mapped[str] = mapped_column(String(320), index=True)
    role_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("role_definition.id"))
    token_hash: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class RoleDefinition(Base):
    __tablename__ = "role_definition"
    __table_args__ = (UniqueConstraint("workspace_id", "name", name="uq_role_workspace_name"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("workspace.id", ondelete="CASCADE"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(80))
    permissions: Mapped[list[str]] = mapped_column(JSONType, default=list)
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False)


class Membership(Base):
    __tablename__ = "membership"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "principal_type", "principal_id", name="uq_membership_principal"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("workspace.id", ondelete="CASCADE"), index=True
    )
    principal_type: Mapped[str] = mapped_column(String(16))
    principal_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    role_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("role_definition.id"))
    identity_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("identity.id", ondelete="CASCADE"), nullable=True, index=True
    )
    is_identity_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(16), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class SignupRequest(Base):
    """A self-service request to join a workspace, pending a human decision."""

    __tablename__ = "signup_request"
    __table_args__ = (
        Index("ix_signup_request_workspace_status", "workspace_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("workspace.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(16), default="pending")
    identity_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("identity.id", ondelete="SET NULL"), nullable=True, index=True
    )
    identity_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    owner_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    agent_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    agent_slug: Mapped[str | None] = mapped_column(String(80), nullable=True)
    requested_role: Mapped[str | None] = mapped_column(String(80), nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    principal_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("app_user.id"), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ResourceGroup(Base):
    """A named collection of resources.

    Resources live in a group or stand alone. The group is a navigation and
    ownership unit; the policy engine still evaluates grants per resource.
    """

    __tablename__ = "resource_group"
    __table_args__ = (
        UniqueConstraint("workspace_id", "name", name="uq_group_workspace_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("workspace.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(32), default="application")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Agent(Base):
    __tablename__ = "agent"
    __table_args__ = (UniqueConstraint("workspace_id", "slug", name="uq_agent_workspace_slug"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("workspace.id", ondelete="CASCADE"), index=True
    )
    slug: Mapped[str] = mapped_column(String(80))
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(24), default="interactive")
    status: Mapped[str] = mapped_column(String(24), default="active")
    ceiling: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    resource_group_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("resource_group.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AgentCredential(Base):
    __tablename__ = "agent_credential"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("agent.id", ondelete="CASCADE"), index=True
    )
    type: Mapped[str] = mapped_column(String(24))
    prefix: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    secret_hash: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    cert_fingerprint: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    cert_pem: Mapped[str | None] = mapped_column(Text, nullable=True)
    serial_number: Mapped[str | None] = mapped_column(String(128), nullable=True)
    issuer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    spiffe_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class BootstrapState(Base):
    __tablename__ = "bootstrap_state"

    id: Mapped[bool] = mapped_column(Boolean, primary_key=True, default=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("app_user.id"), nullable=True
    )
    method: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class EnrollmentToken(Base):
    __tablename__ = "enrollment_token"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("workspace.id", ondelete="CASCADE"), index=True
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("agent.id", ondelete="CASCADE"), nullable=True
    )
    agent_slug: Mapped[str] = mapped_column(String(80))
    role_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("role_definition.id"))
    ceiling: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    prefix: Mapped[str] = mapped_column(String(16), index=True)
    secret_hash: Mapped[bytes] = mapped_column(LargeBinary)
    state: Mapped[str] = mapped_column(String(16), default="active")
    enrollment_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    reserved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class EnrollmentDeviceCode(Base):
    __tablename__ = "enrollment_device_code"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    device_code_hash: Mapped[bytes] = mapped_column(LargeBinary)
    user_code: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("workspace.id", ondelete="CASCADE"), nullable=True
    )
    agent_name: Mapped[str] = mapped_column(String(200))
    requested_role: Mapped[str | None] = mapped_column(String(80), nullable=True)
    approved_agent: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("agent.id"), nullable=True
    )
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("app_user.id"), nullable=True
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    interval_seconds: Mapped[int] = mapped_column(Integer, default=5)
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class UpstreamService(Base):
    __tablename__ = "upstream_service"
    __table_args__ = (UniqueConstraint("workspace_id", "name", name="uq_service_workspace_name"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("workspace.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(80))
    kind: Mapped[str] = mapped_column(String(24))
    endpoint: Mapped[str | None] = mapped_column(Text, nullable=True)
    auth_type: Mapped[str] = mapped_column(String(24), default="none")
    auth_config: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    credential_policy: Mapped[str] = mapped_column(String(24), default="per_agent")
    manifest_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    manifest_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    runtime_requirements: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="active")
    resource_group_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("resource_group.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ServiceTool(Base):
    __tablename__ = "service_tool"
    __table_args__ = (UniqueConstraint("service_id", "name", name="uq_tool_service_name"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    service_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("upstream_service.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200), index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_schema: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    annotations: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    definition_hash: Mapped[str] = mapped_column(String(128))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AgentGrant(Base):
    __tablename__ = "agent_grant"
    __table_args__ = (
        UniqueConstraint("agent_id", "service_id", name="uq_grant_agent_service"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("workspace.id", ondelete="CASCADE"), index=True
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("agent.id", ondelete="CASCADE"), index=True
    )
    service_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("upstream_service.id", ondelete="CASCADE"), index=True
    )
    tools: Mapped[list[str]] = mapped_column(JSONType, default=list)
    arg_constraints: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="active")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class ServiceConnection(Base):
    __tablename__ = "service_connection"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("workspace.id", ondelete="CASCADE"), index=True
    )
    service_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("upstream_service.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("app_user.id"), nullable=True
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("agent.id"), nullable=True
    )
    binding: Mapped[str] = mapped_column(String(24), default="per_agent")
    binding_key: Mapped[str] = mapped_column(String(255), unique=True)
    status: Mapped[str] = mapped_column(String(24), default="active")
    credentials_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    scopes: Mapped[list[str]] = mapped_column(JSONType, default=list)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class AuditEvent(Base):
    __tablename__ = "audit_event"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("workspace.id", ondelete="CASCADE"), nullable=True, index=True
    )
    actor_type: Mapped[str] = mapped_column(String(16))
    actor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    action: Mapped[str] = mapped_column(String(80), index=True)
    resource_type: Mapped[str | None] = mapped_column(String(48), nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    decision: Mapped[str | None] = mapped_column(String(16), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    trace_id: Mapped[str] = mapped_column(String(64), index=True)
    meta: Mapped[dict[str, Any]] = mapped_column("metadata", JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class OAuthState(Base):
    __tablename__ = "oauth_state"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("workspace.id", ondelete="CASCADE"), index=True
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("agent.id", ondelete="CASCADE"))
    service_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("upstream_service.id", ondelete="CASCADE")
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("app_user.id"), nullable=True
    )
    state_hash: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    pkce_verifier_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_record"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("workspace.id", ondelete="CASCADE"), index=True
    )
    key: Mapped[str] = mapped_column(String(255))
    request_hash: Mapped[str] = mapped_column(String(128))
    response_body: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class TraceSpan(Base):
    """One timed unit of work inside a trace.

    The HTTP middleware writes the root span for every API request; the MCP
    endpoint adds a child span per tool call. Durations are milliseconds.
    """

    __tablename__ = "trace_span"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("workspace.id", ondelete="CASCADE"), index=True
    )
    trace_id: Mapped[str] = mapped_column(String(64), index=True)
    span_id: Mapped[str] = mapped_column(String(32))
    parent_span_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(16), default="server")
    status: Mapped[str] = mapped_column(String(16), default="ok")
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    actor_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


__all__ = [
    "Agent",
    "AgentCredential",
    "AgentGrant",
    "AppUser",
    "AuditEvent",
    "BootstrapState",
    "EnrollmentDeviceCode",
    "EnrollmentToken",
    "IdempotencyRecord",
    "Membership",
    "OAuthState",
    "ResourceGroup",
    "RoleDefinition",
    "ServiceConnection",
    "ServiceTool",
    "TraceSpan",
    "UpstreamService",
    "Workspace",
]
