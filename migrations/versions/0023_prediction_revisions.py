"""Добавить историю managed-публикаций прогнозов.

Revision ID: 0023_prediction_revisions
Revises: 0022_managed_model_pointer
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0023_prediction_revisions"
down_revision = "0022_managed_model_pointer"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Создать append-only revisions и nullable указатель текущей витрины."""
    op.create_table(
        "prediction_revisions",
        sa.Column("revision_id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=128), nullable=False),
        sa.Column("tournament", sa.String(length=64), nullable=False),
        sa.Column("source_namespace", sa.String(length=128), nullable=False),
        sa.Column("source_event_id", sa.String(length=128), nullable=False),
        sa.Column("canonical_event_id", sa.BigInteger(), nullable=True),
        sa.Column("market", sa.String(length=32), nullable=False),
        sa.Column("market_spec", sa.String(length=64), nullable=False),
        sa.Column("outcomes_json", sa.Text(), nullable=False),
        sa.Column("probabilities_json", sa.Text(), nullable=False),
        sa.Column("model_pool", sa.String(length=128), nullable=False),
        sa.Column("bundle_id", sa.String(length=80), nullable=False),
        sa.Column("model_identity", sa.String(length=192), nullable=False),
        sa.Column("feature_contract_id", sa.String(length=128), nullable=False),
        sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("input_snapshot_ref", sa.String(length=256), nullable=True),
        sa.Column("payload_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
        sa.PrimaryKeyConstraint("revision_id"),
        sa.UniqueConstraint(
            "run_id",
            "tournament",
            "source_namespace",
            "source_event_id",
            "market",
            "market_spec",
            name="uq_prediction_revision_idempotency",
        ),
    )
    op.create_index(
        "ix_prediction_revision_event",
        "prediction_revisions",
        ["tournament", "source_namespace", "source_event_id"],
    )
    with op.batch_alter_table("predictions") as batch_op:
        batch_op.add_column(sa.Column("current_revision_id", sa.String(length=36), nullable=True))
        batch_op.create_foreign_key(
            "fk_predictions_current_revision_id_prediction_revisions",
            "prediction_revisions",
            ["current_revision_id"],
            ["revision_id"],
            ondelete="RESTRICT",
        )

    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            """CREATE FUNCTION reject_prediction_revision_mutation() RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'prediction revisions are append-only';
            END;
            $$ LANGUAGE plpgsql"""
        )
        op.execute(
            """CREATE TRIGGER trg_prediction_revisions_immutable
            BEFORE UPDATE OR DELETE ON prediction_revisions
            FOR EACH ROW EXECUTE FUNCTION reject_prediction_revision_mutation()"""
        )
    elif op.get_bind().dialect.name == "sqlite":
        op.execute(
            """CREATE TRIGGER trg_prediction_revisions_no_update
            BEFORE UPDATE ON prediction_revisions
            BEGIN SELECT RAISE(ABORT, 'prediction revisions are append-only'); END"""
        )
        op.execute(
            """CREATE TRIGGER trg_prediction_revisions_no_delete
            BEFORE DELETE ON prediction_revisions
            BEGIN SELECT RAISE(ABORT, 'prediction revisions are append-only'); END"""
        )


def downgrade() -> None:
    """Удаление истории запрещено; исправляйте схему новой revision."""
    raise RuntimeError("Destructive downgrade запрещён; используйте forward-fix migration.")
