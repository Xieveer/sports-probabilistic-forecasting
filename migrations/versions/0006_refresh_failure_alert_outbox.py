"""Добавить durable admin-only refresh failure alert outbox.

Revision ID: 0006_refresh_failure_alert_outbox
Revises: 0005_canonical_store_bootstrap
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0006_refresh_failure_alert_outbox"
down_revision = "0005_canonical_store_bootstrap"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Создать idempotent pending alert outbox без сетевых side effects."""
    op.create_table(
        "refresh_failure_alerts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.String(length=128), nullable=False),
        sa.Column("tournament", sa.String(length=64), nullable=False),
        sa.Column("failure_code", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id"),
    )
    op.create_index(
        "ix_refresh_failure_alerts_tournament", "refresh_failure_alerts", ["tournament"]
    )


def downgrade() -> None:
    """Destructive downgrade запрещён: используйте forward-fix migration."""
    raise RuntimeError("Destructive downgrade запрещён; используйте forward-fix migration.")
