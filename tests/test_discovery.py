from __future__ import annotations

from unittest.mock import AsyncMock, patch

from httpx import AsyncClient

OPENAPI_DOC = {
    "openapi": "3.0.0",
    "info": {"title": "Tickets", "version": "1.0"},
    "paths": {
        "/tickets": {
            "get": {
                "operationId": "listTickets",
                "summary": "List tickets",
                "parameters": [
                    {
                        "name": "status",
                        "in": "query",
                        "required": True,
                        "schema": {"type": "string"},
                    }
                ],
            },
            "post": {
                "summary": "Create a ticket",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/Ticket"}
                        }
                    },
                },
            },
        }
    },
    "components": {
        "schemas": {
            "Ticket": {
                "type": "object",
                "properties": {
                    "subject": {"type": "string"},
                    "priority": {"type": "string"},
                },
                "required": ["subject"],
            }
        }
    },
}


async def _service(client: AsyncClient, admin: dict, **overrides) -> dict:
    body = {
        "name": "tickets-api",
        "kind": "http",
        "endpoint": "https://tickets.example.com",
        "auth_type": "none",
        **overrides,
    }
    response = await client.post(
        f"/v1/workspaces/{admin['workspace']}/services",
        headers=admin["headers"],
        json=body,
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_http_discovery_fills_catalog(client: AsyncClient, admin: dict):
    ws = admin["workspace"]
    service = await _service(client, admin)

    with patch(
        "agw.api.services.fetch_openapi",
        AsyncMock(return_value=OPENAPI_DOC),
    ):
        response = await client.post(
            f"/v1/workspaces/{ws}/services/{service['id']}/discover",
            headers=admin["headers"],
        )
    assert response.status_code == 200, response.text
    body = response.json()
    names = {tool["name"] for tool in body["tools"]}
    assert names == {"listTickets", "post_tickets"}
    create = next(tool for tool in body["tools"] if tool["name"] == "post_tickets")
    assert create["input_schema"]["required"] == ["subject"]
    assert create["annotations"]["http_method"] == "POST"
    assert body["service"]["manifest_synced_at"] is not None
    assert body["service"]["runtime_requirements"]["session"] is False

    listed = await client.get(
        f"/v1/workspaces/{ws}/services/{service['id']}/tools",
        headers=admin["headers"],
    )
    assert listed.status_code == 200
    assert {tool["name"] for tool in listed.json()} == names


async def test_discovered_tools_can_be_granted(client: AsyncClient, admin: dict):
    ws = admin["workspace"]
    service = await _service(client, admin)
    agent = await client.post(
        f"/v1/workspaces/{ws}/agents",
        headers=admin["headers"],
        json={"slug": "tickets-bot", "name": "Tickets Bot", "issue_credential": False},
    )
    assert agent.status_code == 201, agent.text
    agent_id = agent.json()["agent"]["id"]

    with patch(
        "agw.api.services.fetch_openapi",
        AsyncMock(return_value=OPENAPI_DOC),
    ):
        await client.post(
            f"/v1/workspaces/{ws}/services/{service['id']}/discover",
            headers=admin["headers"],
        )

    grant = await client.put(
        f"/v1/workspaces/{ws}/agents/{agent_id}/grants/{service['id']}",
        headers=admin["headers"],
        json={"tools": ["listTickets"]},
    )
    assert grant.status_code == 200, grant.text
    assert grant.json()["tools"] == ["listTickets"]


async def test_service_update_changes_name_and_auth(client: AsyncClient, admin: dict):
    ws = admin["workspace"]
    service = await _service(client, admin)

    response = await client.patch(
        f"/v1/workspaces/{ws}/services/{service['id']}",
        headers=admin["headers"],
        json={"name": "tickets-v2", "auth_type": "api_key"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["name"] == "tickets-v2"
    assert body["auth_type"] == "api_key"

    await _service(
        client,
        admin,
        name="billing-api",
        endpoint="https://billing.example.com",
    )
    conflict = await client.patch(
        f"/v1/workspaces/{ws}/services/{service['id']}",
        headers=admin["headers"],
        json={"name": "billing-api"},
    )
    assert conflict.status_code == 409


async def test_create_in_group_and_reject_foreign_group(client: AsyncClient, admin: dict):
    ws = admin["workspace"]
    group = await client.post(
        f"/v1/workspaces/{ws}/resource-groups",
        headers=admin["headers"],
        json={"name": "tickets", "kind": "workload"},
    )
    assert group.status_code == 201, group.text
    group_id = group.json()["id"]

    service = await _service(client, admin, resource_group_id=group_id)
    assert service["resource_group_id"] == group_id

    agent = await client.post(
        f"/v1/workspaces/{ws}/agents",
        headers=admin["headers"],
        json={
            "slug": "grouped-bot",
            "name": "Grouped Bot",
            "issue_credential": False,
            "resource_group_id": group_id,
        },
    )
    assert agent.status_code == 201, agent.text
    assert agent.json()["agent"]["resource_group_id"] == group_id

    inventory = await client.get(f"/v1/workspaces/{ws}/inventory", headers=admin["headers"])
    assert inventory.status_code == 200
    members = inventory.json()["groups"][0]["resources"]
    assert {member["type"] for member in members} == {"service", "agent"}

    missing = await client.post(
        f"/v1/workspaces/{ws}/services",
        headers=admin["headers"],
        json={
            "name": "orphan",
            "kind": "http",
            "endpoint": "https://orphan.example.com",
            "resource_group_id": "00000000-0000-0000-0000-000000000000",
        },
    )
    assert missing.status_code == 404


async def test_agent_edit_slug_and_kind(client: AsyncClient, admin: dict):
    ws = admin["workspace"]
    created = await client.post(
        f"/v1/workspaces/{ws}/agents",
        headers=admin["headers"],
        json={"slug": "edit-bot", "name": "Edit Bot", "issue_credential": False},
    )
    assert created.status_code == 201, created.text
    agent_id = created.json()["agent"]["id"]

    updated = await client.patch(
        f"/v1/workspaces/{ws}/agents/{agent_id}",
        headers=admin["headers"],
        json={"slug": "edit-bot-v2", "kind": "autonomous"},
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert body["slug"] == "edit-bot-v2"
    assert body["kind"] == "autonomous"

    other = await client.post(
        f"/v1/workspaces/{ws}/agents",
        headers=admin["headers"],
        json={"slug": "taken-bot", "name": "Taken", "issue_credential": False},
    )
    assert other.status_code == 201
    conflict = await client.patch(
        f"/v1/workspaces/{ws}/agents/{agent_id}",
        headers=admin["headers"],
        json={"slug": "taken-bot"},
    )
    assert conflict.status_code == 409
