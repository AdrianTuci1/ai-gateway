from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from moto import mock_aws
from pydantic import SecretStr

from agw.config import Runtime, Settings
from agw.core.errors import ApiError
from agw.core.roles import BUILTIN_ROLES
from agw.core.time import utcnow
from agw.db.models import AgentGrant, ServiceTool
from agw.main import create_app
from agw.store import build_store_provider


@pytest.fixture
def dynamo_settings(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-central-1")
    with mock_aws():
        yield Settings(
            db_backend="dynamodb",
            dynamodb_table=f"agw-store-{uuid.uuid4().hex[:10]}",
            dynamodb_region="eu-central-1",
            secret_key=SecretStr("test-secret-key-that-is-long-enough-1234"),
            ca_enabled=False,
        )


async def test_roles_seed_idempotent(dynamo_settings: Settings):
    provider = build_store_provider(dynamo_settings)
    await provider.startup(create_tables=True)
    await provider.startup()
    try:
        async with provider.store() as store:
            roles = await store.list_global_roles()
            assert len(roles) == len(BUILTIN_ROLES)
            owner = await store.get_builtin_role("owner")
            assert "workspace:delete" in owner.permissions
            executor = await store.resolve_role(uuid.uuid4(), "agent:executor")
            assert executor is not None
            assert executor.name == "agent:executor"
            with pytest.raises(LookupError):
                await store.get_builtin_role("missing")
    finally:
        await provider.shutdown()


async def test_workspace_slug_is_unique(dynamo_settings: Settings):
    provider = build_store_provider(dynamo_settings)
    await provider.startup(create_tables=True)
    try:
        async with provider.store() as store:
            workspace = await store.create_workspace(slug="acme", name="Acme")
            assert (await store.get_workspace_by_slug("acme")).id == workspace.id
            with pytest.raises(ApiError) as exc:
                await store.create_workspace(slug="acme", name="Other")
            assert exc.value.status_code == 409
    finally:
        await provider.shutdown()


async def test_agent_grant_and_catalog_cascade(dynamo_settings: Settings):
    provider = build_store_provider(dynamo_settings)
    await provider.startup(create_tables=True)
    try:
        async with provider.store() as store:
            workspace = await store.create_workspace(slug="acme", name="Acme")
            user = await store.create_user(
                email="owner@example.com",
                idp_subject="local:owner@example.com",
            )
            owner = await store.get_builtin_role("owner")
            await store.create_membership(
                workspace_id=workspace.id,
                principal_type="user",
                principal_id=user.id,
                role_id=owner.id,
            )
            agent = await store.create_agent(
                workspace_id=workspace.id,
                slug="billing",
                name="Billing",
                kind="interactive",
                ceiling={},
                created_by=user.id,
            )
            role = await store.get_builtin_role("agent:executor")
            await store.create_membership(
                workspace_id=workspace.id,
                principal_type="agent",
                principal_id=agent.id,
                role_id=role.id,
            )
            service = await store.create_service(
                workspace_id=workspace.id,
                name="crm",
                kind="mcp_http",
                endpoint="http://upstream/mcp",
                auth_type="none",
                credential_policy="per_agent",
                created_by=user.id,
            )
            await store.save_tool(
                ServiceTool(
                    service_id=service.id,
                    name="search_tickets",
                    description="Search",
                    input_schema={"type": "object"},
                    annotations={},
                    definition_hash="hash",
                )
            )
            grant = AgentGrant(
                workspace_id=workspace.id,
                agent_id=agent.id,
                service_id=service.id,
                tools=["search_tickets"],
                arg_constraints={},
                status="active",
                created_by=user.id,
            )
            await store.save_grant(grant)
            assert [entry.id for entry in await store.list_active_grants(agent.id)] == [
                grant.id
            ]
            rows = await store.list_catalog(workspace.id, None)
            assert [(tool.name, svc.name) for tool, svc in rows] == [
                ("search_tickets", "crm")
            ]
            assert await store.tool_names(service.id) == {"search_tickets"}

            await store.revoke_grants_for_service(service.id)
            assert await store.list_active_grants(agent.id) == []
            refreshed = await store.get_grant(agent.id, service.id)
            assert refreshed is not None and refreshed.status == "revoked"

            await store.revoke_grants_for_agent(agent.id)
    finally:
        await provider.shutdown()


async def test_audit_filtering_and_order(dynamo_settings: Settings):
    provider = build_store_provider(dynamo_settings)
    await provider.startup(create_tables=True)
    try:
        async with provider.store() as store:
            workspace = await store.create_workspace(slug="acme", name="Acme")
            for action, decision in (
                ("first", None),
                ("second", "deny"),
                ("third", "allow"),
            ):
                await store.record_audit(
                    workspace_id=workspace.id,
                    actor_type="user",
                    actor_id=None,
                    action=action,
                    trace_id="trace",
                    decision=decision,
                )
            events = await store.list_audit(workspace.id, limit=10)
            assert [event.action for event in events] == ["third", "second", "first"]
            denied = await store.list_audit(workspace.id, decision="deny")
            assert [event.action for event in denied] == ["second"]
            recent = await store.list_audit(
                workspace.id, since=events[-1].created_at
            )
            assert len(recent) == 3
            assert isinstance(events[0].meta, dict)
    finally:
        await provider.shutdown()


async def test_audit_filtered_limit_pages_past_non_matches(
    dynamo_settings: Settings,
):
    provider = build_store_provider(dynamo_settings)
    await provider.startup(create_tables=True)
    try:
        async with provider.store() as store:
            workspace = await store.create_workspace(slug="acme", name="Acme")
            for index in range(6):
                await store.record_audit(
                    workspace_id=workspace.id,
                    actor_type="user",
                    actor_id=None,
                    action=f"event-{index}",
                    trace_id="trace",
                    decision="deny" if index % 2 else "allow",
                )
            allowed = await store.list_audit(
                workspace.id, decision="allow", limit=2
            )
            assert [event.action for event in allowed] == ["event-4", "event-2"]
    finally:
        await provider.shutdown()


async def test_edge_runtime_on_dynamodb(dynamo_settings: Settings):
    settings = dynamo_settings.model_copy(
        update={
            "runtime": Runtime.REQUEST_RESPONSE,
            "bootstrap_enabled": True,
            "bootstrap_token": SecretStr("bootstrap-token"),
            "auto_create": True,
            "public_base_url": "http://testserver",
        }
    )
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            runtime = await client.get("/v1/runtime")
            assert runtime.json()["features"]["mcp_sse"] is False

            response = await client.post(
                "/v1/bootstrap",
                headers={"X-Bootstrap-Token": "bootstrap-token"},
                json={
                    "workspace_slug": "edge",
                    "workspace_name": "Edge",
                    "owner_email": "owner@example.com",
                },
            )
            assert response.status_code == 200, response.text
            headers = {"Authorization": f"Bearer {response.json()['token']}"}
            response = await client.post(
                "/v1/workspaces/edge/agents",
                headers=headers,
                json={"slug": "edge-agent", "name": "Edge"},
            )
            assert response.status_code == 201, response.text
            api_key = response.json()["api_key"]
            response = await client.post(
                "/mcp/edge-agent",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Mcp-Session-Id": "s1",
                },
                json={"jsonrpc": "2.0", "id": 1, "method": "initialize"},
            )
            assert response.status_code == 409
            assert response.json()["error"] == "persistent_runtime_required"


def test_lambda_migrate_on_dynamodb(dynamo_settings: Settings, monkeypatch):
    import boto3

    table = dynamo_settings.dynamodb_table
    client = boto3.client("dynamodb", region_name="eu-central-1")
    client.create_table(
        TableName=table,
        AttributeDefinitions=[
            {"AttributeName": "pk", "AttributeType": "S"},
            {"AttributeName": "sk", "AttributeType": "S"},
        ],
        KeySchema=[
            {"AttributeName": "pk", "KeyType": "HASH"},
            {"AttributeName": "sk", "KeyType": "RANGE"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )

    monkeypatch.setenv("AGW_DB_BACKEND", "dynamodb")
    monkeypatch.setenv("AGW_DYNAMODB_TABLE", table)
    monkeypatch.setenv("AGW_DYNAMODB_REGION", "eu-central-1")
    monkeypatch.setenv("AGW_SECRET_KEY", "test-secret-key-that-is-long-enough-1234")

    from agw.lambda_migrate import handler

    assert handler({}, None) == {
        "ok": True,
        "storage": "dynamodb",
        "ready": True,
    }
