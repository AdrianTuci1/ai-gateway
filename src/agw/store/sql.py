from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, AsyncIterator, Sequence

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agw.config import Settings
from agw.core.roles import seed_builtin_roles
from agw.core.time import utcnow
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
from agw.db.session import build_engine, build_sessionmaker
from agw.store.base import Store


class SqlStore:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def ping(self) -> None:
        await self.session.execute(text("select 1"))

    async def commit(self) -> None:
        await self.session.commit()

    # workspaces

    async def count_workspaces(self) -> int:
        return int(
            (
                await self.session.execute(select(func.count()).select_from(Workspace))
            ).scalar_one()
        )

    async def create_workspace(self, *, slug: str, name: str) -> Workspace:
        workspace = Workspace(slug=slug, name=name)
        self.session.add(workspace)
        await self.session.flush()
        return workspace

    async def get_workspace(self, workspace_id: uuid.UUID) -> Workspace | None:
        return await self.session.get(Workspace, workspace_id)

    async def get_workspace_by_slug(self, slug: str) -> Workspace | None:
        return (
            await self.session.execute(select(Workspace).where(Workspace.slug == slug))
        ).scalar_one_or_none()

    async def list_workspaces_for_user(self, user_id: uuid.UUID) -> list[Workspace]:
        rows = (
            await self.session.execute(
                select(Workspace)
                .join(Membership, Membership.workspace_id == Workspace.id)
                .where(
                    Membership.principal_type == "user",
                    Membership.principal_id == user_id,
                    Workspace.deleted_at.is_(None),
                )
            )
        ).scalars().all()
        return list(rows)

    # identities

    async def create_identity(
        self, *, workspace_id: uuid.UUID, name: str, status: str = "pending"
    ) -> Identity:
        identity = Identity(workspace_id=workspace_id, name=name, status=status)
        self.session.add(identity)
        await self.session.flush()
        return identity

    async def get_identity(self, identity_id: uuid.UUID) -> Identity | None:
        return await self.session.get(Identity, identity_id)

    async def list_identities(
        self, workspace_id: uuid.UUID, *, status: str | None = None
    ) -> list[Identity]:
        query = select(Identity).where(Identity.workspace_id == workspace_id)
        if status is not None:
            query = query.where(Identity.status == status)
        query = query.order_by(Identity.created_at.desc(), Identity.id.desc())
        return list((await self.session.execute(query)).scalars())

    async def save_identity(self, identity: Identity) -> None:
        self.session.add(identity)
        await self.session.flush()

    async def list_memberships_for_identity(
        self, identity_id: uuid.UUID
    ) -> list[Membership]:
        query = (
            select(Membership)
            .where(Membership.identity_id == identity_id)
            .order_by(Membership.created_at, Membership.id)
        )
        return list((await self.session.execute(query)).scalars())

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
    ) -> IdentityInvite:
        invite = IdentityInvite(
            identity_id=identity_id,
            workspace_id=workspace_id,
            email=email,
            role_id=role_id,
            token_hash=token_hash,
            created_by=created_by,
            expires_at=expires_at,
        )
        self.session.add(invite)
        await self.session.flush()
        return invite

    async def get_identity_invite_by_hash(
        self, token_hash: bytes
    ) -> IdentityInvite | None:
        return (
            await self.session.execute(
                select(IdentityInvite).where(IdentityInvite.token_hash == token_hash)
            )
        ).scalar_one_or_none()

    async def save_identity_invite(self, invite: IdentityInvite) -> None:
        self.session.add(invite)
        await self.session.flush()

    # users

    async def create_user(
        self, *, email: str, idp_subject: str, display_name: str | None = None
    ) -> AppUser:
        user = AppUser(email=email, idp_subject=idp_subject, display_name=display_name)
        self.session.add(user)
        await self.session.flush()
        return user

    async def get_user(self, user_id: uuid.UUID) -> AppUser | None:
        return await self.session.get(AppUser, user_id)

    async def get_user_by_email(self, email: str) -> AppUser | None:
        return (
            await self.session.execute(
                select(AppUser).where(func.lower(AppUser.email) == email.lower())
            )
        ).scalar_one_or_none()

    async def get_user_by_subject(self, subject: str) -> AppUser | None:
        return (
            await self.session.execute(
                select(AppUser).where(AppUser.idp_subject == subject)
            )
        ).scalar_one_or_none()

    async def save_user(self, user: AppUser) -> None:
        self.session.add(user)
        await self.session.flush()

    async def touch_user(self, user: AppUser, when: datetime) -> None:
        user.last_seen_at = when
        await self.session.flush()

    # roles

    async def get_role(self, role_id: uuid.UUID) -> RoleDefinition | None:
        return await self.session.get(RoleDefinition, role_id)

    async def get_builtin_role(self, name: str) -> RoleDefinition:
        role = (
            await self.session.execute(
                select(RoleDefinition).where(
                    RoleDefinition.workspace_id.is_(None),
                    RoleDefinition.name == name,
                )
            )
        ).scalar_one_or_none()
        if role is None:
            raise LookupError(f"unknown builtin role: {name}")
        return role

    async def resolve_role(
        self, workspace_id: uuid.UUID, name: str
    ) -> RoleDefinition | None:
        return (
            await self.session.execute(
                select(RoleDefinition).where(
                    RoleDefinition.name == name,
                    (RoleDefinition.workspace_id == workspace_id)
                    | (RoleDefinition.workspace_id.is_(None)),
                )
            )
        ).scalars().first()

    async def list_global_roles(self) -> list[RoleDefinition]:
        return list(
            (
                await self.session.execute(
                    select(RoleDefinition).where(RoleDefinition.workspace_id.is_(None))
                )
            ).scalars().all()
        )

    async def create_role(
        self,
        *,
        workspace_id: uuid.UUID | None,
        name: str,
        permissions: Sequence[str],
        is_builtin: bool,
    ) -> RoleDefinition:
        role = RoleDefinition(
            workspace_id=workspace_id,
            name=name,
            permissions=list(permissions),
            is_builtin=is_builtin,
        )
        self.session.add(role)
        await self.session.flush()
        return role

    async def update_role_permissions(
        self, role: RoleDefinition, permissions: Sequence[str]
    ) -> None:
        role.permissions = list(permissions)
        await self.session.flush()

    # memberships

    async def get_membership(
        self, workspace_id: uuid.UUID, principal_type: str, principal_id: uuid.UUID
    ) -> Membership | None:
        return (
            await self.session.execute(
                select(Membership).where(
                    Membership.workspace_id == workspace_id,
                    Membership.principal_type == principal_type,
                    Membership.principal_id == principal_id,
                )
            )
        ).scalar_one_or_none()

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
    ) -> Membership:
        membership = Membership(
            workspace_id=workspace_id,
            principal_type=principal_type,
            principal_id=principal_id,
            role_id=role_id,
            status=status,
            identity_id=identity_id,
            is_identity_admin=is_identity_admin,
        )
        self.session.add(membership)
        await self.session.flush()
        return membership

    async def save_membership(self, membership: Membership) -> None:
        self.session.add(membership)
        await self.session.flush()

    async def set_membership_role(
        self, membership: Membership, role_id: uuid.UUID
    ) -> None:
        membership.role_id = role_id
        await self.session.flush()

    async def list_memberships(self, workspace_id: uuid.UUID) -> list[Membership]:
        return list(
            (
                await self.session.execute(
                    select(Membership).where(Membership.workspace_id == workspace_id)
                )
            ).scalars()
        )

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
    ) -> SignupRequest:
        signup = SignupRequest(
            workspace_id=workspace_id,
            kind=kind,
            identity_id=identity_id,
            identity_name=identity_name,
            email=email,
            owner_email=owner_email,
            display_name=display_name,
            agent_name=agent_name,
            agent_slug=agent_slug,
            requested_role=requested_role,
            message=message,
        )
        self.session.add(signup)
        await self.session.flush()
        return signup

    async def get_signup_request(
        self, request_id: uuid.UUID
    ) -> SignupRequest | None:
        return await self.session.get(SignupRequest, request_id)

    async def list_signup_requests(
        self, workspace_id: uuid.UUID, *, status: str | None = None
    ) -> list[SignupRequest]:
        query = select(SignupRequest).where(
            SignupRequest.workspace_id == workspace_id
        )
        if status is not None:
            query = query.where(SignupRequest.status == status)
        query = query.order_by(SignupRequest.created_at.desc(), SignupRequest.id.desc())
        return list((await self.session.execute(query)).scalars())

    async def save_signup_request(self, signup: SignupRequest) -> None:
        self.session.add(signup)
        await self.session.flush()

    # resource groups

    async def create_resource_group(
        self,
        *,
        workspace_id: uuid.UUID,
        name: str,
        kind: str,
        description: str | None,
    ) -> ResourceGroup:
        group = ResourceGroup(
            workspace_id=workspace_id,
            name=name,
            kind=kind,
            description=description,
        )
        self.session.add(group)
        await self.session.flush()
        return group

    async def get_resource_group(
        self, group_id: uuid.UUID
    ) -> ResourceGroup | None:
        return await self.session.get(ResourceGroup, group_id)

    async def list_resource_groups(
        self, workspace_id: uuid.UUID
    ) -> list[ResourceGroup]:
        return list(
            (
                await self.session.execute(
                    select(ResourceGroup)
                    .where(ResourceGroup.workspace_id == workspace_id)
                    .order_by(ResourceGroup.name)
                )
            ).scalars()
        )

    async def save_resource_group(self, group: ResourceGroup) -> None:
        self.session.add(group)
        await self.session.flush()

    async def delete_resource_group(self, group: ResourceGroup) -> None:
        await self.session.delete(group)
        await self.session.flush()

    # tracing

    async def record_trace_span(self, span: TraceSpan) -> None:
        self.session.add(span)
        await self.session.flush()

    async def list_recent_spans(
        self, workspace_id: uuid.UUID, *, limit: int = 100
    ) -> list[TraceSpan]:
        return list(
            (
                await self.session.execute(
                    select(TraceSpan)
                    .where(TraceSpan.workspace_id == workspace_id)
                    .order_by(TraceSpan.started_at.desc())
                    .limit(limit)
                )
            ).scalars()
        )

    async def list_trace_roots(
        self,
        workspace_id: uuid.UUID,
        *,
        limit: int = 50,
        offset: int = 0,
        as_of: datetime | None = None,
    ) -> list[TraceSpan]:
        query = select(TraceSpan).where(
            TraceSpan.workspace_id == workspace_id,
            TraceSpan.span_id == "root",
        )
        if as_of is not None:
            query = query.where(TraceSpan.started_at <= as_of)
        query = (
            query.order_by(TraceSpan.started_at.desc(), TraceSpan.trace_id.desc())
            .offset(offset)
            .limit(limit)
        )
        return list((await self.session.execute(query)).scalars())

    async def count_trace_roots(
        self,
        workspace_id: uuid.UUID,
        *,
        as_of: datetime | None = None,
    ) -> int:
        query = (
            select(func.count())
            .select_from(TraceSpan)
            .where(
                TraceSpan.workspace_id == workspace_id,
                TraceSpan.span_id == "root",
            )
        )
        if as_of is not None:
            query = query.where(TraceSpan.started_at <= as_of)
        return int((await self.session.execute(query)).scalar_one())

    async def list_trace_spans(
        self, workspace_id: uuid.UUID, trace_id: str
    ) -> list[TraceSpan]:
        return list(
            (
                await self.session.execute(
                    select(TraceSpan)
                    .where(
                        TraceSpan.workspace_id == workspace_id,
                        TraceSpan.trace_id == trace_id,
                    )
                    .order_by(TraceSpan.started_at)
                )
            ).scalars()
        )

    # bootstrap

    async def get_bootstrap(self) -> BootstrapState | None:
        return await self.session.get(BootstrapState, True)

    async def mark_bootstrapped(
        self, *, user_id: uuid.UUID, method: str, when: datetime
    ) -> BootstrapState:
        state = await self.session.get(BootstrapState, True)
        if state is None:
            state = BootstrapState(id=True)
            self.session.add(state)
        state.completed_at = when
        state.completed_by = user_id
        state.method = method
        await self.session.flush()
        return state

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
    ) -> Agent:
        agent = Agent(
            workspace_id=workspace_id,
            slug=slug,
            name=name,
            kind=kind,
            status=status,
            ceiling=ceiling,
            created_by=created_by,
        )
        self.session.add(agent)
        await self.session.flush()
        return agent

    async def get_agent(self, agent_id: uuid.UUID) -> Agent | None:
        return await self.session.get(Agent, agent_id)

    async def get_agent_by_slug(
        self, workspace_id: uuid.UUID, slug: str
    ) -> Agent | None:
        return (
            await self.session.execute(
                select(Agent).where(
                    Agent.workspace_id == workspace_id, Agent.slug == slug
                )
            )
        ).scalar_one_or_none()

    async def list_agents(
        self, workspace_id: uuid.UUID, *, only_agent_id: uuid.UUID | None = None
    ) -> list[Agent]:
        query = select(Agent).where(Agent.workspace_id == workspace_id)
        if only_agent_id is not None:
            query = query.where(Agent.id == only_agent_id)
        return list(
            (await self.session.execute(query.order_by(Agent.created_at)))
            .scalars()
            .all()
        )

    async def save_agent(self, agent: Agent) -> None:
        self.session.add(agent)
        await self.session.flush()

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
    ) -> AgentCredential:
        credential = AgentCredential(
            agent_id=agent_id,
            type=type,
            prefix=prefix,
            secret_hash=secret_hash,
            cert_fingerprint=cert_fingerprint,
            cert_pem=cert_pem,
            serial_number=serial_number,
            issuer=issuer,
            spiffe_id=spiffe_id,
            expires_at=expires_at,
        )
        self.session.add(credential)
        await self.session.flush()
        return credential

    async def get_credential(
        self, agent_id: uuid.UUID, credential_id: uuid.UUID
    ) -> AgentCredential | None:
        credential = await self.session.get(AgentCredential, credential_id)
        if credential is None or credential.agent_id != agent_id:
            return None
        return credential

    async def get_credential_by_prefix(
        self, prefix: str, credential_type: str
    ) -> AgentCredential | None:
        return (
            await self.session.execute(
                select(AgentCredential).where(
                    AgentCredential.prefix == prefix,
                    AgentCredential.type == credential_type,
                )
            )
        ).scalar_one_or_none()

    async def list_active_credentials(
        self, agent_id: uuid.UUID
    ) -> list[AgentCredential]:
        return list(
            (
                await self.session.execute(
                    select(AgentCredential).where(
                        AgentCredential.agent_id == agent_id,
                        AgentCredential.revoked_at.is_(None),
                    )
                )
            ).scalars().all()
        )

    async def revoke_credential(
        self, credential: AgentCredential, when: datetime
    ) -> None:
        credential.revoked_at = when
        await self.session.flush()

    async def touch_credential(
        self, credential: AgentCredential, when: datetime
    ) -> None:
        credential.last_used_at = when
        await self.session.flush()

    async def revoke_credentials_for_agent(
        self, agent_id: uuid.UUID, when: datetime
    ) -> None:
        credentials = await self.list_active_credentials(agent_id)
        for credential in credentials:
            credential.revoked_at = when
        await self.session.flush()

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
    ) -> EnrollmentToken:
        token = EnrollmentToken(
            workspace_id=workspace_id,
            agent_slug=agent_slug,
            role_id=role_id,
            ceiling=ceiling,
            prefix=prefix,
            secret_hash=secret_hash,
            expires_at=expires_at,
            created_by=created_by,
        )
        self.session.add(token)
        await self.session.flush()
        return token

    async def get_enrollment_token(
        self, token_id: uuid.UUID
    ) -> EnrollmentToken | None:
        return await self.session.get(EnrollmentToken, token_id)

    async def find_enrollment_token_by_prefix(
        self, prefix: str
    ) -> EnrollmentToken | None:
        return (
            await self.session.execute(
                select(EnrollmentToken)
                .where(
                    EnrollmentToken.prefix == prefix,
                    EnrollmentToken.state == "active",
                )
                .with_for_update()
            )
        ).scalar_one_or_none()

    async def consume_enrollment_token(
        self, token: EnrollmentToken, when: datetime
    ) -> bool:
        result = await self.session.execute(
            update(EnrollmentToken)
            .where(EnrollmentToken.id == token.id, EnrollmentToken.state == "active")
            .values(state="consumed", consumed_at=when)
        )
        await self.session.flush()
        return bool(result.rowcount)

    async def set_enrollment_token_state(
        self, token: EnrollmentToken, state: str
    ) -> None:
        token.state = state
        await self.session.flush()

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
    ) -> EnrollmentDeviceCode:
        code = EnrollmentDeviceCode(
            device_code_hash=device_code_hash,
            user_code=user_code,
            agent_name=agent_name,
            requested_role=requested_role,
            expires_at=expires_at,
            interval_seconds=interval_seconds,
        )
        self.session.add(code)
        await self.session.flush()
        return code

    async def get_device_code(
        self, code_id: uuid.UUID
    ) -> EnrollmentDeviceCode | None:
        return await self.session.get(EnrollmentDeviceCode, code_id)

    async def get_device_code_by_user_code(
        self, user_code: str
    ) -> EnrollmentDeviceCode | None:
        return (
            await self.session.execute(
                select(EnrollmentDeviceCode)
                .where(EnrollmentDeviceCode.user_code == user_code)
                .with_for_update()
            )
        ).scalar_one_or_none()

    async def get_device_code_by_hash(
        self, device_code_hash: bytes
    ) -> EnrollmentDeviceCode | None:
        return (
            await self.session.execute(
                select(EnrollmentDeviceCode)
                .where(EnrollmentDeviceCode.device_code_hash == device_code_hash)
                .with_for_update()
            )
        ).scalar_one_or_none()

    async def device_user_code_exists(self, user_code: str) -> bool:
        return (
            await self.session.execute(
                select(EnrollmentDeviceCode.id).where(
                    EnrollmentDeviceCode.user_code == user_code
                )
            )
        ).first() is not None

    async def save_device_code(self, code: EnrollmentDeviceCode) -> None:
        self.session.add(code)
        await self.session.flush()

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
    ) -> UpstreamService:
        service = UpstreamService(
            workspace_id=workspace_id,
            name=name,
            kind=kind,
            endpoint=endpoint,
            auth_type=auth_type,
            credential_policy=credential_policy,
            created_by=created_by,
        )
        self.session.add(service)
        await self.session.flush()
        return service

    async def get_service(self, service_id: uuid.UUID) -> UpstreamService | None:
        return await self.session.get(UpstreamService, service_id)

    async def list_services(self, workspace_id: uuid.UUID) -> list[UpstreamService]:
        return list(
            (
                await self.session.execute(
                    select(UpstreamService)
                    .where(UpstreamService.workspace_id == workspace_id)
                    .order_by(UpstreamService.name)
                )
            ).scalars().all()
        )

    async def list_services_by_ids(
        self, service_ids: Sequence[uuid.UUID]
    ) -> list[UpstreamService]:
        if not service_ids:
            return []
        return list(
            (
                await self.session.execute(
                    select(UpstreamService).where(
                        UpstreamService.id.in_(list(service_ids))
                    )
                )
            ).scalars().all()
        )

    async def save_service(self, service: UpstreamService) -> None:
        self.session.add(service)
        await self.session.flush()

    # tools

    async def list_tools(self, service_id: uuid.UUID) -> list[ServiceTool]:
        return list(
            (
                await self.session.execute(
                    select(ServiceTool)
                    .where(ServiceTool.service_id == service_id)
                    .order_by(ServiceTool.name)
                )
            ).scalars().all()
        )

    async def tool_names(self, service_id: uuid.UUID) -> set[str]:
        return set(
            (
                await self.session.execute(
                    select(ServiceTool.name).where(
                        ServiceTool.service_id == service_id
                    )
                )
            ).scalars().all()
        )

    async def get_tool(
        self, service_id: uuid.UUID, name: str
    ) -> ServiceTool | None:
        return (
            await self.session.execute(
                select(ServiceTool).where(
                    ServiceTool.service_id == service_id, ServiceTool.name == name
                )
            )
        ).scalar_one_or_none()

    async def save_tool(self, tool: ServiceTool) -> None:
        self.session.add(tool)
        await self.session.flush()

    # grants

    async def get_grant(
        self, agent_id: uuid.UUID, service_id: uuid.UUID
    ) -> AgentGrant | None:
        return (
            await self.session.execute(
                select(AgentGrant).where(
                    AgentGrant.agent_id == agent_id,
                    AgentGrant.service_id == service_id,
                )
            )
        ).scalar_one_or_none()

    async def list_grants(self, agent_id: uuid.UUID) -> list[AgentGrant]:
        return list(
            (
                await self.session.execute(
                    select(AgentGrant)
                    .where(AgentGrant.agent_id == agent_id)
                    .order_by(AgentGrant.created_at)
                )
            ).scalars().all()
        )

    async def list_active_grants(self, agent_id: uuid.UUID) -> list[AgentGrant]:
        return list(
            (
                await self.session.execute(
                    select(AgentGrant).where(
                        AgentGrant.agent_id == agent_id,
                        AgentGrant.status == "active",
                    )
                )
            ).scalars().all()
        )

    async def save_grant(self, grant: AgentGrant) -> None:
        self.session.add(grant)
        await self.session.flush()

    async def revoke_grant(self, grant: AgentGrant) -> None:
        grant.status = "revoked"
        await self.session.flush()

    async def revoke_grants_for_agent(self, agent_id: uuid.UUID) -> None:
        grants = await self.list_active_grants(agent_id)
        for grant in grants:
            grant.status = "revoked"
        await self.session.flush()

    async def revoke_grants_for_service(self, service_id: uuid.UUID) -> None:
        grants = (
            await self.session.execute(
                select(AgentGrant).where(
                    AgentGrant.service_id == service_id,
                    AgentGrant.status == "active",
                )
            )
        ).scalars().all()
        for grant in grants:
            grant.status = "revoked"
        await self.session.flush()

    # connections

    async def list_connections(
        self, workspace_id: uuid.UUID, agent_id: uuid.UUID
    ) -> list[ServiceConnection]:
        return list(
            (
                await self.session.execute(
                    select(ServiceConnection).where(
                        ServiceConnection.workspace_id == workspace_id,
                        ServiceConnection.agent_id == agent_id,
                    )
                )
            ).scalars().all()
        )

    # catalog

    async def list_catalog(
        self, workspace_id: uuid.UUID, kind: str | None
    ) -> list[tuple[ServiceTool, UpstreamService]]:
        query = (
            select(ServiceTool, UpstreamService)
            .join(UpstreamService, ServiceTool.service_id == UpstreamService.id)
            .where(
                UpstreamService.workspace_id == workspace_id,
                UpstreamService.status == "active",
            )
        )
        if kind:
            query = query.where(UpstreamService.kind == kind)
        rows = (
            await self.session.execute(query.order_by(ServiceTool.name).limit(2000))
        ).all()
        return [(tool, service) for tool, service in rows]

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
    ) -> AuditEvent:
        event = AuditEvent(
            workspace_id=workspace_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            decision=decision,
            reason=reason,
            trace_id=trace_id,
            meta=meta or {},
        )
        self.session.add(event)
        await self.session.flush()
        return event

    def _audit_query(
        self,
        workspace_id: uuid.UUID,
        *,
        since: datetime | None = None,
        decision: str | None = None,
        as_of: datetime | None = None,
    ):
        query = select(AuditEvent).where(AuditEvent.workspace_id == workspace_id)
        if since is not None:
            query = query.where(AuditEvent.created_at >= since)
        if decision is not None:
            query = query.where(AuditEvent.decision == decision)
        if as_of is not None:
            query = query.where(AuditEvent.created_at <= as_of)
        return query

    async def list_audit(
        self,
        workspace_id: uuid.UUID,
        *,
        since: datetime | None = None,
        decision: str | None = None,
        limit: int = 100,
        offset: int = 0,
        as_of: datetime | None = None,
    ) -> list[AuditEvent]:
        query = (
            self._audit_query(
                workspace_id,
                since=since,
                decision=decision,
                as_of=as_of,
            )
            .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return list((await self.session.execute(query)).scalars().all())

    async def count_audit(
        self,
        workspace_id: uuid.UUID,
        *,
        since: datetime | None = None,
        decision: str | None = None,
        as_of: datetime | None = None,
    ) -> int:
        query = self._audit_query(
            workspace_id,
            since=since,
            decision=decision,
            as_of=as_of,
        ).with_only_columns(func.count()).select_from(AuditEvent)
        return int((await self.session.execute(query)).scalar_one())


class SqlStoreProvider:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.engine = build_engine(settings)
        self.sessionmaker: async_sessionmaker[AsyncSession] = build_sessionmaker(
            self.engine
        )

    async def startup(self, *, create_tables: bool = False) -> None:
        if create_tables:
            from agw.db.session import init_db

            await init_db(self.engine, seed=False)
        async with self.sessionmaker() as session:
            await seed_builtin_roles(SqlStore(session))

    async def shutdown(self) -> None:
        await self.engine.dispose()

    @asynccontextmanager
    async def store(self) -> AsyncIterator[Store]:
        async with self.sessionmaker() as session:
            yield SqlStore(session)


__all__ = ["SqlStore", "SqlStoreProvider"]
