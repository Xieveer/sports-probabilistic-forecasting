"""Сохранить lifecycle запусков полного Data Cycle.

Revision ID: 0012_data_cycle_runs
Revises: 0011_event_odds_observations
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0012_data_cycle_runs"
down_revision = "0011_event_odds_observations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Создать append-history запусков со стадиями и одним active run на турнир."""
    op.add_column(
        "calendar_coverages", sa.Column("last_successful_at", sa.DateTime(), nullable=True)
    )
    op.execute(
        "UPDATE calendar_coverages SET last_successful_at = checked_at "
        "WHERE complete = TRUE AND failure_code IS NULL"
    )
    op.create_table(
        "data_cycle_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.String(128), nullable=False),
        sa.Column("tournament", sa.String(64), nullable=False),
        sa.Column("reason", sa.String(16), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("current_stage", sa.String(32), nullable=True),
        sa.Column("failure_code", sa.String(64), nullable=True),
        sa.Column("summary_json", sa.Text(), nullable=True),
        sa.Column(
            "requested_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint("status IN ('waiting','running','success','partial_success','failed')"),
        sa.CheckConstraint("reason IN ('scheduled','manual','retry')"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", name="uq_data_cycle_run_id"),
    )
    op.create_index("ix_data_cycle_runs_tournament", "data_cycle_runs", ["tournament"])
    op.create_index(
        "ix_data_cycle_runs_requested", "data_cycle_runs", ["tournament", "requested_at"]
    )
    op.create_index(
        "uq_data_cycle_active_tournament",
        "data_cycle_runs",
        ["tournament"],
        unique=True,
        sqlite_where=sa.text("status IN ('waiting', 'running')"),
        postgresql_where=sa.text("status IN ('waiting', 'running')"),
    )
    op.create_table(
        "data_cycle_stage_results",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.String(128), nullable=False),
        sa.Column("stage", sa.String(32), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("failure_code", sa.String(64), nullable=True),
        sa.Column("counts_json", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "stage IN ('calendar','data_odds','quality','predictions','publication','archive_sync')"
        ),
        sa.CheckConstraint(
            "status IN ('waiting','running','success','partial_success','failed','skipped')"
        ),
        sa.ForeignKeyConstraint(["run_id"], ["data_cycle_runs.run_id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "stage", name="uq_data_cycle_stage"),
    )
    op.create_index("ix_data_cycle_stage_results_run_id", "data_cycle_stage_results", ["run_id"])
    op.create_index(
        "ix_data_cycle_stages_run_status",
        "data_cycle_stage_results",
        ["run_id", "status"],
    )


def downgrade() -> None:
    """Не удалять эксплуатационную историю; откат выполняется forward-fix."""
    raise RuntimeError("Destructive downgrade запрещён; используйте forward-fix migration.")
