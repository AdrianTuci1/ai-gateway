"""baseline schema

Revision ID: 0001
Revises:
Create Date: 2026-11-02
"""

from __future__ import annotations

from alembic import op

from agw.db.base import Base
from agw.db import models  # noqa: F401 - register mappings

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The baseline materialises the SQLAlchemy metadata. Later revisions use
    # explicit op.create_table calls.
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
