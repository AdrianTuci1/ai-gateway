from __future__ import annotations

import asyncio

from sqlalchemy import func, select
from typer.testing import CliRunner

from agw.cli import app
from agw.config import Settings
from agw.core.security import decode_session_token
from agw.db.models import AppUser, AuditEvent, Membership, RoleDefinition, Workspace
from agw.db.session import build_engine, build_sessionmaker


def _seed_workspace(settings: Settings) -> None:
    async def _seed() -> None:
        engine = build_engine(settings)
        try:
            async with build_sessionmaker(engine)() as session:
                session.add(Workspace(slug="acme", name="Acme"))
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(_seed())


def _demote_owner(settings: Settings, email: str) -> None:
    async def _demote() -> None:
        engine = build_engine(settings)
        try:
            async with build_sessionmaker(engine)() as session:
                viewer = (
                    await session.execute(
                        select(RoleDefinition).where(
                            RoleDefinition.workspace_id.is_(None),
                            RoleDefinition.name == "viewer",
                        )
                    )
                ).scalar_one()
                user = (
                    await session.execute(
                        select(AppUser).where(AppUser.email == email)
                    )
                ).scalar_one()
                membership = (
                    await session.execute(
                        select(Membership).where(
                            Membership.principal_type == "user",
                            Membership.principal_id == user.id,
                        )
                    )
                ).scalar_one()
                membership.role_id = viewer.id
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(_demote())


def test_admin_recover_restores_owner_and_audits(tmp_path, monkeypatch):
    database = tmp_path / "recover.db"
    monkeypatch.setenv("AGW_DATABASE_URL", f"sqlite+aiosqlite:///{database}")
    monkeypatch.setenv("AGW_CA_DIR", str(tmp_path / "ca"))
    monkeypatch.setenv("AGW_SECRET_KEY", "test-secret-key-that-is-long-enough-1234")
    runner = CliRunner()

    result = runner.invoke(app, ["migrate"])
    assert result.exit_code == 0, result.output

    settings = Settings()
    _seed_workspace(settings)

    result = runner.invoke(
        app,
        [
            "admin",
            "recover",
            "--workspace",
            "acme",
            "--user",
            "owner@example.com",
            "--reason",
            "lost IdP access",
            "--create-user",
            "--no-token",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "owner role restored" in result.output

    _demote_owner(settings, "owner@example.com")

    result = runner.invoke(
        app,
        [
            "admin",
            "recover",
            "--workspace",
            "acme",
            "--user",
            "owner@example.com",
            "--reason",
            "second recovery",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "owner role restored" in result.output

    token_line = next(
        line for line in result.output.splitlines() if "session token" in line
    )
    token = token_line.split(": ", 1)[1].strip()
    claims = decode_session_token(token, "test-secret-key-that-is-long-enough-1234")

    async def _verify() -> None:
        engine = build_engine(settings)
        try:
            async with build_sessionmaker(engine)() as session:
                user = (
                    await session.execute(
                        select(AppUser).where(AppUser.email == "owner@example.com")
                    )
                ).scalar_one()
                role = (
                    await session.execute(
                        select(RoleDefinition.name)
                        .join(Membership, Membership.role_id == RoleDefinition.id)
                        .where(Membership.principal_id == user.id)
                    )
                ).scalar_one()
                assert role == "owner"
                assert claims["sub"] == str(user.id)
                count = (
                    await session.execute(
                        select(func.count())
                        .select_from(AuditEvent)
                        .where(AuditEvent.action == "admin.recover")
                    )
                ).scalar_one()
                assert count == 2
        finally:
            await engine.dispose()

    asyncio.run(_verify())


def test_admin_recover_requires_create_user(tmp_path, monkeypatch):
    database = tmp_path / "recover-missing.db"
    monkeypatch.setenv("AGW_DATABASE_URL", f"sqlite+aiosqlite:///{database}")
    monkeypatch.setenv("AGW_CA_DIR", str(tmp_path / "ca"))
    monkeypatch.setenv("AGW_SECRET_KEY", "test-secret-key-that-is-long-enough-1234")
    runner = CliRunner()

    result = runner.invoke(app, ["migrate"])
    assert result.exit_code == 0, result.output
    _seed_workspace(Settings())

    result = runner.invoke(
        app,
        [
            "admin",
            "recover",
            "--workspace",
            "acme",
            "--user",
            "missing@example.com",
            "--reason",
            "test",
            "--no-token",
        ],
    )
    assert result.exit_code == 4
    assert "user not found" in result.output
