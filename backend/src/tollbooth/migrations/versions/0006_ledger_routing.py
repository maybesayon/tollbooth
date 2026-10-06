"""ledger routing

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-06 18:38:01.620716
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("ledger", schema=None) as batch_op:
        batch_op.add_column(sa.Column("route", sa.String(length=200), nullable=True))
        batch_op.add_column(sa.Column("attempts", sa.Integer(), server_default="1", nullable=False))


def downgrade() -> None:
    with op.batch_alter_table("ledger", schema=None) as batch_op:
        batch_op.drop_column("attempts")
        batch_op.drop_column("route")
