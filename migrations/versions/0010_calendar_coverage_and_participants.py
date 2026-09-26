"""Добавить календарные атрибуты и coverage без изменения canonical revisions.

Revision ID: 0010_calendar_coverage_and_participants
Revises: 0009_prediction_refresh_provenance
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0010_calendar_coverage_and_participants"
down_revision = "0009_prediction_refresh_provenance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Добавить nullable participant fields и календарный coverage state."""
    op.add_column("canonical_events", sa.Column("home_participant", sa.String(128)))
    op.add_column("canonical_events", sa.Column("away_participant", sa.String(128)))
    op.create_table(
        "calendar_coverages",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tournament", sa.String(64), nullable=False),
        sa.Column("source", sa.String(128), nullable=False),
        sa.Column("covered_from", sa.DateTime(), nullable=False),
        sa.Column("covered_until", sa.DateTime(), nullable=False),
        sa.Column("complete", sa.Boolean(), nullable=False),
        sa.Column("checked_at", sa.DateTime(), nullable=False),
        sa.Column("failure_code", sa.String(64), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tournament", "source", name="uq_calendar_coverage_source"),
    )
    op.create_index(
        "ix_calendar_coverages_window",
        "calendar_coverages",
        ["tournament", "covered_from", "covered_until"],
    )


def downgrade() -> None:
    """Запретить destructive downgrade canonical calendar fields."""
    raise RuntimeError("Destructive downgrade запрещён; используйте forward-fix migration.")
