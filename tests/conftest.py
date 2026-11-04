from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from moto import mock_aws
from pydantic import SecretStr

from agw.config import Runtime, Settings
from agw.main import create_app


@pytest.fixture(params=["sql", "dynamodb"])
def settings(request, tmp_path, monkeypatch) -> Settings:
    if request.param == "dynamodb":
        monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
        monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-central-1")
        mock = mock_aws()
        mock.start()
        request.addfinalizer(mock.stop)
        return Settings(
            runtime=Runtime.PERSISTENT,
            db_backend="dynamodb",
            dynamodb_table=f"agw-test-{uuid.uuid4().hex[:12]}",
            secret_key=SecretStr("test-secret-key-that-is-long-enough-1234"),
            bootstrap_enabled=True,
            bootstrap_token=SecretStr("bootstrap-token"),
            dev_auth=True,
            auto_create=True,
            ca_dir=tmp_path / "ca",
            public_base_url="http://testserver",
            ui_enabled=True,
        )
    return Settings(
        runtime=Runtime.PERSISTENT,
        database_url="sqlite+aiosqlite:///:memory:",
        db_driver="sqlite",
        secret_key=SecretStr("test-secret-key-that-is-long-enough-1234"),
        bootstrap_enabled=True,
        bootstrap_token=SecretStr("bootstrap-token"),
        dev_auth=True,
        auto_create=True,
        ca_dir=tmp_path / "ca",
        public_base_url="http://testserver",
        ui_enabled=True,
    )


@pytest.fixture
async def client(settings: Settings):
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as http:
            yield http


@pytest.fixture
async def admin(client: AsyncClient) -> dict:
    response = await client.post(
        "/v1/bootstrap",
        headers={"X-Bootstrap-Token": "bootstrap-token"},
        json={
            "workspace_slug": "acme",
            "workspace_name": "Acme",
            "owner_email": "owner@example.com",
            "password": "owner-password",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    return {
        "token": body["token"],
        "workspace": body["workspace"]["slug"],
        "headers": {"Authorization": f"Bearer {body['token']}"},
    }
