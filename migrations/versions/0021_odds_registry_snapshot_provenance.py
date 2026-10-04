"""Закрепить registry snapshot для разрешённых odds observations.

Revision ID: 0021_odds_registry_snapshot_provenance
Revises: 0020_registry_candidate_feedback_outbox
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0021_odds_registry_snapshot_provenance"
down_revision = "0020_registry_candidate_feedback_outbox"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Добавить nullable provenance для legacy и strict registry odds."""
    with op.batch_alter_table("odds_observations") as batch_op:
        batch_op.add_column(sa.Column("registry_snapshot_id", sa.String(length=80), nullable=True))
        batch_op.create_foreign_key(
            "fk_odds_observation_registry_snapshot",
            "registry_identity_snapshots",
            ["registry_snapshot_id"],
            ["snapshot_id"],
        )
    op.create_index(
        "ix_odds_observation_registry_snapshot",
        "odds_observations",
        ["canonical_event_id", "registry_snapshot_id"],
    )


def downgrade() -> None:
    """Не удалять provenance; используйте forward-fix."""
    raise RuntimeError("Destructive downgrade запрещён; используйте forward-fix migration.")
