from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class WorkspaceOut(ORMModel):
    id: uuid.UUID
    slug: str
    name: str
    created_at: datetime


class UserOut(ORMModel):
    id: uuid.UUID
    email: str
    display_name: str | None = None


class WorkspaceCreate(BaseModel):
    slug: str = Field(min_length=2, max_length=80, pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str = Field(min_length=2, max_length=200)


class BootstrapRequest(BaseModel):
    workspace_slug: str = Field(min_length=2, max_length=80, pattern=r"^[a-z0-9][a-z0-9-]*$")
    workspace_name: str = Field(min_length=2, max_length=200)
    owner_email: str = Field(min_length=3, max_length=320)
    owner_name: str | None = None
    password: str | None = Field(default=None, min_length=8, max_length=200)


class BootstrapResponse(BaseModel):
    workspace: WorkspaceOut
    user: UserOut
    token: str
    expires_in: int


class DevLoginRequest(BaseModel):
    email: str
    workspace_slug: str


class PasswordLoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    workspace_slug: str = Field(min_length=2, max_length=80)
    password: str = Field(min_length=8, max_length=200)


class AuthConfigOut(BaseModel):
    password: bool
    google: bool
    dev: bool


class TokenResponse(BaseModel):
    token: str
    token_type: str = "bearer"
    expires_in: int


class MeOut(BaseModel):
    kind: Literal["user", "agent"]
    id: uuid.UUID
    workspace_id: uuid.UUID
    workspace_slug: str | None
    role: str
    permissions: list[str]
    agent_id: uuid.UUID | None = None
    email: str | None = None
    identity_id: uuid.UUID | None = None
    identity_name: str | None = None
    is_identity_admin: bool = False


class AgentCreate(BaseModel):
    slug: str = Field(min_length=2, max_length=80, pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str = Field(min_length=1, max_length=200)
    kind: Literal["interactive", "autonomous", "service"] = "interactive"
    role: str = "agent:executor"
    ceiling: dict[str, Any] = Field(default_factory=dict)
    issue_credential: bool = True
    resource_group_id: uuid.UUID | None = None


class AgentOut(ORMModel):
    id: uuid.UUID
    slug: str
    name: str
    kind: str
    status: str
    ceiling: dict[str, Any]
    resource_group_id: uuid.UUID | None = None
    created_at: datetime


class AgentCreated(BaseModel):
    agent: AgentOut
    api_key: str | None = None
    role: str


class AgentUpdate(BaseModel):
    name: str | None = None
    slug: str | None = Field(
        default=None, min_length=2, max_length=80, pattern=r"^[a-z0-9][a-z0-9-]*$"
    )
    kind: Literal["interactive", "autonomous", "service"] | None = None
    ceiling: dict[str, Any] | None = None
    status: Literal["active", "suspended", "revoked"] | None = None
    resource_group_id: uuid.UUID | None = None


class CredentialCreated(BaseModel):
    id: uuid.UUID
    type: str
    api_key: str | None = None
    prefix: str | None = None
    expires_at: datetime | None = None


class EnrollmentTokenCreate(BaseModel):
    agent_slug: str = Field(min_length=2, max_length=80)
    role: str = "agent:executor"
    ceiling: dict[str, Any] = Field(default_factory=dict)
    ttl_minutes: int | None = None


class EnrollmentTokenCreated(BaseModel):
    id: uuid.UUID
    token: str
    agent_slug: str
    role: str
    expires_at: datetime


class EnrollRequest(BaseModel):
    agent_slug: str
    credential_type: Literal["client_cert", "api_key"] = "api_key"
    csr_pem: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class EnrollResponse(BaseModel):
    agent_id: uuid.UUID
    workspace_id: uuid.UUID
    credential: dict[str, Any]
    runtime: dict[str, Any]
    renewal: dict[str, Any] | None = None


class DeviceStartRequest(BaseModel):
    agent_name: str = Field(min_length=1, max_length=200)
    requested_role: str = "agent:executor"


class DeviceStartResponse(BaseModel):
    device_code: str
    user_code: str
    verification_uri: str
    expires_in: int
    interval: int


class DeviceApproveRequest(BaseModel):
    user_code: str
    workspace_slug: str
    role: str = "agent:executor"
    agent_slug: str | None = None
    ceiling: dict[str, Any] = Field(default_factory=dict)


class DeviceTokenRequest(BaseModel):
    device_code: str
    credential_type: Literal["client_cert", "api_key"] = "api_key"
    csr_pem: str | None = None


class ServiceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    kind: Literal["mcp_http", "mcp_stdio", "http", "a2a"] = "mcp_http"
    endpoint: str | None = None
    auth_type: Literal["none", "oauth2", "api_key", "mtls"] = "none"
    credential_policy: Literal["per_agent", "per_user", "workspace"] = "per_agent"
    resource_group_id: uuid.UUID | None = None


class ServiceOut(ORMModel):
    id: uuid.UUID
    name: str
    kind: str
    endpoint: str | None
    auth_type: str
    credential_policy: str
    resource_group_id: uuid.UUID | None = None
    manifest_hash: str | None
    manifest_synced_at: datetime | None
    runtime_requirements: dict[str, Any]
    status: str
    created_at: datetime


class ServiceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    endpoint: str | None = None
    auth_type: Literal["none", "oauth2", "api_key", "mtls"] | None = None
    credential_policy: Literal["per_agent", "per_user", "workspace"] | None = None
    status: Literal["active", "disabled"] | None = None
    resource_group_id: uuid.UUID | None = None


class ToolOut(ORMModel):
    id: uuid.UUID
    name: str
    description: str | None
    input_schema: dict[str, Any]
    annotations: dict[str, Any]
    definition_hash: str
    last_seen_at: datetime


class DiscoverResponse(BaseModel):
    service: ServiceOut
    tools: list[ToolOut]


class GrantPut(BaseModel):
    tools: list[str]
    arg_constraints: dict[str, Any] = Field(default_factory=dict)
    expires_at: datetime | None = None


class GrantOut(ORMModel):
    id: uuid.UUID
    agent_id: uuid.UUID
    service_id: uuid.UUID
    tools: list[str]
    arg_constraints: dict[str, Any]
    status: str
    expires_at: datetime | None
    updated_at: datetime


class CatalogTool(BaseModel):
    service_id: uuid.UUID
    service_name: str
    name: str
    description: str | None
    input_schema: dict[str, Any]
    granted: bool


class CatalogResponse(BaseModel):
    items: list[CatalogTool]
    next_cursor: str | None


class ConnectionOut(ORMModel):
    id: uuid.UUID
    agent_id: uuid.UUID | None
    user_id: uuid.UUID | None
    service_id: uuid.UUID
    binding: str
    status: str
    scopes: list[str]
    expires_at: datetime | None


class AuditOut(ORMModel):
    id: uuid.UUID
    workspace_id: uuid.UUID | None
    actor_type: str
    actor_id: uuid.UUID | None
    action: str
    resource_type: str | None
    resource_id: str | None
    decision: str | None
    reason: str | None
    trace_id: str
    meta: dict[str, Any]
    created_at: datetime


class RuntimeOut(BaseModel):
    runtime: str
    features: dict[str, bool]
    limits: dict[str, int]


# Inventory: resource groups, resources, identities, traces.


class ResourceItem(BaseModel):
    type: Literal["service", "agent"]
    id: uuid.UUID
    name: str
    kind: str
    status: str
    group_id: uuid.UUID | None = None
    detail: str | None = None
    children: int = 0


class ResourceGroupOut(ORMModel):
    id: uuid.UUID
    name: str
    kind: str
    description: str | None
    created_at: datetime
    resources: list[ResourceItem] = Field(default_factory=list)


class ResourceGroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: str = Field(default="application", max_length=32)
    description: str | None = Field(default=None, max_length=1000)


class ResourceGroupUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    kind: str | None = Field(default=None, max_length=32)
    description: str | None = Field(default=None, max_length=1000)


class ResourceRef(BaseModel):
    type: Literal["service", "agent"]
    id: uuid.UUID


class GroupResourcesPut(BaseModel):
    resources: list[ResourceRef]


class InventoryOut(BaseModel):
    groups: list[ResourceGroupOut]
    standalone: list[ResourceItem]
    counts: dict[str, int]


class IdentityOut(BaseModel):
    kind: Literal["user", "agent"]
    id: uuid.UUID
    name: str
    email: str | None = None
    role: str
    permissions: list[str]
    status: str
    agent_kind: str | None = None
    group_count: int = 0
    grant_count: int = 0
    last_seen_at: datetime | None = None
    identity_id: uuid.UUID | None = None
    identity_name: str | None = None
    is_identity_admin: bool = False


class SignupCreate(BaseModel):
    kind: Literal["user", "agent"] = "user"
    email: str | None = Field(default=None, max_length=320)
    display_name: str | None = Field(default=None, max_length=200)
    agent_name: str | None = Field(default=None, max_length=200)
    agent_slug: str | None = Field(
        default=None, min_length=2, max_length=80, pattern=r"^[a-z0-9][a-z0-9-]*$"
    )
    identity_name: str | None = Field(default=None, max_length=200)
    owner_email: str | None = Field(default=None, max_length=320)
    password: str | None = Field(default=None, min_length=8, max_length=200)
    requested_role: str | None = Field(default=None, max_length=80)
    message: str | None = Field(default=None, max_length=1000)


class SignupRequestOut(ORMModel):
    id: uuid.UUID
    kind: Literal["user", "agent"]
    status: Literal["pending", "approved", "rejected"]
    identity_id: uuid.UUID | None = None
    identity_name: str | None = None
    email: str | None = None
    owner_email: str | None = None
    display_name: str | None = None
    agent_name: str | None = None
    agent_slug: str | None = None
    requested_role: str | None = None
    message: str | None = None
    principal_id: uuid.UUID | None = None
    decided_by: uuid.UUID | None = None
    decided_at: datetime | None = None
    decision_note: str | None = None
    created_at: datetime


class SignupDecision(BaseModel):
    role: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=1000)


class SignupDecisionOut(BaseModel):
    request: SignupRequestOut
    credential: CredentialCreated | None = None


class IdentityEntityOut(BaseModel):
    kind: Literal["user", "agent"]
    id: uuid.UUID
    name: str
    email: str | None = None
    role: str
    permissions: list[str]
    status: str
    is_identity_admin: bool = False
    agent_kind: str | None = None
    group_count: int = 0
    grant_count: int = 0
    last_seen_at: datetime | None = None


class IdentityGroupOut(BaseModel):
    id: uuid.UUID
    name: str
    status: str
    created_at: datetime
    decided_at: datetime | None = None
    decision_note: str | None = None
    entities: list[IdentityEntityOut] = Field(default_factory=list)
    signup_id: uuid.UUID | None = None
    requested_role: str | None = None
    owner_email: str | None = None
    can_manage: bool = False


class IdentityInviteCreate(BaseModel):
    email: str | None = Field(default=None, max_length=320)
    role: str | None = Field(default=None, max_length=80)


class MembershipRoleUpdate(BaseModel):
    role: str = Field(min_length=1, max_length=80)


class MembershipRoleOut(BaseModel):
    kind: Literal["user", "agent"]
    id: uuid.UUID
    role: str
    permissions: list[str]
    status: str


class IdentityInviteCreated(BaseModel):
    id: uuid.UUID
    identity_id: uuid.UUID
    identity_name: str
    email: str
    role: str
    invite_url: str
    expires_at: datetime


class IdentityInvitePreview(BaseModel):
    identity_name: str
    workspace_slug: str
    workspace_name: str
    email: str
    role: str
    expires_at: datetime


class IdentityInviteAccept(BaseModel):
    display_name: str | None = Field(default=None, max_length=200)
    password: str | None = Field(default=None, min_length=8, max_length=200)


class IdentityInviteAccepted(BaseModel):
    token: str
    token_type: str = "bearer"
    expires_in: int
    workspace_slug: str
    identity_id: uuid.UUID
    identity_name: str
    user: UserOut


class TraceSpanOut(ORMModel):
    span_id: str
    parent_span_id: str | None
    name: str
    kind: str
    status: str
    duration_ms: int
    actor_type: str | None
    actor_id: uuid.UUID | None
    attributes: dict[str, Any]
    started_at: datetime


class TraceSummaryOut(BaseModel):
    trace_id: str
    root_name: str
    status: str
    duration_ms: int
    span_count: int
    actor_type: str | None = None
    actor_id: uuid.UUID | None = None
    started_at: datetime


class TraceDetailOut(BaseModel):
    trace_id: str
    spans: list[TraceSpanOut]
