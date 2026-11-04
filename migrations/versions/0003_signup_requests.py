"""self-service signup requests

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-04

0001 materialises the whole metadata, so a fresh database already has these
tables and columns. This revision only adds what an older database is missing.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    tables = _tables()

    if "membership" in tables and "status" not in _columns("membership"):
        op.add_column(
            "membership",
            sa.Column(
                "status", sa.String(16), nullable=False, server_default="active"
            ),
        )

    if "signup_request" not in tables:
        op.create_table(
            "signup_request",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column(
                "workspace_id",
                sa.Uuid(),
                sa.ForeignKey("workspace.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column("kind", sa.String(8), nullable=False),
            sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
            sa.Column("email", sa.String(320), nullable=True),
            sa.Column("display_name", sa.String(200), nullable=True),
            sa.Column("agent_name", sa.String(200), nullable=True),
            sa.Column("agent_slug", sa.String(80), nullable=True),
            sa.Column("requested_role", sa.String(80), nullable=True),
            sa.Column("message", sa.Text(), nullable=True),
            sa.Column("principal_id", sa.Uuid(), nullable=True),
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
        op.create_index(
            "ix_signup_request_workspace_status",
            "signup_request",
            ["workspace_id", "status"],
        )


def downgrade() -> None:
    tables = _tables()
    if "signup_request" in tables:
        op.drop_table("signup_request")
    if "membership" in tables and "status" in _columns("membership"):
        op.drop_column("membership", "status")
