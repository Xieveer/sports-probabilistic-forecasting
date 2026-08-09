"""Добавить безопасный execution state bounded Worker.

Revision ID: 0004_worker_execution_state
Revises: 0003_lineup_fast_path
Create Date: 2026-08-09
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0004_worker_execution_state"
down_revision = "0003_lineup_fast_path"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Добавить lifecycle state без изменения действующей prediction-витрины."""
    op.create_table(
        "worker_executions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("predictions_count", sa.Integer(), nullable=True),
        sa.Column("failure_code", sa.String(length=64), nullable=True),
        sa.Column(
            "started_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id"),
    )
    op.create_index("ix_worker_executions_status", "worker_executions", ["status"])


def downgrade() -> None:
    """Destructive downgrade запрещён: используйте forward-fix migration."""
    raise RuntimeError("Destructive downgrade запрещён; используйте forward-fix migration.")
