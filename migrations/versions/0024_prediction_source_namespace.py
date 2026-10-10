"""Разделить текущую prediction-витрину по namespace источника.

Revision ID: 0024_prediction_source_namespace
Revises: 0023_prediction_revisions
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0024_prediction_source_namespace"
down_revision = "0023_prediction_revisions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Добавить nullable source namespace, не угадывая его для legacy rows."""
    with op.batch_alter_table("predictions") as batch_op:
        batch_op.add_column(sa.Column("source_namespace", sa.String(length=128), nullable=True))
    op.create_index(
        "ix_prediction_source_event_market",
        "predictions",
        ["tournament", "source_namespace", "match_id", "market", "market_spec"],
    )


def downgrade() -> None:
    """Удаление source provenance запрещено; используйте forward-fix migration."""
    raise RuntimeError("Destructive downgrade запрещён; используйте forward-fix migration.")
