from __future__ import annotations

import uuid

from httpx import AsyncClient

from agw.api import mcp as mcp_module
from agw.api import services as services_module


class FakeMCPClient:
    session_id = None

    def __init__(self, endpoint: str, *, timeout: float = 30.0) -> None:
        self.endpoint = endpoint

    async def list_tools(self):
        return [
            {
                "name": "search_tickets",
                "description": "Search support tickets",
                "inputSchema": {"type": "object", "properties": {"q": {"type": "string"}}},
            },
            {
                "name": "delete_ticket",
                "description": "Delete a ticket",
                "inputSchema": {"type": "object"},
            },
        ]

    async def call_tool(self, name: str, arguments: dict):
        return {"content": [{"type": "text", "text": f"{name}:ok"}]}


async def _create_agent(client: AsyncClient, admin: dict, role: str = "agent:executor"):
    response = await client.post(
        f"/v1/workspaces/{admin['workspace']}/agents",
        headers=admin["headers"],
        json={"slug": "billing", "name": "Billing", "role": role},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_bootstrap_and_me(client: AsyncClient, admin: dict):
    response = await client.get("/v1/me", headers=admin["headers"])
    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "user"
    assert body["role"] == "owner"
    assert body["workspace_slug"] == "acme"
    assert "grant:write" in body["permissions"]


async def test_bootstrap_closed(client: AsyncClient, admin: dict):
    response = await client.post(
        "/v1/bootstrap",
        headers={"X-Bootstrap-Token": "bootstrap-token"},
        json={
            "workspace_slug": "other",
            "workspace_name": "Other",
            "owner_email": "other@example.com",
        },
    )
    assert response.status_code == 410
    assert response.json()["error"] == "bootstrap_closed"


async def test_bootstrap_wrong_token(client: AsyncClient):
    response = await client.post(
        "/v1/bootstrap",
        headers={"X-Bootstrap-Token": "wrong"},
        json={
            "workspace_slug": "acme",
            "workspace_name": "Acme",
            "owner_email": "owner@example.com",
        },
    )
    assert response.status_code == 401


async def test_agent_api_key_auth(client: AsyncClient, admin: dict):
    created = await _create_agent(client, admin)
    api_key = created["api_key"]
    response = await client.get("/v1/me", headers={"Authorization": f"Bearer {api_key}"})
    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "agent"
    assert body["agent_id"] == created["agent"]["id"]
    assert body["role"] == "agent:executor"


async def test_discovery_grant_catalog_and_mcp(
    client: AsyncClient, admin: dict, monkeypatch
):
    monkeypatch.setattr(services_module, "MCPHTTPClient", FakeMCPClient)
    monkeypatch.setattr(mcp_module, "MCPHTTPClient", FakeMCPClient)

    created = await _create_agent(client, admin, role="agent:requester")
    agent = created["agent"]
    api_key = created["api_key"]

    response = await client.post(
        f"/v1/workspaces/{admin['workspace']}/services",
        headers=admin["headers"],
        json={"name": "crm", "kind": "mcp_http", "endpoint": "http://upstream/mcp"},
    )
    assert response.status_code == 201, response.text
    service = response.json()

    response = await client.post(
        f"/v1/workspaces/{admin['workspace']}/services/{service['id']}/discover",
        headers=admin["headers"],
    )
    assert response.status_code == 200, response.text
    assert {tool["name"] for tool in response.json()["tools"]} == {
        "search_tickets",
        "delete_ticket",
    }

    response = await client.put(
        f"/v1/workspaces/{admin['workspace']}/agents/{agent['id']}/grants/{service['id']}",
        headers=admin["headers"],
        json={"tools": ["search_tickets"], "arg_constraints": {}},
    )
    assert response.status_code == 200, response.text

    response = await client.get(
        "/v1/catalog",
        headers={"Authorization": f"Bearer {api_key}"},
        params={"granted": "true"},
    )
    assert response.status_code == 200, response.text
    catalog = response.json()["items"]
    assert len(catalog) == 1
    assert catalog[0]["name"] == "search_tickets"
    assert catalog[0]["granted"] is True

    response = await client.post(
        f"/mcp/{agent['slug']}",
        headers={"Authorization": f"Bearer {api_key}"},
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
    )
    assert response.status_code == 200
    tools = response.json()["result"]["tools"]
    assert [tool["name"] for tool in tools] == ["crm__search_tickets"]

    response = await client.post(
        f"/mcp/{agent['slug']}",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "crm__delete_ticket", "arguments": {}},
        },
    )
    body = response.json()
    assert body["error"]["code"] == -32003

    response = await client.post(
        f"/mcp/{agent['slug']}",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "crm__search_tickets", "arguments": {"q": "invoice"}},
        },
    )
    body = response.json()
    assert body["result"]["content"][0]["text"] == "search_tickets:ok"


async def test_human_role_rejected_for_agent(client: AsyncClient, admin: dict):
    response = await client.post(
        f"/v1/workspaces/{admin['workspace']}/agents",
        headers=admin["headers"],
        json={"slug": "bad-role", "name": "Bad Role", "role": "owner"},
    )
    assert response.status_code == 422
    assert response.json()["error"] == "invalid_role"

    response = await client.post(
        f"/v1/workspaces/{admin['workspace']}/enrollment-tokens",
        headers=admin["headers"],
        json={"agent_slug": "bad-token", "role": "developer"},
    )
    assert response.status_code == 422
    assert response.json()["error"] == "invalid_role"


async def test_audit_resource_ids_are_populated(client: AsyncClient, admin: dict):
    await _create_agent(client, admin)
    response = await client.post(
        f"/v1/workspaces/{admin['workspace']}/services",
        headers=admin["headers"],
        json={"name": "erp", "kind": "mcp_http", "endpoint": "http://upstream/erp"},
    )
    assert response.status_code == 201, response.text

    response = await client.get(
        f"/v1/workspaces/{admin['workspace']}/audit", headers=admin["headers"]
    )
    assert response.status_code == 200, response.text
    events = {event["action"]: event for event in response.json()}
    assert events["agent.created"]["resource_id"] != "None"
    assert events["service.created"]["resource_id"] != "None"
