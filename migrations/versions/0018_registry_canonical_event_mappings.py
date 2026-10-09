"""Добавить версионный bridge project/canonical event identities.

Revision ID: 0018_registry_canonical_event_mappings
Revises: 0017_data_cycle_notification_outbox
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0018_registry_canonical_event_mappings"
down_revision = "0017_data_cycle_notification_outbox"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Создать immutable-by-contract bridge с unresolved rows."""
    op.create_table(
        "registry_identity_snapshots",
        sa.Column("snapshot_id", sa.String(length=68), nullable=False),
        sa.Column("snapshot_kind", sa.String(length=32), nullable=False),
        sa.Column("projection_sha256", sa.String(length=64), nullable=False),
        sa.Column("projection_schema_version", sa.Integer(), nullable=False),
        sa.Column("policy_version", sa.String(length=64), nullable=False),
        sa.Column("normalization_version", sa.String(length=64), nullable=False),
        sa.Column("projection_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("snapshot_id"),
    )
    op.create_table(
        "registry_canonical_event_mappings",
        sa.Column("snapshot_id", sa.String(length=80), nullable=False),
        sa.Column("canonical_event_id", sa.Integer(), nullable=False),
        sa.Column("project_event_id", sa.String(length=36), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("policy_version", sa.String(length=64), nullable=False),
        sa.Column("decision_id", sa.String(length=36), nullable=True),
        sa.CheckConstraint("status IN ('resolved','unresolved','ambiguous','conflict')"),
        sa.CheckConstraint(
            "(status = 'resolved' AND project_event_id IS NOT NULL) OR "
            "(status <> 'resolved' AND project_event_id IS NULL)"
        ),
        sa.ForeignKeyConstraint(["canonical_event_id"], ["canonical_events.id"]),
        sa.ForeignKeyConstraint(["snapshot_id"], ["registry_identity_snapshots.snapshot_id"]),
        sa.PrimaryKeyConstraint("snapshot_id", "canonical_event_id"),
    )
    op.create_index(
        "ix_registry_event_mapping_canonical",
        "registry_canonical_event_mappings",
        ["canonical_event_id", "snapshot_id"],
    )


def downgrade() -> None:
    """Не удалять уже использованный event bridge; используйте forward-fix."""
    raise RuntimeError("Destructive downgrade запрещён; используйте forward-fix migration.")
