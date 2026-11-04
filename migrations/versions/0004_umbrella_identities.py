"""umbrella identities and invite links

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-04

0001 materialises the whole metadata, so a fresh database already has these
tables and columns. The upgrade path adds them to older databases and groups
existing memberships under one identity per person where possible.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def _tables(bind) -> set[str]:
    return set(sa.inspect(bind).get_table_names())


def _columns(bind, table: str) -> set[str]:
    if table not in _tables(bind):
        return set()
    return {column["name"] for column in sa.inspect(bind).get_columns(table)}


def _indexes(bind, table: str) -> set[str]:
    if table not in _tables(bind):
        return set()
    return {index["name"] for index in sa.inspect(bind).get_indexes(table)}


def upgrade() -> None:
    bind = op.get_bind()
    tables = _tables(bind)

    if "membership" in tables:
        if "identity_id" not in _columns(bind, "membership"):
            op.add_column("membership", sa.Column("identity_id", sa.Uuid(), nullable=True))
        if "is_identity_admin" not in _columns(bind, "membership"):
            op.add_column(
                "membership",
                sa.Column(
                    "is_identity_admin",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.false(),
                ),
            )
        if "ix_membership_identity_id" not in _indexes(bind, "membership"):
            op.create_index("ix_membership_identity_id", "membership", ["identity_id"])

    if "signup_request" in tables:
        if "identity_id" not in _columns(bind, "signup_request"):
            op.add_column(
                "signup_request", sa.Column("identity_id", sa.Uuid(), nullable=True)
            )
        if "identity_name" not in _columns(bind, "signup_request"):
            op.add_column(
                "signup_request",
                sa.Column("identity_name", sa.String(200), nullable=True),
            )
        if "owner_email" not in _columns(bind, "signup_request"):
            op.add_column(
                "signup_request",
                sa.Column("owner_email", sa.String(320), nullable=True),
            )
        if "ix_signup_request_identity_id" not in _indexes(bind, "signup_request"):
            op.create_index(
                "ix_signup_request_identity_id", "signup_request", ["identity_id"]
            )

    if "identity" not in tables:
        op.create_table(
            "identity",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column(
                "workspace_id",
                sa.Uuid(),
                sa.ForeignKey("workspace.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column("name", sa.String(200), nullable=False),
            sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
            sa.Column(
                "decided_by",
                sa.Uuid(),
                sa.ForeignKey("app_user.id"),
                nullable=True,
            ),
            sa.Column("decided_at", sa.DateTime(), nullable=True),
            sa.Column("decision_note", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
    if "ix_identity_workspace_status" not in _indexes(bind, "identity"):
        op.create_index(
            "ix_identity_workspace_status", "identity", ["workspace_id", "status"]
        )

    if "identity_invite" not in tables:
        op.create_table(
            "identity_invite",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column(
                "identity_id",
                sa.Uuid(),
                sa.ForeignKey("identity.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column(
                "workspace_id",
                sa.Uuid(),
                sa.ForeignKey("workspace.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column("email", sa.String(320), nullable=False, index=True),
            sa.Column(
                "role_id",
                sa.Uuid(),
                sa.ForeignKey("role_definition.id"),
                nullable=False,
            ),
            sa.Column("token_hash", sa.LargeBinary(), nullable=False, unique=True),
            sa.Column("created_by", sa.Uuid(), nullable=True),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("consumed_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )

    _backfill(bind)


def _backfill(bind) -> None:
    meta = sa.MetaData()
    membership = sa.Table("membership", meta, autoload_with=bind)
    identity = sa.Table("identity", meta, autoload_with=bind)
    app_user = sa.Table("app_user", meta, autoload_with=bind)
    agent = sa.Table("agent", meta, autoload_with=bind)
    signup = sa.Table("signup_request", meta, autoload_with=bind)
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    def new_identity(workspace_id, name, status) -> uuid.UUID:
        identity_id = uuid.uuid4()
        if bind.dialect.name == "sqlite":
            # Reflected SQLite CHAR(32) columns do not accept UUID objects.
            identity_id = identity_id.hex
        bind.execute(
            identity.insert().values(
                id=identity_id,
                workspace_id=workspace_id,
                name=name or "Identity",
                status=status or "active",
                created_at=now,
            )
        )
        return identity_id

    rows = list(
        bind.execute(
            sa.select(membership).where(
                membership.c.principal_type == "user",
                membership.c.identity_id.is_(None),
            )
        ).mappings()
    )
    for row in rows:
        user = bind.execute(
            sa.select(app_user).where(app_user.c.id == row["principal_id"])
        ).mappings().first()
        label = (
            (user["display_name"] or user["email"])
            if user is not None
            else "Identity"
        )
        identity_id = new_identity(
            row["workspace_id"], label, row["status"] or "active"
        )
        bind.execute(
            membership.update()
            .where(membership.c.id == row["id"])
            .values(identity_id=identity_id, is_identity_admin=True)
        )

    rows = list(
        bind.execute(
            sa.select(membership).where(
                membership.c.principal_type == "agent",
                membership.c.identity_id.is_(None),
            )
        ).mappings()
    )
    for row in rows:
        agent_row = bind.execute(
            sa.select(agent).where(agent.c.id == row["principal_id"])
        ).mappings().first()
        identity_id = None
        if agent_row is not None and agent_row["created_by"] is not None:
            owner = bind.execute(
                sa.select(membership).where(
                    membership.c.workspace_id == row["workspace_id"],
                    membership.c.principal_type == "user",
                    membership.c.principal_id == agent_row["created_by"],
                    membership.c.identity_id.is_not(None),
                )
            ).mappings().first()
            if owner is not None:
                identity_id = owner["identity_id"]
        is_admin = identity_id is None
        if identity_id is None:
            label = agent_row["name"] if agent_row is not None else "Agent"
            identity_id = new_identity(
                row["workspace_id"], label, row["status"] or "active"
            )
        bind.execute(
            membership.update()
            .where(membership.c.id == row["id"])
            .values(identity_id=identity_id, is_identity_admin=is_admin)
        )

    rows = list(
        bind.execute(
            sa.select(signup).where(signup.c.identity_id.is_(None))
        ).mappings()
    )
    for row in rows:
        identity_id = None
        if row["kind"] == "user" and row["email"]:
            user = bind.execute(
                sa.select(app_user).where(app_user.c.email == row["email"])
            ).mappings().first()
            if user is not None:
                owner = bind.execute(
                    sa.select(membership).where(
                        membership.c.workspace_id == row["workspace_id"],
                        membership.c.principal_type == "user",
                        membership.c.principal_id == user["id"],
                        membership.c.identity_id.is_not(None),
                    )
                ).mappings().first()
                if owner is not None:
                    identity_id = owner["identity_id"]
            label = row["display_name"] or row["email"]
        else:
            label = row["identity_name"] or row["agent_name"] or row["agent_slug"]
        if identity_id is None:
            identity_id = new_identity(row["workspace_id"], label, row["status"])
        bind.execute(
            signup.update()
            .where(signup.c.id == row["id"])
            .values(identity_id=identity_id, identity_name=label)
        )


def downgrade() -> None:
    bind = op.get_bind()
    tables = _tables(bind)
    if "membership" in tables:
        if "ix_membership_identity_id" in _indexes(bind, "membership"):
            op.drop_index("ix_membership_identity_id", table_name="membership")
        with op.batch_alter_table("membership") as batch:
            if "is_identity_admin" in _columns(bind, "membership"):
                batch.drop_column("is_identity_admin")
            if "identity_id" in _columns(bind, "membership"):
                batch.drop_column("identity_id")
    if "signup_request" in tables:
        if "ix_signup_request_identity_id" in _indexes(bind, "signup_request"):
            op.drop_index("ix_signup_request_identity_id", table_name="signup_request")
        with op.batch_alter_table("signup_request") as batch:
            for column in ("identity_name", "owner_email", "identity_id"):
                if column in _columns(bind, "signup_request"):
                    batch.drop_column(column)
    if "identity_invite" in tables:
        op.drop_table("identity_invite")
    if "identity" in tables:
        op.drop_table("identity")
