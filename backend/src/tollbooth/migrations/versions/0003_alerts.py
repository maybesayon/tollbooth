"""alerts

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-24 15:25:23.837706
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "alert_channels",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("url_hint", sa.String(length=200), nullable=False),
        sa.Column("encrypted_url", sa.Text(), nullable=False),
        sa.Column("encrypted_secret", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_alert_channels")),
        sa.UniqueConstraint("name", name=op.f("uq_alert_channels_name")),
    )
    op.create_table(
        "budget_alerts",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("budget_id", sa.String(length=32), nullable=False),
        sa.Column("budget_name", sa.String(length=200), nullable=False),
        sa.Column("threshold", sa.Integer(), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("spend_nanousd", sa.BigInteger(), nullable=False),
        sa.Column("limit_nanousd", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_budget_alerts")),
        sa.UniqueConstraint(
            "budget_id",
            "period_start",
            "threshold",
            name=op.f("uq_budget_alerts_budget_id_period_start_threshold"),
        ),
    )
    with op.batch_alter_table("budget_alerts", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_budget_alerts_created_at"), ["created_at"], unique=False
        )

    op.create_table(
        "alert_deliveries",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("alert_id", sa.String(length=32), nullable=False),
        sa.Column("channel_id", sa.String(length=32), nullable=False),
        sa.Column("channel_name", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["alert_id"],
            ["budget_alerts.id"],
            name=op.f("fk_alert_deliveries_alert_id_budget_alerts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_alert_deliveries")),
    )
    with op.batch_alter_table("alert_deliveries", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_alert_deliveries_alert_id"), ["alert_id"], unique=False
        )

    op.create_table(
        "budget_channels",
        sa.Column("budget_id", sa.String(length=32), nullable=False),
        sa.Column("channel_id", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(
            ["budget_id"],
            ["budgets.id"],
            name=op.f("fk_budget_channels_budget_id_budgets"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["channel_id"],
            ["alert_channels.id"],
            name=op.f("fk_budget_channels_channel_id_alert_channels"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("budget_id", "channel_id", name=op.f("pk_budget_channels")),
    )


def downgrade() -> None:
    op.drop_table("budget_channels")
    with op.batch_alter_table("alert_deliveries", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_alert_deliveries_alert_id"))

    op.drop_table("alert_deliveries")
    with op.batch_alter_table("budget_alerts", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_budget_alerts_created_at"))

    op.drop_table("budget_alerts")
    op.drop_table("alert_channels")
