"""Добавить per-tournament refresh lock.

Revision ID: 0007_refresh_lock
Revises: 0006_refresh_failure_alert_outbox
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0007_refresh_lock"
down_revision = "0006_refresh_failure_alert_outbox"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "refresh_locks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tournament", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(length=128), nullable=False),
        sa.Column(
            "acquired_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tournament"),
    )


def downgrade() -> None:
    raise RuntimeError("Destructive downgrade запрещён; используйте forward-fix migration.")
