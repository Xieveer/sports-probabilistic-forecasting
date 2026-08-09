"""Добавить revision и outbox confirmed-lineup fast path.

Revision ID: 0003_lineup_fast_path
Revises: 0002_model_registry_provenance
Create Date: 2026-08-09
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0003_lineup_fast_path"
down_revision = "0002_model_registry_provenance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Добавить DB-first revision и delivery outbox без изменения predictions."""
    op.create_table(
        "lineup_prediction_revisions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("match_id", sa.String(length=64), nullable=False),
        sa.Column("tournament", sa.String(length=64), nullable=False),
        sa.Column("model_pool", sa.String(length=128), nullable=False),
        sa.Column("immutable_model_version", sa.String(length=192), nullable=False),
        sa.Column("lineup_state", sa.String(length=16), nullable=False),
        sa.Column("lineup_source", sa.String(length=128), nullable=False),
        sa.Column("lineup_received_at", sa.DateTime(), nullable=False),
        sa.Column("lineup_fingerprint", sa.String(length=192), nullable=False),
        sa.Column("prediction_json", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("lineup_fingerprint"),
    )
    op.create_table(
        "lineup_notification_outbox",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("revision_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("revision_id"),
    )


def downgrade() -> None:
    """Destructive downgrade запрещён: используйте forward-fix migration."""
    raise RuntimeError("Destructive downgrade запрещён; используйте forward-fix migration.")
