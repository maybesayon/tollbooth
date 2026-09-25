"""audit log

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-24 20:09:40.929140
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_log",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_type", sa.String(length=16), nullable=False),
        sa.Column("actor_id", sa.String(length=32), nullable=True),
        sa.Column("actor_label", sa.String(length=320), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=True),
        sa.Column("target_id", sa.String(length=64), nullable=True),
        sa.Column("details", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_log")),
    )
    with op.batch_alter_table("audit_log", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_audit_log_action"), ["action"], unique=False)
        batch_op.create_index(batch_op.f("ix_audit_log_actor_id"), ["actor_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_audit_log_created_at"), ["created_at"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("audit_log", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_audit_log_created_at"))
        batch_op.drop_index(batch_op.f("ix_audit_log_actor_id"))
        batch_op.drop_index(batch_op.f("ix_audit_log_action"))

    op.drop_table("audit_log")
