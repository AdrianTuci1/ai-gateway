from __future__ import annotations

import asyncio
import json
import os
import uuid
from pathlib import Path

import typer
from sqlalchemy import func, select

from agw.audit.service import record
from agw.config import Runtime, Settings
from agw.core.roles import seed_builtin_roles
from agw.core.security import create_session_token, hash_secret
from agw.core.time import utcnow
from agw.db.models import AppUser, Identity, Membership, RoleDefinition, Workspace
from agw.db.session import build_engine, build_sessionmaker
from agw.store import build_store_provider
from agw.store.sql import SqlStore

app = typer.Typer(no_args_is_help=True, add_completion=False)
admin_app = typer.Typer(no_args_is_help=True)
app.add_typer(admin_app, name="admin")


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8080, "--port"),
    runtime: Runtime = typer.Option(Runtime.PERSISTENT, "--runtime"),
    reload: bool = typer.Option(False, "--reload"),
    create: bool = typer.Option(False, "--create", help="Create tables at startup"),
    check: bool = typer.Option(False, "--check", help="Validate configuration and exit"),
) -> None:
    """Start the gateway API."""
    os.environ["AGW_RUNTIME"] = runtime.value
    if create:
        os.environ["AGW_AUTO_CREATE"] = "true"
    if check:

        async def _check() -> None:
            settings = Settings()
            provider = build_store_provider(settings)
            try:
                async with provider.store() as store:
                    await store.ping()
                typer.echo(
                    f"ok backend={settings.db_backend} "
                    f"runtime={settings.runtime.value} features={json.dumps(settings.features)}"
                )
            finally:
                await provider.shutdown()

        asyncio.run(_check())
        return
    import uvicorn

    uvicorn.run("agw.main:app", host=host, port=port, reload=reload)


def _run_migrations(settings: Settings) -> None:
    from alembic import command
    from alembic.config import Config

    project_root = Path(
        os.environ.get("AGW_PROJECT_ROOT", str(Path(__file__).resolve().parents[2]))
    )
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("script_location", str(project_root / "migrations"))
    config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))
    command.upgrade(config, "head")


@app.command()
def migrate() -> None:
    """Prepare storage and seed builtin roles.

    SQL backends run Alembic first; DynamoDB creates no schema and only
    needs the builtin role items seeded idempotently.
    """
    settings = Settings()
    if not settings.uses_dynamodb:
        _run_migrations(settings)

    async def _seed() -> None:
        provider = build_store_provider(settings)
        try:
            await provider.startup()
        finally:
            await provider.shutdown()

    asyncio.run(_seed())
    typer.echo(f"storage ready ({settings.db_backend})")


@admin_app.command("recover")
def admin_recover(
    user: str = typer.Option(..., "--user", prompt=True, help="Email of the user to restore"),
    reason: str = typer.Option(..., "--reason", prompt=True, help="Why recovery is needed"),
    workspace: str = typer.Option(
        None, "--workspace", help="Workspace slug; inferred when only one exists"
    ),
    create_user: bool = typer.Option(
        False, "--create-user", help="Create the user when the email is unknown"
    ),
    print_token: bool = typer.Option(
        True, "--token/--no-token", help="Print a fresh session token"
    ),
    password: str = typer.Option(
        None, "--password", help="Set or reset a local password for the user"
    ),
) -> None:
    """Restore the owner role for a user and record the action in audit."""
    email = user.strip().lower()
    note = reason.strip()
    if not email:
        typer.echo("--user is required", err=True)
        raise typer.Exit(2)
    if not note:
        typer.echo("--reason is required", err=True)
        raise typer.Exit(2)
    if password is not None and len(password) < 8:
        typer.echo("--password must be at least 8 characters", err=True)
        raise typer.Exit(2)

    settings = Settings()
    if settings.uses_dynamodb:
        typer.echo(
            "admin recover is available on self-hosted SQL backends only; "
            "on DynamoDB use an operator role through the HTTP API",
            err=True,
        )
        raise typer.Exit(2)

    async def _recover() -> tuple[str, str, bool, bool, str]:
        engine = build_engine(settings)
        try:
            async with build_sessionmaker(engine)() as session:
                store = SqlStore(session)
                await seed_builtin_roles(store)

                if workspace:
                    target = (
                        await session.execute(
                            select(Workspace).where(Workspace.slug == workspace)
                        )
                    ).scalar_one_or_none()
                    if target is None:
                        typer.echo(f"workspace not found: {workspace}", err=True)
                        raise typer.Exit(4)
                else:
                    workspaces = (await session.execute(select(Workspace))).scalars().all()
                    if len(workspaces) != 1:
                        typer.echo(
                            f"pass --workspace; found {len(workspaces)} workspaces", err=True
                        )
                        raise typer.Exit(2)
                    target = workspaces[0]

                owner_role = await store.get_builtin_role("owner")
                account = (
                    await session.execute(
                        select(AppUser).where(func.lower(AppUser.email) == email)
                    )
                ).scalar_one_or_none()
                if account is None:
                    account = (
                        await session.execute(
                            select(AppUser).where(AppUser.idp_subject == f"local:{email}")
                        )
                    ).scalar_one_or_none()
                created = False
                if account is None:
                    if not create_user:
                        typer.echo(
                            f"user not found: {email}; pass --create-user", err=True
                        )
                        raise typer.Exit(4)
                    account = AppUser(idp_subject=f"local:{email}", email=email)
                    session.add(account)
                    await session.flush()
                    created = True

                if password:
                    account.password_hash = hash_secret(password)

                membership = (
                    await session.execute(
                        select(Membership).where(
                            Membership.workspace_id == target.id,
                            Membership.principal_type == "user",
                            Membership.principal_id == account.id,
                        )
                    )
                ).scalar_one_or_none()
                previous_role = None
                changed = False
                if membership is None:
                    identity = Identity(
                        workspace_id=target.id,
                        name=account.display_name or account.email,
                        status="active",
                        created_at=utcnow(),
                    )
                    session.add(identity)
                    await session.flush()
                    session.add(
                        Membership(
                            workspace_id=target.id,
                            principal_type="user",
                            principal_id=account.id,
                            role_id=owner_role.id,
                            identity_id=identity.id,
                            is_identity_admin=True,
                        )
                    )
                    changed = True
                else:
                    old_role = await session.get(RoleDefinition, membership.role_id)
                    previous_role = old_role.name if old_role else None
                    if membership.role_id != owner_role.id:
                        membership.role_id = owner_role.id
                        changed = True
                    if membership.identity_id is None:
                        identity = Identity(
                            workspace_id=target.id,
                            name=account.display_name or account.email,
                            status="active",
                            created_at=utcnow(),
                        )
                        session.add(identity)
                        await session.flush()
                        membership.identity_id = identity.id
                        membership.is_identity_admin = True
                        changed = True

                await record(
                    store,
                    workspace_id=target.id,
                    actor_type="system",
                    actor_id=None,
                    action="admin.recover",
                    trace_id=uuid.uuid4().hex,
                    resource_type="user",
                    resource_id=str(account.id),
                    decision="allow",
                    reason=note,
                    meta={
                        "email": email,
                        "workspace": target.slug,
                        "created_user": created,
                        "changed": changed,
                        "previous_role": previous_role,
                    },
                )
                await session.commit()
                session_token = (
                    create_session_token(
                        account.id,
                        target.id,
                        settings.session_secret,
                        settings.session_ttl_hours,
                    )
                    if print_token
                    else ""
                )
                return target.slug, str(account.id), changed, created, session_token
        finally:
            await engine.dispose()

    slug, user_id, changed, created, session_token = asyncio.run(_recover())
    typer.echo(f"workspace: {slug}")
    typer.echo(f"user: {user_id} ({email})")
    if created:
        typer.echo("user created")
    if changed:
        typer.echo("owner role restored")
    else:
        typer.echo("user already had the owner role")
    typer.echo("admin.recover recorded in audit")
    if session_token:
        typer.echo(f"session token (shown once): {session_token}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
