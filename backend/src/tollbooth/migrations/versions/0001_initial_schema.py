"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-09-24 14:24:30.032158
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ledger",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("team", sa.String(length=200), nullable=False),
        sa.Column("virtual_key_id", sa.String(length=32), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=200), nullable=False),
        sa.Column("streamed", sa.Boolean(), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("ttfb_ms", sa.Integer(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("cache_read_tokens", sa.Integer(), nullable=False),
        sa.Column("cache_write_tokens", sa.Integer(), nullable=False),
        sa.Column("cache_write_1h_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_nanousd", sa.BigInteger(), nullable=True),
        sa.Column("error_type", sa.String(length=200), nullable=True),
        sa.Column("upstream_request_id", sa.String(length=200), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ledger")),
    )
    with op.batch_alter_table("ledger", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_ledger_created_at"), ["created_at"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_ledger_team_created_at"), ["team", "created_at"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_ledger_virtual_key_id_created_at"),
            ["virtual_key_id", "created_at"],
            unique=False,
        )

    op.create_table(
        "provider_credentials",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("encrypted_key", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_provider_credentials")),
        sa.UniqueConstraint("name", name=op.f("uq_provider_credentials_name")),
    )
    op.create_table(
        "virtual_keys",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("team", sa.String(length=200), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("key_prefix", sa.String(length=16), nullable=False),
        sa.Column("credential_id", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["credential_id"],
            ["provider_credentials.id"],
            name=op.f("fk_virtual_keys_credential_id_provider_credentials"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_virtual_keys")),
        sa.UniqueConstraint("key_hash", name=op.f("uq_virtual_keys_key_hash")),
    )
    with op.batch_alter_table("virtual_keys", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_virtual_keys_team"), ["team"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("virtual_keys", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_virtual_keys_team"))

    op.drop_table("virtual_keys")
    op.drop_table("provider_credentials")
    with op.batch_alter_table("ledger", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_ledger_virtual_key_id_created_at"))
        batch_op.drop_index(batch_op.f("ix_ledger_team_created_at"))
        batch_op.drop_index(batch_op.f("ix_ledger_created_at"))

    op.drop_table("ledger")
