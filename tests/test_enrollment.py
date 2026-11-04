from __future__ import annotations

import uuid

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from agw.config import Settings
from agw.main import create_app


def _csr(slug: str) -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    csr = (
        x509.CertificateSigningRequestBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, slug)]))
        .sign(key, hashes.SHA256())
    )
    return csr.public_bytes(serialization.Encoding.PEM).decode()


async def test_enrollment_token_is_single_use(client: AsyncClient, admin: dict):
    response = await client.post(
        f"/v1/workspaces/{admin['workspace']}/enrollment-tokens",
        headers=admin["headers"],
        json={"agent_slug": "cert-agent", "role": "agent:executor"},
    )
    assert response.status_code == 201, response.text
    token = response.json()["token"]

    body = {
        "agent_slug": "cert-agent",
        "credential_type": "client_cert",
        "csr_pem": _csr("cert-agent"),
    }
    response = await client.post(
        "/v1/enroll", headers={"Authorization": f"Bearer {token}"}, json=body
    )
    assert response.status_code == 200, response.text
    credential = response.json()["credential"]
    assert credential["type"] == "client_cert"
    assert "BEGIN CERTIFICATE" in credential["certificate_pem"]
    assert credential["spiffe_id"].startswith("spiffe://acme/agent/")

    response = await client.post(
        "/v1/enroll", headers={"Authorization": f"Bearer {token}"}, json=body
    )
    assert response.status_code == 401
    assert response.json()["error"] == "enrollment_token_invalid"


async def test_enrollment_api_key_and_auth(client: AsyncClient, admin: dict):
    response = await client.post(
        f"/v1/workspaces/{admin['workspace']}/enrollment-tokens",
        headers=admin["headers"],
        json={"agent_slug": "worker", "role": "agent:requester"},
    )
    token = response.json()["token"]
    response = await client.post(
        "/v1/enroll",
        headers={"Authorization": f"Bearer {token}"},
        json={"agent_slug": "worker", "credential_type": "api_key"},
    )
    assert response.status_code == 200, response.text
    api_key = response.json()["credential"]["api_key"]
    me = await client.get("/v1/me", headers={"Authorization": f"Bearer {api_key}"})
    assert me.status_code == 200
    assert me.json()["role"] == "agent:requester"


@pytest.mark.asyncio
async def test_cert_enrollment_requires_ca(tmp_path):
    settings = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        db_driver="sqlite",
        secret_key=SecretStr("test-secret-key-that-is-long-enough-1234"),
        bootstrap_enabled=True,
        bootstrap_token=SecretStr("bootstrap-token"),
        auto_create=True,
        ca_enabled=False,
        ca_dir=tmp_path / "ca",
    )
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = await client.post(
                "/v1/bootstrap",
                headers={"X-Bootstrap-Token": "bootstrap-token"},
                json={
                    "workspace_slug": "acme",
                    "workspace_name": "Acme",
                    "owner_email": "owner@example.com",
                },
            )
            headers = {"Authorization": f"Bearer {response.json()['token']}"}

            response = await client.post(
                "/v1/workspaces/acme/enrollment-tokens",
                headers=headers,
                json={"agent_slug": "edge-agent", "role": "agent:executor"},
            )
            token = response.json()["token"]

            response = await client.post(
                "/v1/enroll",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "agent_slug": "edge-agent",
                    "credential_type": "client_cert",
                    "csr_pem": _csr("edge-agent"),
                },
            )
            assert response.status_code == 501
            assert response.json()["error"] == "feature_unavailable"


async def test_device_flow(client: AsyncClient, admin: dict):
    response = await client.post(
        "/v1/enroll/device",
        json={"agent_name": "laptop-agent", "requested_role": "agent:executor"},
    )
    assert response.status_code == 200, response.text
    started = response.json()

    response = await client.post(
        "/v1/enroll/device/token", json={"device_code": started["device_code"]}
    )
    assert response.status_code == 409
    assert response.json()["error"] == "authorization_pending"

    response = await client.post(
        "/v1/enroll/device/approve",
        headers=admin["headers"],
        json={
            "user_code": started["user_code"],
            "workspace_slug": admin["workspace"],
            "role": "agent:executor",
            "agent_slug": "laptop-agent",
        },
    )
    assert response.status_code == 200, response.text

    response = await client.post(
        "/v1/enroll/device/token", json={"device_code": started["device_code"]}
    )
    assert response.status_code == 200, response.text
    api_key = response.json()["credential"]["api_key"]
    me = await client.get("/v1/me", headers={"Authorization": f"Bearer {api_key}"})
    assert me.status_code == 200
    assert me.json()["kind"] == "agent"
