"""Создать durable outbox terminal Data Cycle notifications.

Revision ID: 0017_data_cycle_notification_outbox
Revises: 0016_control_stall_monotonic
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0017_data_cycle_notification_outbox"
down_revision = "0016_control_stall_monotonic"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Создать alias-only outbox с ограниченным lease lifecycle."""
    op.create_table(
        "data_cycle_notification_outbox",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.String(length=128), nullable=False),
        sa.Column("destination_alias", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("available_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("lease_token", sa.String(length=36), nullable=True),
        sa.Column("lease_until", sa.DateTime(), nullable=True),
        sa.Column("last_error_code", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("delivered_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint("status IN ('pending','leased','delivered')"),
        sa.CheckConstraint("attempts >= 0"),
        sa.CheckConstraint("length(destination_alias) BETWEEN 1 AND 64"),
        sa.ForeignKeyConstraint(["run_id"], ["data_cycle_runs.run_id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "run_id", "destination_alias", name="uq_data_cycle_notification_run_alias"
        ),
    )
    op.create_index(
        "ix_data_cycle_notification_claim",
        "data_cycle_notification_outbox",
        ["status", "available_at", "lease_until", "created_at"],
    )


def downgrade() -> None:
    """Удалить таблицу outbox, не изменяя историю циклов."""
    op.drop_index("ix_data_cycle_notification_claim", table_name="data_cycle_notification_outbox")
    op.drop_table("data_cycle_notification_outbox")
