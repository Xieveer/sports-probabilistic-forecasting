"""Добавить refresh/data/feature provenance prediction-витрины.

Revision ID: 0009_prediction_refresh_provenance
Revises: 0008_tournament_publication_state
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0009_prediction_refresh_provenance"
down_revision = "0008_tournament_publication_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("predictions", sa.Column("refresh_run_id", sa.String(length=128), nullable=True))
    op.add_column(
        "predictions", sa.Column("canonical_snapshot_id", sa.String(length=128), nullable=True)
    )
    op.add_column(
        "predictions", sa.Column("feature_contract_id", sa.String(length=128), nullable=True)
    )
    op.create_index("ix_predictions_refresh_run_id", "predictions", ["refresh_run_id"])
    op.create_index(
        "ix_predictions_canonical_snapshot_id", "predictions", ["canonical_snapshot_id"]
    )


def downgrade() -> None:
    raise RuntimeError("Destructive downgrade запрещён; используйте forward-fix migration.")
