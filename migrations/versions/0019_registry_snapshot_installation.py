"""Добавить server installation projection и publication pointer.

Revision ID: 0019_registry_snapshot_installation
Revises: 0018_registry_canonical_event_mappings
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0019_registry_snapshot_installation"
down_revision = "0018_registry_canonical_event_mappings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Сохранить manifest/records и добавить атомарный publication pointer."""
    op.add_column("registry_identity_snapshots", sa.Column("manifest_json", sa.Text()))
    op.create_table(
        "registry_snapshot_records",
        sa.Column("snapshot_id", sa.String(length=68), nullable=False),
        sa.Column("file_name", sa.String(length=32), nullable=False),
        sa.Column("record_key", sa.String(length=256), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["snapshot_id"], ["registry_identity_snapshots.snapshot_id"]),
        sa.PrimaryKeyConstraint("snapshot_id", "file_name", "record_key"),
    )
    op.create_table(
        "registry_event_resolver_projections",
        sa.Column("snapshot_id", sa.String(length=68), nullable=False),
        sa.Column("event_snapshot_id", sa.String(length=68), nullable=False),
        sa.Column("projection_sha256", sa.String(length=64), nullable=False),
        sa.Column("projection_json", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["snapshot_id"], ["registry_identity_snapshots.snapshot_id"]),
        sa.PrimaryKeyConstraint("snapshot_id"),
    )
    op.create_table(
        "registry_publications",
        sa.Column("publication_sequence", sa.BigInteger(), nullable=False),
        sa.Column("publication_id", sa.String(length=128), nullable=False),
        sa.Column("snapshot_id", sa.String(length=68), nullable=False),
        sa.Column("previous_publication_id", sa.String(length=128), nullable=True),
        sa.Column("published_at", sa.DateTime(), nullable=False),
        sa.Column("actor", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["snapshot_id"], ["registry_identity_snapshots.snapshot_id"]),
        sa.PrimaryKeyConstraint("publication_sequence"),
        sa.UniqueConstraint("publication_id"),
    )
    op.create_table(
        "active_registry_installation",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("publication_sequence", sa.BigInteger(), nullable=False),
        sa.Column("publication_id", sa.String(length=128), nullable=False),
        sa.Column("snapshot_id", sa.String(length=68), nullable=False),
        sa.Column("activated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("id = 1"),
        sa.ForeignKeyConstraint(["snapshot_id"], ["registry_identity_snapshots.snapshot_id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "registry_installation_locks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("lock_version", sa.Integer(), nullable=False, server_default="0"),
        sa.CheckConstraint("id = 1"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.bulk_insert(
        sa.table(
            "registry_installation_locks",
            sa.column("id", sa.Integer()),
            sa.column("lock_version", sa.Integer()),
        ),
        [{"id": 1, "lock_version": 0}],
    )


def downgrade() -> None:
    """Не удалять установленные immutable snapshots; используйте forward-fix."""
    raise RuntimeError("Destructive downgrade запрещён; используйте forward-fix migration.")
