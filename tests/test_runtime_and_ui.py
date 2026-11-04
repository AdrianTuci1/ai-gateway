from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from sqlalchemy.pool import NullPool

from agw.config import Runtime, Settings
from agw.db.session import build_engine
from agw.main import create_app


@pytest.mark.asyncio
async def test_request_response_runtime_features(tmp_path):
    settings = Settings(
        runtime=Runtime.REQUEST_RESPONSE,
        database_url="sqlite+aiosqlite:///:memory:",
        db_driver="sqlite",
        secret_key=SecretStr("test-secret"),
        auto_create=True,
        ca_dir=tmp_path / "ca",
    )
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = await client.get("/v1/runtime")
            assert response.status_code == 200
            body = response.json()
            assert body["runtime"] == "request_response"
            assert body["features"]["mcp_sse"] is False
            assert body["features"]["stdio"] is False


@pytest.mark.asyncio
async def test_request_response_rejects_streaming_and_sessions(tmp_path):
    settings = Settings(
        runtime=Runtime.REQUEST_RESPONSE,
        database_url="sqlite+aiosqlite:///:memory:",
        db_driver="sqlite",
        secret_key=SecretStr("test-secret-key-that-is-long-enough-1234"),
        bootstrap_enabled=True,
        bootstrap_token=SecretStr("bootstrap-token"),
        auto_create=True,
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
            admin_headers = {"Authorization": f"Bearer {response.json()['token']}"}
            response = await client.post(
                "/v1/workspaces/acme/agents",
                headers=admin_headers,
                json={"slug": "billing", "name": "Billing"},
            )
            api_key = response.json()["api_key"]

            response = await client.post(
                "/mcp/billing",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Accept": "text/event-stream",
                },
                json={"jsonrpc": "2.0", "id": 1, "method": "initialize"},
            )
            assert response.status_code == 409
            assert response.json()["error"] == "persistent_runtime_required"

            response = await client.post(
                "/mcp/billing",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Mcp-Session-Id": "session-1",
                },
                json={"jsonrpc": "2.0", "id": 2, "method": "initialize"},
            )
            assert response.status_code == 409
            assert response.json()["error"] == "persistent_runtime_required"


def test_null_pool_mode_for_lambda(tmp_path):
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'lambda.db'}",
        db_driver="sqlite",
        db_pool_mode="null",
        secret_key=SecretStr("test-secret"),
        ca_dir=tmp_path / "ca",
    )
    engine = build_engine(settings)
    assert isinstance(engine.pool, NullPool)


@pytest.mark.asyncio
async def test_ui_placeholder(tmp_path):
    settings = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        db_driver="sqlite",
        secret_key=SecretStr("test-secret"),
        auto_create=True,
        ca_dir=tmp_path / "ca",
    )
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = await client.get("/")
            assert response.status_code == 200
            assert "AI Gateway" in response.text
