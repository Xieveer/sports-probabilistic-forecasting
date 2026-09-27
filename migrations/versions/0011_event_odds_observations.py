"""Хранить подтверждённые odds observation отдельно от Prediction.

Revision ID: 0011_event_odds_observations
Revises: 0010_calendar_coverage_and_participants
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0011_event_odds_observations"
down_revision = "0010_calendar_coverage_and_participants"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Добавить проекцию времени наблюдения коэффициентов по событию."""
    op.create_table(
        "odds_observations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("canonical_event_id", sa.Integer(), nullable=False),
        sa.Column("market", sa.String(32), nullable=False),
        sa.Column("market_spec", sa.String(64), nullable=False),
        sa.Column("bookmaker", sa.String(64), nullable=False),
        sa.Column("event_scheduled_at", sa.DateTime(), nullable=False),
        sa.Column("event_home_participant", sa.String(128), nullable=False),
        sa.Column("event_away_participant", sa.String(128), nullable=False),
        sa.Column("observed_at", sa.DateTime(), nullable=False),
        sa.Column("values_json", sa.Text(), nullable=False),
        sa.Column("source", sa.String(128), nullable=False),
        sa.ForeignKeyConstraint(["canonical_event_id"], ["canonical_events.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "canonical_event_id",
            "market",
            "market_spec",
            "bookmaker",
            name="uq_odds_observation_event_market_bookmaker",
        ),
    )
    op.create_index(
        "ix_odds_observations_canonical_event_id",
        "odds_observations",
        ["canonical_event_id"],
    )
    op.create_index(
        "ix_odds_observation_event",
        "odds_observations",
        ["canonical_event_id", "observed_at"],
    )


def downgrade() -> None:
    """Запретить удаление сохранённого source observation."""
    raise RuntimeError("Destructive downgrade запрещён; используйте forward-fix migration.")
