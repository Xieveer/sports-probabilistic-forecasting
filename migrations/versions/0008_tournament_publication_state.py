"""Добавить durable public eligibility витрин.

Revision ID: 0008_tournament_publication_state
Revises: 0007_refresh_lock
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0008_tournament_publication_state"
down_revision = "0007_refresh_lock"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Создать additive state без изменения существующих prediction rows."""
    op.create_table(
        "tournament_publication_states",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tournament", sa.String(length=64), nullable=False),
        sa.Column("market", sa.String(length=32), nullable=False),
        sa.Column("market_spec", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("run_id", sa.String(length=128), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tournament", "market", "market_spec", name="uq_publication_slice"),
    )
    op.create_index(
        "ix_publication_state_tournament",
        "tournament_publication_states",
        ["tournament", "status"],
    )


def downgrade() -> None:
    """Destructive downgrade запрещён; используйте forward-fix migration."""
    raise RuntimeError("Destructive downgrade запрещён; используйте forward-fix migration.")
