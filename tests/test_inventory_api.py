from __future__ import annotations

from httpx import AsyncClient


async def _seed(client: AsyncClient, admin: dict) -> dict:
    headers = admin["headers"]
    ws = admin["workspace"]
    group = await client.post(
        f"/v1/workspaces/{ws}/resource-groups",
        headers=headers,
        json={"name": "support", "kind": "application", "description": "Support workload"},
    )
    assert group.status_code == 201, group.text
    service = await client.post(
        f"/v1/workspaces/{ws}/services",
        headers=headers,
        json={"name": "tickets", "kind": "http", "endpoint": "https://tickets.example.com"},
    )
    assert service.status_code == 201, service.text
    agent = await client.post(
        f"/v1/workspaces/{ws}/agents",
        headers=headers,
        json={"slug": "support-bot", "name": "Support Bot", "issue_credential": False},
    )
    assert agent.status_code == 201, agent.text
    return {
        "group": group.json(),
        "service": service.json(),
        "agent": agent.json()["agent"],
    }


async def test_inventory_groups_resources_and_standalone(client: AsyncClient, admin: dict):
    ws = admin["workspace"]
    headers = admin["headers"]
    seeded = await _seed(client, admin)

    inventory = await client.get(f"/v1/workspaces/{ws}/inventory", headers=headers)
    assert inventory.status_code == 200, inventory.text
    body = inventory.json()
    assert body["counts"] == {"groups": 1, "services": 1, "agents": 1}
    assert len(body["standalone"]) == 2
    group = body["groups"][0]
    assert group["name"] == "support"
    assert body["groups"][0]["resources"] == []

    assign = await client.put(
        f"/v1/workspaces/{ws}/resource-groups/{group['id']}/resources",
        headers=headers,
        json={
            "resources": [
                {"type": "service", "id": seeded["service"]["id"]},
                {"type": "agent", "id": seeded["agent"]["id"]},
            ]
        },
    )
    assert assign.status_code == 200, assign.text
    assert len(assign.json()["resources"]) == 2

    assigned = (await client.get(f"/v1/workspaces/{ws}/inventory", headers=headers)).json()
    assert len(assigned["groups"][0]["resources"]) == 2
    assert assigned["standalone"] == []


async def test_group_rename_and_delete_releases_resources(client: AsyncClient, admin: dict):
    ws = admin["workspace"]
    headers = admin["headers"]
    seeded = await _seed(client, admin)
    group_id = seeded["group"]["id"]

    await client.put(
        f"/v1/workspaces/{ws}/resource-groups/{group_id}/resources",
        headers=headers,
        json={"resources": [{"type": "service", "id": seeded["service"]["id"]}]},
    )

    renamed = await client.patch(
        f"/v1/workspaces/{ws}/resource-groups/{group_id}",
        headers=headers,
        json={"name": "support-eu"},
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["name"] == "support-eu"

    deleted = await client.delete(
        f"/v1/workspaces/{ws}/resource-groups/{group_id}", headers=headers
    )
    assert deleted.status_code == 204, deleted.text

    inventory = (await client.get(f"/v1/workspaces/{ws}/inventory", headers=headers)).json()
    assert inventory["groups"] == []
    assert inventory["counts"]["groups"] == 0
    assert {item["type"] for item in inventory["standalone"]} == {"service", "agent"}


async def test_identities_include_owner_and_agent(client: AsyncClient, admin: dict):
    ws = admin["workspace"]
    headers = admin["headers"]
    await _seed(client, admin)

    response = await client.get(f"/v1/workspaces/{ws}/identities", headers=headers)
    assert response.status_code == 200, response.text
    identities = response.json()
    kinds = {(identity["kind"], identity["name"]) for identity in identities}
    assert ("user", "owner@example.com") in kinds
    assert ("agent", "Support Bot") in kinds
    agent = next(item for item in identities if item["kind"] == "agent")
    assert agent["role"] == "agent:executor"
    assert "grant:read" in agent["permissions"]


async def test_trace_list_and_detail(client: AsyncClient, admin: dict):
    ws = admin["workspace"]
    headers = admin["headers"]
    await client.get(f"/v1/workspaces/{ws}/inventory", headers=headers)
    inventory = (await client.get(f"/v1/workspaces/{ws}/inventory", headers=headers)).json()
    assert inventory["counts"]["groups"] == 0

    response = await client.get(f"/v1/workspaces/{ws}/traces", headers=headers)
    assert response.status_code == 200, response.text
    traces = response.json()
    assert traces, "requests should write root spans"
    match = next(
        trace
        for trace in traces
        if trace["root_name"] == "GET /v1/workspaces/{ws}/inventory"
    )
    assert match["status"] == "ok"
    assert match["span_count"] >= 1

    detail = await client.get(
        f"/v1/workspaces/{ws}/traces/{match['trace_id']}", headers=headers
    )
    assert detail.status_code == 200, detail.text
    spans = detail.json()["spans"]
    assert len(spans) == match["span_count"]
    root = next(span for span in spans if span["parent_span_id"] is None)
    assert root["span_id"] == "root"
    assert root["actor_type"] == "user"
