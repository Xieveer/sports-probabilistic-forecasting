"""Добавить durable outbox для обратной очереди registry candidates.

Revision ID: 0020_registry_candidate_feedback_outbox
Revises: 0019_registry_snapshot_installation
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0020_registry_candidate_feedback_outbox"
down_revision = "0019_registry_snapshot_installation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Создать таблицу для надёжной публикации и acknowledgement batch-ей."""
    op.create_table(
        "registry_candidate_outbox",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("installation_id", sa.String(length=36), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("batch_id", sa.String(length=64), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error_code", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending','staged','awaiting_ack','acknowledged')",
            name="ck_registry_candidate_outbox_status",
        ),
        sa.CheckConstraint("attempts >= 0", name="ck_registry_candidate_outbox_attempts"),
        sa.CheckConstraint(
            "(status = 'pending' AND batch_id IS NULL) OR "
            "(status <> 'pending' AND batch_id IS NOT NULL)",
            name="ck_registry_candidate_outbox_batch_status",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_registry_candidate_outbox_delivery",
        "registry_candidate_outbox",
        ["installation_id", "status", "id"],
    )
    op.create_index(
        "ix_registry_candidate_outbox_batch",
        "registry_candidate_outbox",
        ["installation_id", "batch_id"],
    )
    op.create_table(
        "registry_candidate_batch_sequences",
        sa.Column("installation_id", sa.String(length=36), nullable=False),
        sa.Column("last_sequence", sa.BigInteger(), server_default="0", nullable=False),
        sa.CheckConstraint("last_sequence >= 0", name="ck_registry_candidate_batch_sequence"),
        sa.PrimaryKeyConstraint("installation_id"),
    )


def downgrade() -> None:
    """Не удалять candidate evidence автоматически; используйте forward-fix."""
    raise RuntimeError("Destructive downgrade запрещён; используйте forward-fix migration.")
