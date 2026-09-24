"""budgets

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-24 15:20:28.566458
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "budgets",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("scope", sa.String(length=16), nullable=False),
        sa.Column("scope_value", sa.String(length=200), nullable=True),
        sa.Column("period", sa.String(length=16), nullable=False),
        sa.Column("limit_nanousd", sa.BigInteger(), nullable=False),
        sa.Column("enforcement", sa.String(length=16), nullable=False),
        sa.Column("thresholds", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_budgets")),
    )
    with op.batch_alter_table("budgets", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_budgets_scope_scope_value"), ["scope", "scope_value"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("budgets", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_budgets_scope_scope_value"))

    op.drop_table("budgets")
