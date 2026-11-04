from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi import APIRouter, Depends, Request

from agw.api.deps import get_principal, get_settings, get_store
from agw.api.schemas import MeOut, RuntimeOut
from agw.config import Settings
from agw.core.runtime import runtime_payload
from agw.policy.engine import Principal
from agw.store.base import Store

router = APIRouter()


@router.get("/healthz")
async def healthz(store: Store = Depends(get_store)) -> dict[str, str]:
    await store.ping()
    return {"status": "ok"}


@router.get("/v1/runtime", response_model=RuntimeOut)
async def runtime(settings: Settings = Depends(get_settings)) -> dict:
    return runtime_payload(settings)


@router.get("/v1/me", response_model=MeOut)
async def me(
    principal: Principal = Depends(get_principal),
    store: Store = Depends(get_store),
) -> MeOut:
    workspace = await store.get_workspace(principal.workspace_id)
    return MeOut(
        kind=principal.kind,
        id=principal.id,
        workspace_id=principal.workspace_id,
        workspace_slug=workspace.slug if workspace else None,
        role=principal.role,
        permissions=sorted(principal.permissions),
        agent_id=principal.agent_id,
        email=principal.email,
        identity_id=principal.identity_id,
        identity_name=principal.identity_name,
        is_identity_admin=principal.is_identity_admin,
    )


def _ca_fingerprint(settings: Settings) -> str | None:
    if not settings.ca_enabled:
        return None
    cert_path = Path(settings.ca_dir) / "ca_cert.pem"
    if not cert_path.exists():
        return None
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization

    cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
    der = cert.public_bytes(serialization.Encoding.DER)
    return hashlib.sha256(der).hexdigest()


@router.get("/.well-known/agw")
async def discovery(
    request: Request, settings: Settings = Depends(get_settings)
) -> dict:
    base = settings.public_base_url.rstrip("/") or str(request.base_url).rstrip("/")
    payload = {
        "api_version": "v1",
        "protocols": {"mcp": "2025-06-18", "a2a": "0.2"},
        "auth": {
            "agent": ["mtls", "api_key"],
            "enrollment": ["token", "device_code"],
            "user": ["session"],
        },
        "endpoints": {
            "enroll": f"{base}/v1/enroll",
            "device_authorization": f"{base}/v1/enroll/device",
            "device_token": f"{base}/v1/enroll/device/token",
            "mcp": f"{base}/mcp/{{agent_slug}}",
            "catalog": f"{base}/v1/catalog",
        },
        "runtime": settings.runtime.value,
        "onboarding": (
            "No credential? Ask your operator for an enrollment token, "
            "or start device enrollment."
        ),
    }
    fingerprint = _ca_fingerprint(settings)
    if fingerprint:
        payload["trust"] = {"ca_fingerprint_sha256": fingerprint}
    return payload
