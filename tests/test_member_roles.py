from __future__ import annotations

from httpx import AsyncClient


async def _approved_user(
    client: AsyncClient,
    admin: dict,
    *,
    email: str = "dana@example.com",
    role: str = "viewer",
) -> tuple[str, str]:
    ws = admin["workspace"]
    created = await client.post(
        f"/v1/workspaces/{ws}/signup",
        json={"kind": "user", "email": email, "display_name": "Dana"},
    )
    assert created.status_code == 201, created.text
    approved = await client.post(
        f"/v1/workspaces/{ws}/signups/{created.json()['id']}/approve",
        headers=admin["headers"],
        json={"role": role},
    )
    assert approved.status_code == 200, approved.text
    request = approved.json()["request"]
    return request["principal_id"], request["identity_id"]


async def _approved_agent(client: AsyncClient, admin: dict) -> str:
    ws = admin["workspace"]
    created = await client.post(
        f"/v1/workspaces/{ws}/signup",
        json={
            "kind": "agent",
            "agent_name": "Research Bot",
            "agent_slug": "research-bot",
            "identity_name": "Dana",
            "owner_email": "dana@example.com",
        },
    )
    assert created.status_code == 201, created.text
    approved = await client.post(
        f"/v1/workspaces/{ws}/signups/{created.json()['id']}/approve",
        headers=admin["headers"],
        json={"role": "agent:requester"},
    )
    assert approved.status_code == 200, approved.text
    return approved.json()["request"]["principal_id"]


async def _change_role(
    client: AsyncClient, admin: dict, kind: str, member_id: str, role: str
):
    return await client.patch(
        f"/v1/workspaces/{admin['workspace']}/members/{kind}/{member_id}/role",
        headers=admin["headers"],
        json={"role": role},
    )


async def test_owner_changes_member_role(client: AsyncClient, admin: dict):
    user_id, identity_id = await _approved_user(client, admin)

    changed = await _change_role(client, admin, "user", user_id, "developer")
    assert changed.status_code == 200, changed.text
    assert changed.json()["role"] == "developer"
    assert "agent:create" in changed.json()["permissions"]

    groups = await client.get(
        f"/v1/workspaces/{admin['workspace']}/identity-groups",
        headers=admin["headers"],
    )
    group = next(item for item in groups.json() if item["id"] == identity_id)
    entity = next(item for item in group["entities"] if item["id"] == user_id)
    assert entity["role"] == "developer"
    assert "agent:create" in entity["permissions"]

    login = await client.post(
        "/v1/auth/dev-login",
        json={"workspace_slug": admin["workspace"], "email": "dana@example.com"},
    )
    assert login.status_code == 200, login.text
    me = await client.get(
        "/v1/me", headers={"Authorization": f"Bearer {login.json()['token']}"}
    )
    assert me.status_code == 200
    assert me.json()["role"] == "developer"

    audit = await client.get(
        f"/v1/workspaces/{admin['workspace']}/audit", headers=admin["headers"]
    )
    event = next(
        entry for entry in audit.json() if entry["action"] == "member.role_changed"
    )
    assert event["meta"]["from"] == "viewer"
    assert event["meta"]["to"] == "developer"


async def test_role_change_checks_role_kind(client: AsyncClient, admin: dict):
    user_id, _ = await _approved_user(client, admin)

    wrong_kind = await _change_role(client, admin, "user", user_id, "agent:executor")
    assert wrong_kind.status_code == 422, wrong_kind.text
    assert wrong_kind.json()["error"] == "invalid_role"

    unknown = await _change_role(client, admin, "user", user_id, "superuser")
    assert unknown.status_code == 422, unknown.text
    assert unknown.json()["error"] == "invalid_role"

    missing = await client.patch(
        f"/v1/workspaces/{admin['workspace']}/members/user/"
        "00000000-0000-0000-0000-000000000000/role",
        headers=admin["headers"],
        json={"role": "viewer"},
    )
    assert missing.status_code == 404, missing.text

    agent_id = await _approved_agent(client, admin)
    human_role = await _change_role(client, admin, "agent", agent_id, "viewer")
    assert human_role.status_code == 422, human_role.text
    agent_role = await _change_role(client, admin, "agent", agent_id, "agent:editor")
    assert agent_role.status_code == 200, agent_role.text
    assert agent_role.json()["role"] == "agent:editor"
    assert "grant:write" in agent_role.json()["permissions"]


async def test_member_cannot_change_roles(client: AsyncClient, admin: dict):
    await _approved_user(client, admin)
    login = await client.post(
        "/v1/auth/dev-login",
        json={"workspace_slug": admin["workspace"], "email": "dana@example.com"},
    )
    member_headers = {"Authorization": f"Bearer {login.json()['token']}"}
    me = await client.get("/v1/me", headers=member_headers)
    target = me.json()["id"]

    denied = await client.patch(
        f"/v1/workspaces/{admin['workspace']}/members/user/{target}/role",
        headers=member_headers,
        json={"role": "owner"},
    )
    assert denied.status_code == 403, denied.text


async def test_last_owner_cannot_be_demoted(client: AsyncClient, admin: dict):
    me = await client.get("/v1/me", headers=admin["headers"])
    owner_id = me.json()["id"]

    blocked = await _change_role(client, admin, "user", owner_id, "admin")
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["error"] == "last_owner"

    second_owner_id, _ = await _approved_user(
        client, admin, email="sam@example.com"
    )
    promote_second = await _change_role(
        client, admin, "user", second_owner_id, "owner"
    )
    assert promote_second.status_code == 200

    demoted = await _change_role(client, admin, "user", owner_id, "admin")
    assert demoted.status_code == 200, demoted.text
    assert demoted.json()["role"] == "admin"
