"""local password authentication

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def _columns(bind, table: str) -> set[str]:
    inspector = sa.inspect(bind)
    if table not in inspector.get_table_names():
        return set()
    return {column["name"] for column in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    if "app_user" in sa.inspect(bind).get_table_names():
        if "password_hash" not in _columns(bind, "app_user"):
            op.add_column(
                "app_user",
                sa.Column("password_hash", sa.LargeBinary(), nullable=True),
            )


def downgrade() -> None:
    bind = op.get_bind()
    if "app_user" in sa.inspect(bind).get_table_names():
        if "password_hash" in _columns(bind, "app_user"):
            with op.batch_alter_table("app_user") as batch:
                batch.drop_column("password_hash")
