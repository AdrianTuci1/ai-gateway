from __future__ import annotations

from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import jwt
import pytest
from httpx import AsyncClient
from pydantic import SecretStr

from agw.api import oidc
from agw.config import Settings
from agw.core.errors import ApiError


async def _password_login(
    client: AsyncClient, *, email: str, password: str, workspace: str = "acme"
):
    return await client.post(
        "/v1/auth/login",
        json={
            "workspace_slug": workspace,
            "email": email,
            "password": password,
        },
    )


async def test_owner_signs_in_with_password(client: AsyncClient, admin: dict):
    response = await _password_login(
        client, email="owner@example.com", password="owner-password"
    )
    assert response.status_code == 200, response.text
    me = await client.get(
        "/v1/me",
        headers={"Authorization": f"Bearer {response.json()['token']}"},
    )
    assert me.status_code == 200
    assert me.json()["email"] == "owner@example.com"

    wrong = await _password_login(
        client, email="owner@example.com", password="wrong-password"
    )
    assert wrong.status_code == 401, wrong.text
    assert wrong.json()["error"] == "invalid_credentials"

    unknown = await _password_login(
        client, email="nobody@example.com", password="owner-password"
    )
    assert unknown.status_code == 401, unknown.text


async def test_signup_password_works_after_approval(client: AsyncClient, admin: dict):
    created = await client.post(
        "/v1/workspaces/acme/signup",
        json={
            "kind": "user",
            "email": "dana@example.com",
            "display_name": "Dana",
            "password": "dana-password",
        },
    )
    assert created.status_code == 201, created.text

    pending = await _password_login(
        client, email="dana@example.com", password="dana-password"
    )
    assert pending.status_code == 403
    assert pending.json()["error"] == "approval_pending"

    approved = await client.post(
        f"/v1/workspaces/acme/signups/{created.json()['id']}/approve",
        headers=admin["headers"],
        json={"role": "viewer"},
    )
    assert approved.status_code == 200, approved.text

    signed_in = await _password_login(
        client, email="dana@example.com", password="dana-password"
    )
    assert signed_in.status_code == 200, signed_in.text
    me = await client.get(
        "/v1/me",
        headers={"Authorization": f"Bearer {signed_in.json()['token']}"},
    )
    assert me.status_code == 200
    assert me.json()["role"] == "viewer"


async def test_claim_sets_a_password(client: AsyncClient, admin: dict):
    agent_signup = await client.post(
        "/v1/workspaces/acme/signup",
        json={
            "kind": "agent",
            "agent_name": "Research Bot",
            "agent_slug": "research-bot",
            "identity_name": "Dana",
            "owner_email": "dana@example.com",
            "requested_role": "agent:requester",
        },
    )
    assert agent_signup.status_code == 201, agent_signup.text
    approved_agent = await client.post(
        f"/v1/workspaces/acme/signups/{agent_signup.json()['id']}/approve",
        headers=admin["headers"],
        json={"role": "agent:requester"},
    )
    assert approved_agent.status_code == 200, approved_agent.text
    identity_id = approved_agent.json()["request"]["identity_id"]

    invite = await client.post(
        f"/v1/workspaces/acme/identity-groups/{identity_id}/invites",
        headers=admin["headers"],
        json={"email": "dana@example.com", "role": "viewer"},
    )
    assert invite.status_code == 201, invite.text
    token = invite.json()["invite_url"].rsplit("/", 1)[-1]

    accepted = await client.post(
        f"/v1/identity-invites/{token}/accept",
        json={"display_name": "Dana", "password": "dana-password"},
    )
    assert accepted.status_code == 200, accepted.text

    signed_in = await _password_login(
        client, email="dana@example.com", password="dana-password"
    )
    assert signed_in.status_code == 200, signed_in.text


async def test_auth_config_reports_enabled_methods(
    client: AsyncClient, settings: Settings
):
    response = await client.get("/v1/auth/config")
    assert response.status_code == 200
    assert response.json() == {"password": True, "google": False, "dev": True}

    settings.google_client_id = "google-client"
    settings.google_client_secret = SecretStr("google-secret")
    response = await client.get("/v1/auth/config")
    assert response.json()["google"] is True


async def test_google_start_requires_configuration(
    client: AsyncClient, settings: Settings
):
    response = await client.get(
        "/v1/auth/oidc/google/start", params={"workspace_slug": "acme"}
    )
    assert response.status_code == 503
    assert response.json()["error"] == "oidc_unavailable"


async def test_google_start_builds_state(
    client: AsyncClient, settings: Settings, admin: dict
):
    settings.google_client_id = "google-client"
    settings.google_client_secret = SecretStr("google-secret")
    response = await client.get(
        "/v1/auth/oidc/google/start",
        params={"workspace_slug": "acme", "next": "/identities"},
    )
    assert response.status_code == 303, response.text
    location = response.headers["location"]
    parsed = urlparse(location)
    assert parsed.netloc == "accounts.google.com"
    query = parse_qs(parsed.query)
    assert query["client_id"] == ["google-client"]
    assert query["redirect_uri"] == [
        "http://testserver/v1/auth/oidc/google/callback"
    ]
    state = jwt.decode(
        query["state"][0], settings.session_secret, algorithms=["HS256"]
    )
    assert state["typ"] == "oidc_state"
    assert state["ws"] == "acme"
    assert state["next"] == "/identities"
    assert state["nonce"]


async def test_google_callback_issues_a_session(
    client: AsyncClient, settings: Settings, admin: dict, monkeypatch: pytest.MonkeyPatch
):
    settings.google_client_id = "google-client"
    settings.google_client_secret = SecretStr("google-secret")
    start = await client.get(
        "/v1/auth/oidc/google/start", params={"workspace_slug": "acme"}
    )
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
    expected_nonce = jwt.decode(
        state, settings.session_secret, algorithms=["HS256"]
    )["nonce"]

    async def fake_exchange(settings, *, code, redirect_uri):
        assert code == "google-code"
        return {"id_token": "fake-id-token"}

    def fake_verify(settings, id_token, *, nonce):
        assert id_token == "fake-id-token"
        assert nonce == expected_nonce
        return {
            "email": "owner@example.com",
            "email_verified": True,
            "nonce": nonce,
        }

    monkeypatch.setattr(oidc, "exchange_google_code", fake_exchange)
    monkeypatch.setattr(oidc, "verify_google_id_token", fake_verify)

    callback = await client.get(
        "/v1/auth/oidc/google/callback",
        params={"code": "google-code", "state": state},
    )
    assert callback.status_code == 303, callback.text
    location = callback.headers["location"]
    assert location.startswith("http://testserver/#")
    fragment = parse_qs(urlparse(location).fragment)
    token = fragment["sso"][0]
    me = await client.get(
        "/v1/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert me.status_code == 200, me.text
    assert me.json()["email"] == "owner@example.com"


def test_google_id_token_restricts_domain(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
):
    settings.google_client_id = "google-client"
    settings.google_client_secret = SecretStr("google-secret")
    settings.google_allowed_domains = "gmail.com"
    monkeypatch.setattr(
        oidc._jwks,
        "get_signing_key_from_jwt",
        lambda token: SimpleNamespace(key="signing-key"),
    )

    def claims_for(email: str) -> dict:
        return {
            "iss": "https://accounts.google.com",
            "email": email,
            "email_verified": True,
            "nonce": "nonce-1",
        }

    monkeypatch.setattr(
        oidc.jwt, "decode", lambda *args, **kwargs: claims_for("dana@example.com")
    )
    with pytest.raises(ApiError) as rejected:
        oidc.verify_google_id_token(settings, "id-token", nonce="nonce-1")
    assert rejected.value.code == "oidc_domain_not_allowed"

    monkeypatch.setattr(
        oidc.jwt, "decode", lambda *args, **kwargs: claims_for("dana@gmail.com")
    )
    claims = oidc.verify_google_id_token(settings, "id-token", nonce="nonce-1")
    assert claims["email"] == "dana@gmail.com"


async def test_google_callback_rejects_unknown_account(
    client: AsyncClient,
    settings: Settings,
    admin: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    settings.google_client_id = "google-client"
    settings.google_client_secret = SecretStr("google-secret")
    start = await client.get(
        "/v1/auth/oidc/google/start", params={"workspace_slug": "acme"}
    )
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]

    async def fake_exchange(settings, *, code, redirect_uri):
        return {"id_token": "fake-id-token"}

    def fake_verify(settings, id_token, *, nonce):
        return {"email": "stranger@example.com", "email_verified": True, "nonce": nonce}

    monkeypatch.setattr(oidc, "exchange_google_code", fake_exchange)
    monkeypatch.setattr(oidc, "verify_google_id_token", fake_verify)

    callback = await client.get(
        "/v1/auth/oidc/google/callback",
        params={"code": "google-code", "state": state},
    )
    assert callback.status_code == 303
    assert callback.headers["location"] == "http://testserver/?sso_error=no_account"
