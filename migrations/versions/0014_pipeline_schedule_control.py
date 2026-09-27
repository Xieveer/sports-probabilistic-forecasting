"""Сохранить настройки и идемпотентность control API Data Cycle.

Revision ID: 0014_pipeline_schedule_control
Revises: 0013_future_odds_acquisition
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0014_pipeline_schedule_control"
down_revision = "0013_future_odds_acquisition"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Добавить additive control-state таблицы без изменения serving schema."""
    op.add_column("data_cycle_runs", sa.Column("scheduled_for", sa.DateTime(), nullable=True))
    if op.get_bind().dialect.name == "postgresql":
        op.alter_column(
            "data_cycle_runs",
            "status",
            existing_type=sa.String(24),
            existing_nullable=False,
            server_default=sa.text("'waiting'"),
        )
        op.alter_column(
            "data_cycle_stage_results",
            "status",
            existing_type=sa.String(24),
            existing_nullable=False,
            server_default=sa.text("'waiting'"),
        )
    elif op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("data_cycle_runs") as batch:
            batch.alter_column(
                "status",
                existing_type=sa.String(24),
                existing_nullable=False,
                server_default=sa.text("'waiting'"),
            )
        with op.batch_alter_table("data_cycle_stage_results") as batch:
            batch.alter_column(
                "status",
                existing_type=sa.String(24),
                existing_nullable=False,
                server_default=sa.text("'waiting'"),
            )
    op.create_table(
        "pipeline_schedules",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("pipeline_id", sa.String(64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("base_time", sa.String(5), nullable=False, server_default="10:00"),
        sa.Column("timezone", sa.String(64), nullable=False, server_default="Europe/Moscow"),
        sa.Column("interval_hours", sa.Integer(), nullable=False, server_default="24"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("next_run_at", sa.DateTime(), nullable=True),
        sa.Column("last_run_at", sa.DateTime(), nullable=True),
        sa.Column("last_missed_slots", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("interval_hours IN (4,6,8,12,24)"),
        sa.CheckConstraint("revision >= 1"),
        sa.CheckConstraint("last_missed_slots >= 0"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("pipeline_id", name="uq_pipeline_schedules_pipeline"),
    )
    op.create_table(
        "data_cycle_control_requests",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("idempotency_key", sa.String(192), nullable=False),
        sa.Column("pipeline_id", sa.String(64), nullable=False),
        sa.Column("run_id", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["run_id"], ["data_cycle_runs.run_id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_data_cycle_control_idempotency"),
    )
    op.create_index(
        "ix_data_cycle_control_requests_run",
        "data_cycle_control_requests",
        ["run_id"],
    )
    op.create_table(
        "data_cycle_dispatcher_state",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("dispatcher_id", sa.String(64), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dispatcher_id", name="uq_data_cycle_dispatcher_id"),
    )


def downgrade() -> None:
    """Не удалять control state и run history; применять forward-fix."""
    raise RuntimeError("Destructive downgrade запрещён; используйте forward-fix migration.")
