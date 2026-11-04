from __future__ import annotations

import uuid
from contextlib import AbstractAsyncContextManager
from datetime import datetime
from typing import Any, Protocol, Sequence

from agw.db.models import (
    Agent,
    AgentCredential,
    AgentGrant,
    AppUser,
    AuditEvent,
    BootstrapState,
    EnrollmentDeviceCode,
    EnrollmentToken,
    Identity,
    IdentityInvite,
    Membership,
    ResourceGroup,
    RoleDefinition,
    ServiceConnection,
    ServiceTool,
    SignupRequest,
    TraceSpan,
    UpstreamService,
    Workspace,
)


class Store(Protocol):
    """Request-scoped persistence interface.

    Both the SQL and DynamoDB backends return the same detached model
    instances, so the API layer never depends on a database driver.
    Writes are applied immediately; ``commit`` finishes the unit of work
    for transactional backends and is a no-op for DynamoDB.
    """

    async def ping(self) -> None: ...

    async def commit(self) -> None: ...

    # workspaces
    async def count_workspaces(self) -> int: ...

    async def create_workspace(self, *, slug: str, name: str) -> Workspace: ...

    async def get_workspace(self, workspace_id: uuid.UUID) -> Workspace | None: ...

    async def get_workspace_by_slug(self, slug: str) -> Workspace | None: ...

    async def list_workspaces_for_user(self, user_id: uuid.UUID) -> list[Workspace]: ...

    # identities

    async def create_identity(
        self, *, workspace_id: uuid.UUID, name: str, status: str = "pending"
    ) -> Identity: ...

    async def get_identity(self, identity_id: uuid.UUID) -> Identity | None: ...

    async def list_identities(
        self, workspace_id: uuid.UUID, *, status: str | None = None
    ) -> list[Identity]: ...

    async def save_identity(self, identity: Identity) -> None: ...

    async def list_memberships_for_identity(
        self, identity_id: uuid.UUID
    ) -> list[Membership]: ...

    async def create_identity_invite(
        self,
        *,
        identity_id: uuid.UUID,
        workspace_id: uuid.UUID,
        email: str,
        role_id: uuid.UUID,
        token_hash: bytes,
        created_by: uuid.UUID | None,
        expires_at: datetime,
    ) -> IdentityInvite: ...

    async def get_identity_invite_by_hash(
        self, token_hash: bytes
    ) -> IdentityInvite | None: ...

    async def save_identity_invite(self, invite: IdentityInvite) -> None: ...

    # users
    async def create_user(
        self, *, email: str, idp_subject: str, display_name: str | None = None
    ) -> AppUser: ...

    async def get_user(self, user_id: uuid.UUID) -> AppUser | None: ...

    async def get_user_by_email(self, email: str) -> AppUser | None: ...

    async def get_user_by_subject(self, subject: str) -> AppUser | None: ...

    async def save_user(self, user: AppUser) -> None: ...

    async def touch_user(self, user: AppUser, when: datetime) -> None: ...

    # roles
    async def get_role(self, role_id: uuid.UUID) -> RoleDefinition | None: ...

    async def get_builtin_role(self, name: str) -> RoleDefinition: ...

    async def resolve_role(
        self, workspace_id: uuid.UUID, name: str
    ) -> RoleDefinition | None: ...

    async def list_global_roles(self) -> list[RoleDefinition]: ...

    async def create_role(
        self,
        *,
        workspace_id: uuid.UUID | None,
        name: str,
        permissions: Sequence[str],
        is_builtin: bool,
    ) -> RoleDefinition: ...

    async def update_role_permissions(
        self, role: RoleDefinition, permissions: Sequence[str]
    ) -> None: ...

    # memberships
    async def get_membership(
        self, workspace_id: uuid.UUID, principal_type: str, principal_id: uuid.UUID
    ) -> Membership | None: ...

    async def create_membership(
        self,
        *,
        workspace_id: uuid.UUID,
        principal_type: str,
        principal_id: uuid.UUID,
        role_id: uuid.UUID,
        status: str = "active",
        identity_id: uuid.UUID | None = None,
        is_identity_admin: bool = False,
    ) -> Membership: ...

    async def save_membership(self, membership: Membership) -> None: ...

    async def set_membership_role(
        self, membership: Membership, role_id: uuid.UUID
    ) -> None: ...

    async def list_memberships(self, workspace_id: uuid.UUID) -> list[Membership]: ...

    # signup requests

    async def create_signup_request(
        self,
        *,
        workspace_id: uuid.UUID,
        kind: str,
        email: str | None,
        display_name: str | None,
        agent_name: str | None,
        agent_slug: str | None,
        requested_role: str | None,
        message: str | None,
        identity_id: uuid.UUID | None = None,
        identity_name: str | None = None,
        owner_email: str | None = None,
    ) -> SignupRequest: ...

    async def get_signup_request(
        self, request_id: uuid.UUID
    ) -> SignupRequest | None: ...

    async def list_signup_requests(
        self, workspace_id: uuid.UUID, *, status: str | None = None
    ) -> list[SignupRequest]: ...

    async def save_signup_request(self, signup: SignupRequest) -> None: ...

    # resource groups

    async def create_resource_group(
        self,
        *,
        workspace_id: uuid.UUID,
        name: str,
        kind: str,
        description: str | None,
    ) -> ResourceGroup: ...

    async def get_resource_group(
        self, group_id: uuid.UUID
    ) -> ResourceGroup | None: ...

    async def list_resource_groups(
        self, workspace_id: uuid.UUID
    ) -> list[ResourceGroup]: ...

    async def save_resource_group(self, group: ResourceGroup) -> None: ...

    async def delete_resource_group(self, group: ResourceGroup) -> None: ...

    # tracing

    async def record_trace_span(self, span: TraceSpan) -> None: ...

    async def list_recent_spans(
        self, workspace_id: uuid.UUID, *, limit: int = 100
    ) -> list[TraceSpan]: ...

    async def list_trace_roots(
        self,
        workspace_id: uuid.UUID,
        *,
        limit: int = 50,
        offset: int = 0,
        as_of: datetime | None = None,
    ) -> list[TraceSpan]: ...

    async def count_trace_roots(
        self,
        workspace_id: uuid.UUID,
        *,
        as_of: datetime | None = None,
    ) -> int: ...

    async def list_trace_spans(
        self, workspace_id: uuid.UUID, trace_id: str
    ) -> list[TraceSpan]: ...

    # bootstrap
    async def get_bootstrap(self) -> BootstrapState | None: ...

    async def mark_bootstrapped(
        self, *, user_id: uuid.UUID, method: str, when: datetime
    ) -> BootstrapState: ...

    # agents
    async def create_agent(
        self,
        *,
        workspace_id: uuid.UUID,
        slug: str,
        name: str,
        kind: str,
        ceiling: dict[str, Any],
        created_by: uuid.UUID | None,
        status: str = "active",
    ) -> Agent: ...

    async def get_agent(self, agent_id: uuid.UUID) -> Agent | None: ...

    async def get_agent_by_slug(
        self, workspace_id: uuid.UUID, slug: str
    ) -> Agent | None: ...

    async def list_agents(
        self, workspace_id: uuid.UUID, *, only_agent_id: uuid.UUID | None = None
    ) -> list[Agent]: ...

    async def save_agent(self, agent: Agent) -> None: ...

    # credentials
    async def create_credential(
        self,
        *,
        agent_id: uuid.UUID,
        type: str,
        prefix: str | None = None,
        secret_hash: bytes | None = None,
        cert_fingerprint: str | None = None,
        cert_pem: str | None = None,
        serial_number: str | None = None,
        issuer: str | None = None,
        spiffe_id: str | None = None,
        expires_at: datetime | None = None,
    ) -> AgentCredential: ...

    async def get_credential(
        self, agent_id: uuid.UUID, credential_id: uuid.UUID
    ) -> AgentCredential | None: ...

    async def get_credential_by_prefix(
        self, prefix: str, credential_type: str
    ) -> AgentCredential | None: ...

    async def list_active_credentials(
        self, agent_id: uuid.UUID
    ) -> list[AgentCredential]: ...

    async def revoke_credential(
        self, credential: AgentCredential, when: datetime
    ) -> None: ...

    async def touch_credential(
        self, credential: AgentCredential, when: datetime
    ) -> None: ...

    async def revoke_credentials_for_agent(
        self, agent_id: uuid.UUID, when: datetime
    ) -> None: ...

    # enrollment tokens
    async def create_enrollment_token(
        self,
        *,
        workspace_id: uuid.UUID,
        agent_slug: str,
        role_id: uuid.UUID,
        ceiling: dict[str, Any],
        prefix: str,
        secret_hash: bytes,
        expires_at: datetime,
        created_by: uuid.UUID,
    ) -> EnrollmentToken: ...

    async def get_enrollment_token(
        self, token_id: uuid.UUID
    ) -> EnrollmentToken | None: ...

    async def find_enrollment_token_by_prefix(
        self, prefix: str
    ) -> EnrollmentToken | None: ...

    async def consume_enrollment_token(
        self, token: EnrollmentToken, when: datetime
    ) -> bool: ...

    async def set_enrollment_token_state(
        self, token: EnrollmentToken, state: str
    ) -> None: ...

    # device flow
    async def create_device_code(
        self,
        *,
        device_code_hash: bytes,
        user_code: str,
        agent_name: str,
        requested_role: str | None,
        expires_at: datetime,
        interval_seconds: int,
    ) -> EnrollmentDeviceCode: ...

    async def get_device_code(
        self, code_id: uuid.UUID
    ) -> EnrollmentDeviceCode | None: ...

    async def get_device_code_by_user_code(
        self, user_code: str
    ) -> EnrollmentDeviceCode | None: ...

    async def get_device_code_by_hash(
        self, device_code_hash: bytes
    ) -> EnrollmentDeviceCode | None: ...

    async def device_user_code_exists(self, user_code: str) -> bool: ...

    async def save_device_code(self, code: EnrollmentDeviceCode) -> None: ...

    # services
    async def create_service(
        self,
        *,
        workspace_id: uuid.UUID,
        name: str,
        kind: str,
        endpoint: str | None,
        auth_type: str,
        credential_policy: str,
        created_by: uuid.UUID | None,
    ) -> UpstreamService: ...

    async def get_service(self, service_id: uuid.UUID) -> UpstreamService | None: ...

    async def list_services(self, workspace_id: uuid.UUID) -> list[UpstreamService]: ...

    async def list_services_by_ids(
        self, service_ids: Sequence[uuid.UUID]
    ) -> list[UpstreamService]: ...

    async def save_service(self, service: UpstreamService) -> None: ...

    # tools
    async def list_tools(self, service_id: uuid.UUID) -> list[ServiceTool]: ...

    async def tool_names(self, service_id: uuid.UUID) -> set[str]: ...

    async def get_tool(
        self, service_id: uuid.UUID, name: str
    ) -> ServiceTool | None: ...

    async def save_tool(self, tool: ServiceTool) -> None: ...

    # grants
    async def get_grant(
        self, agent_id: uuid.UUID, service_id: uuid.UUID
    ) -> AgentGrant | None: ...

    async def list_grants(self, agent_id: uuid.UUID) -> list[AgentGrant]: ...

    async def list_active_grants(self, agent_id: uuid.UUID) -> list[AgentGrant]: ...

    async def save_grant(self, grant: AgentGrant) -> None: ...

    async def revoke_grant(self, grant: AgentGrant) -> None: ...

    async def revoke_grants_for_agent(self, agent_id: uuid.UUID) -> None: ...

    async def revoke_grants_for_service(self, service_id: uuid.UUID) -> None: ...

    # connections
    async def list_connections(
        self, workspace_id: uuid.UUID, agent_id: uuid.UUID
    ) -> list[ServiceConnection]: ...

    # catalog
    async def list_catalog(
        self, workspace_id: uuid.UUID, kind: str | None
    ) -> list[tuple[ServiceTool, UpstreamService]]: ...

    # audit
    async def record_audit(
        self,
        *,
        workspace_id: uuid.UUID | None,
        actor_type: str,
        actor_id: uuid.UUID | None,
        action: str,
        trace_id: str,
        resource_type: str | None = None,
        resource_id: str | None = None,
        decision: str | None = None,
        reason: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> AuditEvent: ...

    async def list_audit(
        self,
        workspace_id: uuid.UUID,
        *,
        since: datetime | None = None,
        decision: str | None = None,
        limit: int = 100,
        offset: int = 0,
        as_of: datetime | None = None,
    ) -> list[AuditEvent]: ...

    async def count_audit(
        self,
        workspace_id: uuid.UUID,
        *,
        since: datetime | None = None,
        decision: str | None = None,
        as_of: datetime | None = None,
    ) -> int: ...


class StoreProvider(Protocol):
    """Application-scoped backend: owns connections and startup work."""

    async def startup(self, *, create_tables: bool = False) -> None: ...

    async def shutdown(self) -> None: ...

    def store(self) -> AbstractAsyncContextManager[Store]: ...


def new_id() -> uuid.UUID:
    return uuid.uuid4()
