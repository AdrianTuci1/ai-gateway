"""resource groups and trace spans

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-04

0001 materialises the whole metadata, so a fresh database already has these
tables. This revision only adds what an older database is missing, which keeps
both paths (fresh and upgraded) on the same schema.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    tables = _tables()
    if "resource_group" not in tables:
        op.create_table(
            "resource_group",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column(
                "workspace_id",
                sa.Uuid(),
                sa.ForeignKey("workspace.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column("name", sa.String(120), nullable=False),
            sa.Column("kind", sa.String(32), nullable=False, server_default="application"),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("workspace_id", "name", name="uq_group_workspace_name"),
        )

    for table in ("agent", "upstream_service"):
        if table in tables and "resource_group_id" not in _columns(table):
            op.add_column(table, sa.Column("resource_group_id", sa.Uuid(), nullable=True))
            op.create_index(
                f"ix_{table}_resource_group_id", table, ["resource_group_id"]
            )

    if "trace_span" not in tables:
        op.create_table(
            "trace_span",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column(
                "workspace_id",
                sa.Uuid(),
                sa.ForeignKey("workspace.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column("trace_id", sa.String(64), nullable=False, index=True),
            sa.Column("span_id", sa.String(32), nullable=False),
            sa.Column("parent_span_id", sa.String(32), nullable=True),
            sa.Column("name", sa.String(200), nullable=False),
            sa.Column("kind", sa.String(16), nullable=False, server_default="server"),
            sa.Column("status", sa.String(16), nullable=False, server_default="ok"),
            sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("actor_type", sa.String(16), nullable=True),
            sa.Column("actor_id", sa.Uuid(), nullable=True),
            sa.Column("attributes", sa.JSON(), nullable=False),
            sa.Column("started_at", sa.DateTime(), nullable=False, index=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )


def downgrade() -> None:
    tables = _tables()
    if "trace_span" in tables:
        op.drop_table("trace_span")
    for table in ("agent", "upstream_service"):
        if table in tables and "resource_group_id" in _columns(table):
            op.drop_index(f"ix_{table}_resource_group_id", table_name=table)
            op.drop_column(table, "resource_group_id")
    if "resource_group" in tables:
        op.drop_table("resource_group")
