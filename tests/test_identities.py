from __future__ import annotations

from httpx import AsyncClient


async def _agent_identity(
    client: AsyncClient, ws: str, headers: dict, **body
) -> tuple[dict, str]:
    created = await client.post(
        f"/v1/workspaces/{ws}/signup",
        json={
            "kind": "agent",
            "agent_name": "Research Bot",
            "agent_slug": "research-bot",
            "requested_role": "agent:requester",
            **body,
        },
    )
    assert created.status_code == 201, created.text
    approved = await client.post(
        f"/v1/workspaces/{ws}/signups/{created.json()['id']}/approve",
        headers=headers,
        json={"role": "agent:requester"},
    )
    assert approved.status_code == 200, approved.text
    decision = approved.json()
    return decision, decision["credential"]["api_key"]


async def _groups(client: AsyncClient, ws: str, headers: dict) -> list[dict]:
    response = await client.get(
        f"/v1/workspaces/{ws}/identity-groups", headers=headers
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_approved_agent_invites_owner_without_admin_approval(
    client: AsyncClient, admin: dict
):
    ws = admin["workspace"]
    headers = admin["headers"]
    decision, api_key = await _agent_identity(
        client,
        ws,
        headers,
        identity_name="Dana",
        owner_email="dana@example.com",
    )
    identity_id = decision["request"]["identity_id"]
    assert identity_id is not None

    groups = await _groups(client, ws, headers)
    dana = next(group for group in groups if group["id"] == identity_id)
    assert dana["status"] == "active"
    assert dana["owner_email"] == "dana@example.com"
    assert [entity["name"] for entity in dana["entities"]] == ["Research Bot"]
    assert dana["entities"][0]["is_identity_admin"] is True
    assert dana["can_manage"] is True

    agent_headers = {"Authorization": f"Bearer {api_key}"}
    invited = await client.post(
        f"/v1/workspaces/{ws}/identity-groups/{identity_id}/invites",
        headers=agent_headers,
        json={},
    )
    assert invited.status_code == 201, invited.text
    invite = invited.json()
    assert invite["email"] == "dana@example.com"
    assert invite["role"] == "viewer"
    token = invite["invite_url"].rsplit("/", 1)[-1]

    escalation = await client.post(
        f"/v1/workspaces/{ws}/identity-groups/{identity_id}/invites",
        headers=agent_headers,
        json={"role": "developer"},
    )
    assert escalation.status_code == 403, escalation.text

    preview = await client.get(f"/v1/identity-invites/{token}")
    assert preview.status_code == 200, preview.text
    assert preview.json()["identity_name"] == "Dana"
    assert preview.json()["email"] == "dana@example.com"

    accepted = await client.post(
        f"/v1/identity-invites/{token}/accept", json={"display_name": "Dana"}
    )
    assert accepted.status_code == 200, accepted.text
    joined = accepted.json()
    assert joined["identity_id"] == identity_id
    assert joined["user"]["email"] == "dana@example.com"

    me = await client.get(
        "/v1/me", headers={"Authorization": f"Bearer {joined['token']}"}
    )
    assert me.status_code == 200, me.text
    assert me.json()["identity_id"] == identity_id
    assert me.json()["identity_name"] == "Dana"
    assert me.json()["is_identity_admin"] is False
    assert me.json()["role"] == "viewer"

    groups = await _groups(client, ws, headers)
    dana = next(group for group in groups if group["id"] == identity_id)
    by_kind = {entity["kind"]: entity for entity in dana["entities"]}
    assert by_kind["agent"]["name"] == "Research Bot"
    assert by_kind["agent"]["is_identity_admin"] is True
    assert by_kind["user"]["email"] == "dana@example.com"
    assert by_kind["user"]["is_identity_admin"] is False

    reused = await client.post(
        f"/v1/identity-invites/{token}/accept", json={"display_name": "Dana"}
    )
    assert reused.status_code == 404, reused.text

    audit = await client.get(f"/v1/workspaces/{ws}/audit", headers=headers)
    actions = [entry["action"] for entry in audit.json()]
    assert "identity.approved" in actions
    assert "identity.invited" in actions
    assert "identity.invite_accepted" in actions


async def test_workspace_admin_can_invite_with_a_human_role(
    client: AsyncClient, admin: dict
):
    ws = admin["workspace"]
    headers = admin["headers"]
    _, _ = await _agent_identity(client, ws, headers, owner_email="dana@example.com")
    groups = await _groups(client, ws, headers)
    dana = next(group for group in groups if group["name"] == "Research Bot")

    invited = await client.post(
        f"/v1/workspaces/{ws}/identity-groups/{dana['id']}/invites",
        headers=headers,
        json={"email": "dana@example.com", "role": "developer"},
    )
    assert invited.status_code == 201, invited.text
    assert invited.json()["role"] == "developer"
    token = invited.json()["invite_url"].rsplit("/", 1)[-1]

    accepted = await client.post(f"/v1/identity-invites/{token}/accept", json={})
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["user"]["email"] == "dana@example.com"


async def test_person_signup_attaches_to_approved_agent_identity(
    client: AsyncClient, admin: dict
):
    ws = admin["workspace"]
    headers = admin["headers"]
    decision, _ = await _agent_identity(
        client, ws, headers, identity_name="Dana", owner_email="dana@example.com"
    )
    identity_id = decision["request"]["identity_id"]

    created = await client.post(
        f"/v1/workspaces/{ws}/signup",
        json={"kind": "user", "email": "dana@example.com", "display_name": "Dana"},
    )
    assert created.status_code == 201, created.text
    assert created.json()["identity_id"] == identity_id
    assert created.json()["identity_name"] == "Dana"

    approved = await client.post(
        f"/v1/workspaces/{ws}/signups/{created.json()['id']}/approve",
        headers=headers,
        json={"role": "viewer"},
    )
    assert approved.status_code == 200, approved.text
    groups = await _groups(client, ws, headers)
    dana = next(group for group in groups if group["id"] == identity_id)
    assert {entity["kind"] for entity in dana["entities"]} == {"agent", "user"}
    assert len([group for group in groups if group["name"] == "Dana"]) == 1


async def test_rejected_agent_can_request_again(client: AsyncClient, admin: dict):
    ws = admin["workspace"]
    headers = admin["headers"]
    created = await client.post(
        f"/v1/workspaces/{ws}/signup",
        json={
            "kind": "agent",
            "agent_name": "Research Bot",
            "agent_slug": "research-bot",
            "identity_name": "Dana",
            "owner_email": "dana@example.com",
            "requested_role": "agent:requester",
        },
    )
    assert created.status_code == 201, created.text
    rejected = await client.post(
        f"/v1/workspaces/{ws}/signups/{created.json()['id']}/reject",
        headers=headers,
        json={"note": "not yet"},
    )
    assert rejected.status_code == 200, rejected.text

    again = await client.post(
        f"/v1/workspaces/{ws}/signup",
        json={
            "kind": "agent",
            "agent_name": "Research Bot",
            "agent_slug": "research-bot",
            "identity_name": "Dana",
            "owner_email": "dana@example.com",
            "requested_role": "agent:requester",
        },
    )
    assert again.status_code == 201, again.text
    assert again.json()["status"] == "pending"

    approved = await client.post(
        f"/v1/workspaces/{ws}/signups/{again.json()['id']}/approve",
        headers=headers,
        json={"role": "agent:requester"},
    )
    assert approved.status_code == 200, approved.text
    groups = await _groups(client, ws, headers)
    dana = next(group for group in groups if group["name"] == "Dana")
    assert len([entity for entity in dana["entities"] if entity["kind"] == "agent"]) == 1


async def test_pending_identity_cannot_be_invited(client: AsyncClient, admin: dict):
    ws = admin["workspace"]
    headers = admin["headers"]
    created = await client.post(
        f"/v1/workspaces/{ws}/signup",
        json={
            "kind": "agent",
            "agent_name": "Pending Bot",
            "agent_slug": "pending-bot",
            "requested_role": "agent:requester",
        },
    )
    assert created.status_code == 201, created.text
    identity_id = created.json()["identity_id"]

    invited = await client.post(
        f"/v1/workspaces/{ws}/identity-groups/{identity_id}/invites",
        headers=headers,
        json={"email": "dana@example.com"},
    )
    assert invited.status_code == 409, invited.text
    assert invited.json()["error"] == "identity_not_active"


async def test_identity_admin_cannot_invite_into_another_identity(
    client: AsyncClient, admin: dict
):
    ws = admin["workspace"]
    headers = admin["headers"]
    _, api_key = await _agent_identity(
        client, ws, headers, owner_email="dana@example.com"
    )
    other = await client.post(
        f"/v1/workspaces/{ws}/signup",
        json={
            "kind": "agent",
            "agent_name": "Other Bot",
            "agent_slug": "other-bot",
            "requested_role": "agent:requester",
        },
    )
    approved = await client.post(
        f"/v1/workspaces/{ws}/signups/{other.json()['id']}/approve",
        headers=headers,
        json={"role": "agent:requester"},
    )
    assert approved.status_code == 200, approved.text
    other_identity = approved.json()["request"]["identity_id"]

    invited = await client.post(
        f"/v1/workspaces/{ws}/identity-groups/{other_identity}/invites",
        headers={"Authorization": f"Bearer {api_key}"},
        json={"email": "someone@example.com"},
    )
    assert invited.status_code == 403, invited.text
