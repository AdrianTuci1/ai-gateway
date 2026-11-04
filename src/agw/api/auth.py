from __future__ import annotations

import secrets
import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, Request

from agw.api.deps import get_principal, get_settings, get_store
from agw.api.identity_service import (
    agent_identity_name,
    ensure_principal_identity,
    user_identity_name,
)
from agw.api.schemas import (
    AuthConfigOut,
    BootstrapRequest,
    BootstrapResponse,
    DeviceApproveRequest,
    DeviceStartRequest,
    DeviceStartResponse,
    DeviceTokenRequest,
    DevLoginRequest,
    EnrollRequest,
    EnrollResponse,
    PasswordLoginRequest,
    TokenResponse,
    UserOut,
    WorkspaceOut,
)
from agw.audit.service import record
from agw.config import Settings
from agw.core.errors import ApiError, not_found
from agw.core.security import (
    constant_time_equals,
    create_session_token,
    hash_opaque,
    hash_secret,
    new_opaque,
    new_token,
    parse_token,
    verify_secret,
)
from agw.core.time import utcnow
from agw.db.models import Agent, RoleDefinition
from agw.policy.engine import Principal, require_permission
from agw.store.base import Store

router = APIRouter()


def _base_url(request: Request, settings: Settings) -> str:
    base = settings.public_base_url.rstrip("/")
    if base:
        return base
    return str(request.base_url).rstrip("/")

_USER_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _user_code() -> str:
    raw = "".join(secrets.choice(_USER_CODE_ALPHABET) for _ in range(8))
    return f"{raw[:4]}-{raw[4:]}"


async def _resolve_role(
    store: Store, workspace_id: uuid.UUID, name: str
) -> RoleDefinition:
    role = await store.resolve_role(workspace_id, name)
    if role is None:
        raise ApiError(422, "invalid_role", f"unknown role: {name}")
    return role


def ensure_agent_role(role: RoleDefinition) -> None:
    if role.is_builtin and not role.name.startswith("agent:"):
        raise ApiError(422, "invalid_role", "human roles cannot be assigned to agents")


async def issue_credential(
    request: Request,
    store: Store,
    agent: Agent,
    credential_type: str,
    csr_pem: str | None,
) -> dict:
    if credential_type == "api_key":
        token, prefix, secret = new_token("live")
        credential = await store.create_credential(
            agent_id=agent.id,
            type="api_key",
            prefix=prefix,
            secret_hash=hash_secret(secret),
            expires_at=utcnow() + timedelta(days=90),
        )
        return {
            "id": credential.id,
            "type": "api_key",
            "api_key": token,
            "prefix": prefix,
            "expires_at": credential.expires_at,
        }

    if not csr_pem:
        raise ApiError(422, "invalid_request", "csr_pem is required for client_cert")
    ca = request.app.state.ca
    if ca is None:
        raise ApiError(501, "feature_unavailable", "certificate authority is not configured")
    workspace = await store.get_workspace(agent.workspace_id)
    spiffe_id = f"spiffe://{workspace.slug}/agent/{agent.id}"
    try:
        issued = ca.issue(
            csr_pem,
            spiffe_id=spiffe_id,
            ttl_hours=request.app.state.settings.agent_cert_ttl_hours,
        )
    except ValueError as exc:
        raise ApiError(422, "invalid_request", f"invalid CSR: {exc}") from exc
    credential = await store.create_credential(
        agent_id=agent.id,
        type="client_cert",
        cert_fingerprint=issued.fingerprint_sha256,
        cert_pem=issued.certificate_pem,
        serial_number=issued.serial_number,
        issuer="internal",
        spiffe_id=spiffe_id,
        expires_at=issued.expires_at,
    )
    return {
        "id": credential.id,
        "type": "client_cert",
        "certificate_pem": issued.certificate_pem,
        "ca_chain_pem": [ca.certificate_pem],
        "spiffe_id": spiffe_id,
        "expires_at": issued.expires_at,
    }


@router.post("/v1/bootstrap", response_model=BootstrapResponse)
async def bootstrap(
    body: BootstrapRequest,
    request: Request,
    store: Store = Depends(get_store),
    settings: Settings = Depends(get_settings),
) -> BootstrapResponse:
    if not settings.bootstrap_enabled:
        raise ApiError(403, "bootstrap_disabled", "HTTP bootstrap is disabled")
    supplied = request.headers.get("x-bootstrap-token", "")
    expected = settings.bootstrap_token.get_secret_value() if settings.bootstrap_token else ""
    if not constant_time_equals(supplied, expected):
        raise ApiError(401, "unauthenticated", "invalid bootstrap token")

    existing = await store.count_workspaces()
    state = await store.get_bootstrap()
    if existing or (state and state.completed_at):
        raise ApiError(410, "bootstrap_closed", "the gateway is already initialized")

    workspace = await store.create_workspace(
        slug=body.workspace_slug, name=body.workspace_name
    )
    user = await store.create_user(
        email=body.owner_email.lower(),
        idp_subject=f"local:{body.owner_email.lower()}",
        display_name=body.owner_name,
    )
    if body.password:
        user.password_hash = hash_secret(body.password)
        await store.save_user(user)
    owner_role = await store.get_builtin_role("owner")
    identity = await store.create_identity(
        workspace_id=workspace.id, name=user_identity_name(user), status="active"
    )
    await store.create_membership(
        workspace_id=workspace.id,
        principal_type="user",
        principal_id=user.id,
        role_id=owner_role.id,
        identity_id=identity.id,
        is_identity_admin=True,
    )
    await store.mark_bootstrapped(
        user_id=user.id, method="http_token", when=utcnow()
    )
    await record(
        store,
        workspace_id=workspace.id,
        actor_type="user",
        actor_id=user.id,
        action="bootstrap.completed",
        resource_type="workspace",
        resource_id=str(workspace.id),
        trace_id=request.state.trace_id,
    )
    token = create_session_token(
        user.id, workspace.id, settings.session_secret, settings.session_ttl_hours
    )
    await store.commit()
    return BootstrapResponse(
        workspace=WorkspaceOut.model_validate(workspace),
        user=UserOut.model_validate(user),
        token=token,
        expires_in=settings.session_ttl_hours * 3600,
    )


@router.get("/v1/auth/config", response_model=AuthConfigOut)
async def auth_config(
    settings: Settings = Depends(get_settings),
) -> AuthConfigOut:
    return AuthConfigOut(
        password=settings.password_auth_enabled,
        google=bool(settings.google_client_id and settings.google_client_secret),
        dev=settings.dev_auth,
    )


@router.post("/v1/auth/login", response_model=TokenResponse)
async def password_login(
    body: PasswordLoginRequest,
    request: Request,
    store: Store = Depends(get_store),
    settings: Settings = Depends(get_settings),
) -> TokenResponse:
    if not settings.password_auth_enabled:
        raise not_found("endpoint")
    email = body.email.strip().lower()
    user = await store.get_user_by_email(email)
    workspace = await store.get_workspace_by_slug(body.workspace_slug)
    if (
        user is None
        or workspace is None
        or not verify_secret(user.password_hash, body.password)
    ):
        raise ApiError(401, "invalid_credentials", "e-mail or password is incorrect")
    membership = await store.get_membership(workspace.id, "user", user.id)
    if membership is None:
        raise ApiError(403, "forbidden", "user is not a member of this workspace")
    if membership.status == "pending":
        raise ApiError(
            403, "approval_pending", "your access request is waiting for approval"
        )
    if membership.status == "rejected":
        raise ApiError(403, "signup_rejected", "your access request was rejected")
    token = create_session_token(
        user.id, workspace.id, settings.session_secret, settings.session_ttl_hours
    )
    await record(
        store,
        workspace_id=workspace.id,
        actor_type="user",
        actor_id=user.id,
        action="auth.login",
        resource_type="user",
        resource_id=str(user.id),
        trace_id=request.state.trace_id,
        meta={"method": "password"},
    )
    await store.commit()
    return TokenResponse(token=token, expires_in=settings.session_ttl_hours * 3600)


@router.post("/v1/auth/dev-login", response_model=TokenResponse)
async def dev_login(
    body: DevLoginRequest,
    request: Request,
    store: Store = Depends(get_store),
    settings: Settings = Depends(get_settings),
) -> TokenResponse:
    if not settings.dev_auth:
        raise not_found("endpoint")
    user = await store.get_user_by_email(body.email.lower())
    workspace = await store.get_workspace_by_slug(body.workspace_slug)
    if user is None or workspace is None:
        raise not_found("user or workspace")
    membership = await store.get_membership(
        workspace.id, "user", user.id
    )
    if membership is None:
        raise ApiError(403, "forbidden", "user is not a member of this workspace")
    if membership.status == "pending":
        raise ApiError(
            403, "approval_pending", "your access request is waiting for approval"
        )
    if membership.status == "rejected":
        raise ApiError(403, "signup_rejected", "your access request was rejected")
    token = create_session_token(
        user.id, workspace.id, settings.session_secret, settings.session_ttl_hours
    )
    return TokenResponse(token=token, expires_in=settings.session_ttl_hours * 3600)


@router.post("/v1/enroll", response_model=EnrollResponse)
async def enroll(
    body: EnrollRequest,
    request: Request,
    store: Store = Depends(get_store),
    settings: Settings = Depends(get_settings),
) -> EnrollResponse:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise ApiError(401, "enrollment_required", "enrollment token required")
    parsed = parse_token(header[7:].strip(), "enroll")
    if parsed is None:
        raise ApiError(401, "enrollment_token_invalid", "enrollment token is invalid")
    prefix, secret = parsed
    token = await store.find_enrollment_token_by_prefix(prefix)
    if token is None or token.expires_at <= utcnow():
        raise ApiError(401, "enrollment_token_invalid", "enrollment token is invalid")
    if not verify_secret(token.secret_hash, secret):
        raise ApiError(401, "enrollment_token_invalid", "enrollment token is invalid")
    if body.agent_slug != token.agent_slug:
        raise ApiError(401, "enrollment_token_invalid", "enrollment token is invalid")

    agent = None
    if token.agent_id is not None:
        agent = await store.get_agent(token.agent_id)
    if agent is None:
        agent = await store.get_agent_by_slug(token.workspace_id, token.agent_slug)
    if agent is None:
        agent = await store.create_agent(
            workspace_id=token.workspace_id,
            slug=token.agent_slug,
            name=token.agent_slug,
            kind="autonomous",
            ceiling=token.ceiling or {},
            created_by=token.created_by,
        )
    membership = await store.get_membership(
        token.workspace_id, "agent", agent.id
    )
    if membership is None:
        identity = None
        creator_user = await store.get_user(token.created_by)
        if creator_user is not None:
            identity = await ensure_principal_identity(
                store,
                workspace_id=token.workspace_id,
                principal_type="user",
                principal_id=creator_user.id,
                name=user_identity_name(creator_user),
            )
        else:
            creator_agent = await store.get_agent(token.created_by)
            if creator_agent is not None:
                identity = await ensure_principal_identity(
                    store,
                    workspace_id=token.workspace_id,
                    principal_type="agent",
                    principal_id=creator_agent.id,
                    name=agent_identity_name(creator_agent),
                )
        is_admin = identity is None
        if identity is None:
            identity = await store.create_identity(
                workspace_id=token.workspace_id,
                name=agent.name,
                status="active",
            )
        await store.create_membership(
            workspace_id=token.workspace_id,
            principal_type="agent",
            principal_id=agent.id,
            role_id=token.role_id,
            identity_id=identity.id,
            is_identity_admin=is_admin,
        )

    credential = await issue_credential(
        request, store, agent, body.credential_type, body.csr_pem
    )
    if not await store.consume_enrollment_token(token, utcnow()):
        raise ApiError(401, "enrollment_token_invalid", "enrollment token is invalid")
    await record(
        store,
        workspace_id=token.workspace_id,
        actor_type="agent",
        actor_id=agent.id,
        action="enrollment.consumed",
        resource_type="agent",
        resource_id=str(agent.id),
        trace_id=request.state.trace_id,
        meta={"credential_type": body.credential_type},
    )
    await store.commit()
    base = _base_url(request, settings)
    return EnrollResponse(
        agent_id=agent.id,
        workspace_id=agent.workspace_id,
        credential=credential,
        runtime={"mcp_url": f"{base}/mcp/{agent.slug}"},
        renewal=(
            {"url": "/v1/agent/credentials/renew", "after_seconds": 43200}
            if body.credential_type == "client_cert"
            else None
        ),
    )


@router.post("/v1/enroll/device", response_model=DeviceStartResponse)
async def device_start(
    body: DeviceStartRequest,
    request: Request,
    store: Store = Depends(get_store),
    settings: Settings = Depends(get_settings),
) -> DeviceStartResponse:
    device_code = new_opaque(32)
    user_code = _user_code()
    for _ in range(5):
        if not await store.device_user_code_exists(user_code):
            break
        user_code = _user_code()
    code = await store.create_device_code(
        device_code_hash=hash_opaque(device_code),
        user_code=user_code,
        agent_name=body.agent_name,
        requested_role=body.requested_role,
        expires_at=utcnow() + timedelta(seconds=settings.device_code_ttl_seconds),
        interval_seconds=settings.device_code_interval_seconds,
    )
    await store.commit()
    base = _base_url(request, settings)
    return DeviceStartResponse(
        device_code=device_code,
        user_code=code.user_code,
        verification_uri=f"{base}/activate",
        expires_in=settings.device_code_ttl_seconds,
        interval=settings.device_code_interval_seconds,
    )


@router.post("/v1/enroll/device/approve")
async def device_approve(
    body: DeviceApproveRequest,
    request: Request,
    principal: Principal = Depends(get_principal),
    store: Store = Depends(get_store),
) -> dict:
    require_permission(principal, "agent:create")
    code = await store.get_device_code_by_user_code(body.user_code.upper())
    if code is None or code.expires_at <= utcnow() or code.status != "pending":
        raise not_found("device code")
    workspace = await store.get_workspace_by_slug(body.workspace_slug)
    if workspace is None or workspace.id != principal.workspace_id:
        raise not_found("workspace")
    code.attempts += 1
    if code.attempts > 5:
        code.status = "expired"
        await store.save_device_code(code)
        await store.commit()
        raise ApiError(429, "rate_limited", "too many attempts")
    role = await _resolve_role(store, workspace.id, body.role)
    ensure_agent_role(role)
    slug = body.agent_slug or code.agent_name.lower().replace(" ", "-")[:60]
    agent = await store.get_agent_by_slug(workspace.id, slug)
    if agent is None:
        agent = await store.create_agent(
            workspace_id=workspace.id,
            slug=slug,
            name=code.agent_name,
            kind="interactive",
            ceiling=body.ceiling,
            created_by=principal.id,
        )
        approver_name = principal.identity_name
        if approver_name is None:
            if principal.kind == "user":
                approver = await store.get_user(principal.id)
                approver_name = user_identity_name(approver) if approver else "identity"
            else:
                approver = await store.get_agent(principal.id)
                approver_name = (
                    agent_identity_name(approver) if approver else "identity"
                )
        identity = await ensure_principal_identity(
            store,
            workspace_id=workspace.id,
            principal_type=principal.kind,
            principal_id=principal.id,
            name=approver_name,
        )
        is_admin = identity is None
        if identity is None:
            identity = await store.create_identity(
                workspace_id=workspace.id,
                name=code.agent_name,
                status="active",
            )
        await store.create_membership(
            workspace_id=workspace.id,
            principal_type="agent",
            principal_id=agent.id,
            role_id=role.id,
            identity_id=identity.id,
            is_identity_admin=is_admin,
        )
    code.status = "approved"
    code.workspace_id = workspace.id
    code.approved_agent = agent.id
    code.approved_by = principal.id
    await store.save_device_code(code)
    await record(
        store,
        workspace_id=workspace.id,
        actor_type=principal.kind,
        actor_id=principal.id,
        action="enrollment.approved",
        resource_type="agent",
        resource_id=str(agent.id),
        trace_id=request.state.trace_id,
    )
    await store.commit()
    return {"status": "approved", "agent_id": str(agent.id), "agent_slug": agent.slug}


@router.post("/v1/enroll/device/token")
async def device_token(
    body: DeviceTokenRequest,
    request: Request,
    store: Store = Depends(get_store),
    settings: Settings = Depends(get_settings),
) -> dict:
    code = await store.get_device_code_by_hash(hash_opaque(body.device_code))
    if code is None or code.expires_at <= utcnow():
        raise ApiError(401, "enrollment_token_invalid", "device code is invalid")
    now = utcnow()
    if code.status == "pending":
        if code.last_polled_at and now - code.last_polled_at < timedelta(
            seconds=code.interval_seconds
        ):
            raise ApiError(429, "slow_down", "poll slower")
        code.last_polled_at = now
        await store.save_device_code(code)
        await store.commit()
        raise ApiError(409, "authorization_pending", "the device code is not approved yet")
    if code.status != "approved" or code.approved_agent is None:
        raise ApiError(401, "enrollment_token_invalid", "device code is invalid")
    agent = await store.get_agent(code.approved_agent)
    if agent is None:
        raise ApiError(401, "enrollment_token_invalid", "device code is invalid")
    credential = await issue_credential(
        request, store, agent, body.credential_type, body.csr_pem
    )
    code.status = "consumed"
    await store.save_device_code(code)
    await record(
        store,
        workspace_id=agent.workspace_id,
        actor_type="agent",
        actor_id=agent.id,
        action="enrollment.device_consumed",
        resource_type="agent",
        resource_id=str(agent.id),
        trace_id=request.state.trace_id,
    )
    await store.commit()
    base = _base_url(request, settings)
    return {
        "agent_id": str(agent.id),
        "workspace_id": str(agent.workspace_id),
        "credential": credential,
        "runtime": {"mcp_url": f"{base}/mcp/{agent.slug}"},
    }
