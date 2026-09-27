"""Сохранить источник и получение будущих Pinnacle odds."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0013_future_odds_acquisition"
down_revision = "0012_data_cycle_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Добавить retrieved provenance и журнал batch-попыток без потери истории."""
    op.add_column("odds_observations", sa.Column("retrieved_at", sa.DateTime(), nullable=True))
    op.add_column(
        "odds_observations", sa.Column("observed_at_source", sa.String(64), nullable=True)
    )
    op.add_column(
        "odds_observations", sa.Column("provider_event_id", sa.String(128), nullable=True)
    )
    op.create_table(
        "odds_acquisition_attempts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.String(128), nullable=False),
        sa.Column("tournament", sa.String(64), nullable=False),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("failure_code", sa.String(64), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(), nullable=False),
        sa.Column("window_from", sa.DateTime(), nullable=True),
        sa.Column("window_to", sa.DateTime(), nullable=True),
        sa.Column("provider_events", sa.Integer(), nullable=False),
        sa.Column("matched_events", sa.Integer(), nullable=False),
        sa.Column("missing_events", sa.Integer(), nullable=False),
        sa.Column("rejected_events", sa.Integer(), nullable=False),
        sa.Column("requests_remaining", sa.Integer(), nullable=True),
        sa.Column("requests_used", sa.Integer(), nullable=True),
        sa.CheckConstraint("status IN ('success','partial_success','failed')"),
        sa.ForeignKeyConstraint(["run_id"], ["data_cycle_runs.run_id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "provider", name="uq_odds_attempt_run_provider"),
    )
    op.create_index(
        "ix_odds_acquisition_attempt_tournament",
        "odds_acquisition_attempts",
        ["tournament", "retrieved_at"],
    )


def downgrade() -> None:
    """Не удалять журнал попыток и provenance; откат выполнять forward-fix."""
    raise RuntimeError("Destructive downgrade запрещён; используйте forward-fix migration.")
