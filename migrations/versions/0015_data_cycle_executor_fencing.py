"""Добавить generation и stop evidence для Data Cycle executor recovery.

Revision ID: 0015_data_cycle_executor_fencing
Revises: 0014_pipeline_schedule_control
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0015_data_cycle_executor_fencing"
down_revision = "0014_pipeline_schedule_control"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Расширить lifecycle additive полями owner без снятия active-run guard."""
    op.add_column(
        "data_cycle_runs",
        sa.Column("executor_generation", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("data_cycle_runs", sa.Column("executor_owner_id", sa.String(64), nullable=True))
    op.add_column("data_cycle_runs", sa.Column("executor_stalled_at", sa.DateTime(), nullable=True))
    op.add_column(
        "data_cycle_runs", sa.Column("owner_stop_verified_at", sa.DateTime(), nullable=True)
    )
    op.add_column(
        "data_cycle_runs", sa.Column("stopped_container_count", sa.Integer(), nullable=True)
    )
    with op.batch_alter_table("data_cycle_runs") as batch:
        batch.create_check_constraint(
            "ck_data_cycle_runs_executor_generation", "executor_generation >= 0"
        )
        batch.create_check_constraint(
            "ck_data_cycle_runs_stopped_container_count",
            "stopped_container_count IS NULL OR stopped_container_count >= 0",
        )


def downgrade() -> None:
    """Удалить только новые executor metadata fields; run history остаётся intact."""
    with op.batch_alter_table("data_cycle_runs") as batch:
        batch.drop_constraint("ck_data_cycle_runs_stopped_container_count", type_="check")
        batch.drop_constraint("ck_data_cycle_runs_executor_generation", type_="check")
        batch.drop_column("stopped_container_count")
        batch.drop_column("owner_stop_verified_at")
        batch.drop_column("executor_stalled_at")
        batch.drop_column("executor_owner_id")
        batch.drop_column("executor_generation")
