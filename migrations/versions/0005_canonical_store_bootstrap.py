"""Добавить canonical event store и audit initial bootstrap.

Revision ID: 0005_canonical_store_bootstrap
Revises: 0004_worker_execution_state
Create Date: 2026-08-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0005_canonical_store_bootstrap"
down_revision = "0004_worker_execution_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Создать additive canonical store без изменения prediction-витрины."""
    op.create_table(
        "canonical_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("sport", sa.String(length=64), nullable=False),
        sa.Column("tournament", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=128), nullable=False),
        sa.Column("source_event_id", sa.String(length=128), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("current_revision_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "first_ingested_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "last_ingested_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tournament", "source", "source_event_id", name="uq_canonical_event_source"
        ),
    )
    op.create_index("ix_canonical_events_sport", "canonical_events", ["sport"])
    op.create_index("ix_canonical_events_tournament", "canonical_events", ["tournament"])
    op.create_index("ix_canonical_events_scheduled_at", "canonical_events", ["scheduled_at"])
    op.create_index(
        "ix_canonical_event_tournament_schedule",
        "canonical_events",
        ["tournament", "scheduled_at"],
    )
    op.create_table(
        "canonical_event_revisions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("canonical_event_id", sa.Integer(), nullable=False),
        sa.Column("revision_sha256", sa.String(length=64), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=False),
        sa.Column("source_observed_at", sa.DateTime(), nullable=False),
        sa.Column(
            "ingested_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["canonical_event_id"], ["canonical_events.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "canonical_event_id", "revision_sha256", name="uq_canonical_event_revision"
        ),
    )
    op.create_index(
        "ix_canonical_event_revisions_canonical_event_id",
        "canonical_event_revisions",
        ["canonical_event_id"],
    )
    op.create_table(
        "refresh_watermarks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tournament", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=128), nullable=False),
        sa.Column("snapshot_id", sa.String(length=80), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tournament"),
    )
    op.create_table(
        "bootstrap_imports",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("artifact_id", sa.String(length=80), nullable=False),
        sa.Column("tournament", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("events_count", sa.Integer(), nullable=False),
        sa.Column(
            "imported_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("artifact_id"),
    )
    op.create_index("ix_bootstrap_imports_tournament", "bootstrap_imports", ["tournament"])


def downgrade() -> None:
    """Destructive downgrade запрещён: используйте forward-fix migration."""
    raise RuntimeError("Destructive downgrade запрещён; используйте forward-fix migration.")
