from __future__ import annotations

from httpx import AsyncClient


async def _signup(client: AsyncClient, ws: str, **body) -> dict:
    response = await client.post(f"/v1/workspaces/{ws}/signup", json=body)
    assert response.status_code == 201, response.text
    return response.json()


async def _login(client: AsyncClient, ws: str, email: str) -> dict:
    return await client.post(
        "/v1/auth/dev-login", json={"workspace_slug": ws, "email": email}
    )


async def test_person_signup_waits_for_approval(client: AsyncClient, admin: dict):
    ws = admin["workspace"]
    headers = admin["headers"]
    created = await _signup(
        client,
        ws,
        kind="user",
        email="Dana@Example.com",
        display_name="Dana",
        message="I need to review tool calls.",
    )
    assert created["status"] == "pending"
    assert created["email"] == "dana@example.com"

    blocked = await _login(client, ws, "dana@example.com")
    assert blocked.status_code == 403, blocked.text
    assert blocked.json()["error"] == "approval_pending"

    while_pending = await client.post(
        f"/v1/workspaces/{ws}/signup",
        json={"kind": "user", "email": "dana@example.com"},
    )
    assert while_pending.status_code == 409
    assert while_pending.json()["error"] == "signup_pending"

    listed = await client.get(
        f"/v1/workspaces/{ws}/signups?status=pending", headers=headers
    )
    assert listed.status_code == 200, listed.text
    assert [entry["id"] for entry in listed.json()] == [created["id"]]

    identities = await client.get(f"/v1/workspaces/{ws}/identities", headers=headers)
    assert identities.status_code == 200
    assert "dana@example.com" not in identities.text

    approved = await client.post(
        f"/v1/workspaces/{ws}/signups/{created['id']}/approve",
        headers=headers,
        json={"role": "viewer", "note": "known reviewer"},
    )
    assert approved.status_code == 200, approved.text
    decision = approved.json()
    assert decision["request"]["status"] == "approved"
    assert decision["credential"] is None

    signed_in = await _login(client, ws, "dana@example.com")
    assert signed_in.status_code == 200, signed_in.text
    member = await client.get(
        "/v1/me", headers={"Authorization": f"Bearer {signed_in.json()['token']}"}
    )
    assert member.status_code == 200
    assert member.json()["role"] == "viewer"

    identities = await client.get(f"/v1/workspaces/{ws}/identities", headers=headers)
    assert "dana@example.com" in identities.text

    audit = await client.get(f"/v1/workspaces/{ws}/audit", headers=headers)
    actions = [entry["action"] for entry in audit.json()]
    assert "signup.requested" in actions
    assert "signup.approved" in actions

    duplicate = await client.post(
        f"/v1/workspaces/{ws}/signup",
        json={"kind": "user", "email": "dana@example.com"},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"] == "already_member"


async def test_person_signup_rejection_and_reapply(client: AsyncClient, admin: dict):
    ws = admin["workspace"]
    headers = admin["headers"]
    created = await _signup(
        client, ws, kind="user", email="sam@example.com", display_name="Sam"
    )

    rejected = await client.post(
        f"/v1/workspaces/{ws}/signups/{created['id']}/reject",
        headers=headers,
        json={"note": "external contractor"},
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["request"]["status"] == "rejected"

    blocked = await _login(client, ws, "sam@example.com")
    assert blocked.status_code == 403
    assert blocked.json()["error"] == "signup_rejected"

    again = await _signup(client, ws, kind="user", email="sam@example.com")
    assert again["status"] == "pending"
    assert again["display_name"] is None

    approved = await client.post(
        f"/v1/workspaces/{ws}/signups/{again['id']}/approve",
        headers=headers,
        json={"role": "developer"},
    )
    assert approved.status_code == 200, approved.text
    assert (await _login(client, ws, "sam@example.com")).status_code == 200


async def test_agent_signup_issues_credential_on_approval(
    client: AsyncClient, admin: dict
):
    ws = admin["workspace"]
    headers = admin["headers"]
    created = await _signup(
        client,
        ws,
        kind="agent",
        agent_name="Research Bot",
        agent_slug="research-bot",
        requested_role="agent:requester",
        message="Needs catalog access.",
    )
    assert created["status"] == "pending"
    assert created["kind"] == "agent"

    agents = await client.get(f"/v1/workspaces/{ws}/agents", headers=headers)
    assert "research-bot" not in agents.text

    while_pending = await client.post(
        f"/v1/workspaces/{ws}/signup",
        json={"kind": "agent", "agent_slug": "research-bot"},
    )
    assert while_pending.status_code == 409
    assert while_pending.json()["error"] == "signup_pending"

    role_error = await client.post(
        f"/v1/workspaces/{ws}/signups/{created['id']}/approve",
        headers=headers,
        json={"role": "viewer"},
    )
    assert role_error.status_code == 422

    approved = await client.post(
        f"/v1/workspaces/{ws}/signups/{created['id']}/approve",
        headers=headers,
        json={"role": "agent:requester"},
    )
    assert approved.status_code == 200, approved.text
    credential = approved.json()["credential"]
    assert credential["type"] == "api_key"
    assert credential["api_key"].startswith("agw_live_")

    agents = await client.get(f"/v1/workspaces/{ws}/agents", headers=headers)
    assert agents.status_code == 200
    assert any(agent["slug"] == "research-bot" for agent in agents.json())

    me = await client.get(
        "/v1/me",
        headers={"Authorization": f"Bearer {credential['api_key']}"},
    )
    assert me.status_code == 200, me.text
    assert me.json()["kind"] == "agent"
    assert me.json()["role"] == "agent:requester"

    duplicate = await client.post(
        f"/v1/workspaces/{ws}/signup",
        json={"kind": "agent", "agent_slug": "research-bot"},
    )
    assert duplicate.status_code == 409


async def test_signup_approval_requires_permission(client: AsyncClient, admin: dict):
    ws = admin["workspace"]
    headers = admin["headers"]
    first = await _signup(client, ws, kind="user", email="viewer@example.com")
    approved = await client.post(
        f"/v1/workspaces/{ws}/signups/{first['id']}/approve",
        headers=headers,
        json={"role": "viewer"},
    )
    assert approved.status_code == 200, approved.text
    token = (await _login(client, ws, "viewer@example.com")).json()["token"]
    viewer_headers = {"Authorization": f"Bearer {token}"}

    second = await _signup(client, ws, kind="user", email="later@example.com")
    denied = await client.post(
        f"/v1/workspaces/{ws}/signups/{second['id']}/approve",
        headers=viewer_headers,
        json={"role": "viewer"},
    )
    assert denied.status_code == 403, denied.text

    pending = await client.get(
        f"/v1/workspaces/{ws}/signups?status=pending", headers=viewer_headers
    )
    assert pending.status_code == 200
    assert [entry["id"] for entry in pending.json()] == [second["id"]]
