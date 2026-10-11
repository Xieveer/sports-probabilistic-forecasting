"""Добавить закрытый журнал фактических ставок и неизменяемый контекст карточки.

Revision ID: 0025_real_bets_ledger
Revises: 0024_prediction_source_namespace
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0025_real_bets_ledger"
down_revision = "0024_prediction_source_namespace"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Создать additive таблицы журнала без изменения публичной витрины."""
    op.create_table(
        "bet_card_contexts",
        sa.Column("context_id", sa.String(36), primary_key=True),
        sa.Column("owner_user_id", sa.String(32), nullable=False),
        sa.Column("tournament", sa.String(64), nullable=False),
        sa.Column("source_namespace", sa.String(128)),
        sa.Column("source_event_id", sa.String(128), nullable=False),
        sa.Column("market", sa.String(32), nullable=False),
        sa.Column("market_spec", sa.String(64), nullable=False),
        sa.Column(
            "prediction_revision_id",
            sa.String(36),
            sa.ForeignKey("prediction_revisions.revision_id", ondelete="RESTRICT"),
        ),
        sa.Column("quote_observation_id", sa.BigInteger()),
        sa.Column("snapshot_json", sa.Text(), nullable=False),
        sa.Column("captured_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_bet_card_contexts_owner_user_id", "bet_card_contexts", ["owner_user_id"])
    op.create_table(
        "real_bets",
        sa.Column("bet_id", sa.String(36), primary_key=True),
        sa.Column("owner_user_id", sa.String(32), nullable=False),
        sa.Column("create_request_id", sa.String(128), nullable=False, unique=True),
        sa.Column("create_request_hash", sa.String(64), nullable=False),
        sa.Column(
            "context_id",
            sa.String(36),
            sa.ForeignKey("bet_card_contexts.context_id", ondelete="RESTRICT"),
        ),
        sa.Column("tournament", sa.String(64), nullable=False),
        sa.Column("source_namespace", sa.String(128)),
        sa.Column("source_event_id", sa.String(128), nullable=False),
        sa.Column("market_spec", sa.String(64), nullable=False),
        sa.Column("outcome", sa.String(64), nullable=False),
        sa.Column("bookmaker", sa.String(32), nullable=False),
        sa.Column("funding", sa.String(16), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("stake", sa.Numeric(14, 2), nullable=False),
        sa.Column("decimal_odds", sa.Numeric(10, 4), nullable=False),
        sa.Column("placed_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("result", sa.String(16)),
        sa.Column("payout", sa.Numeric(14, 2)),
        sa.Column("settled_at", sa.DateTime()),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("stake > 0", name="ck_real_bet_stake_positive"),
        sa.CheckConstraint("decimal_odds > 1", name="ck_real_bet_odds_positive"),
        sa.CheckConstraint("currency = 'RUB'", name="ck_real_bet_rub"),
        sa.CheckConstraint("funding IN ('cash', 'freebet')", name="ck_real_bet_funding"),
        sa.CheckConstraint("status IN ('open', 'settled', 'cancelled')", name="ck_real_bet_status"),
        sa.CheckConstraint(
            "result IS NULL OR result IN ('win', 'loss', 'void')", name="ck_real_bet_result"
        ),
    )
    op.create_index("ix_real_bets_owner_user_id", "real_bets", ["owner_user_id"])
    op.create_index("ix_real_bets_owner_settled", "real_bets", ["owner_user_id", "settled_at"])
    op.create_table(
        "real_bet_audit",
        sa.Column("audit_id", sa.String(36), primary_key=True),
        sa.Column(
            "bet_id",
            sa.String(36),
            sa.ForeignKey("real_bets.bet_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("owner_user_id", sa.String(32), nullable=False),
        sa.Column("request_id", sa.String(128), nullable=False, unique=True),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("operation", sa.String(16), nullable=False),
        sa.Column("before_json", sa.Text()),
        sa.Column("after_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_real_bet_audit_bet", "real_bet_audit", ["bet_id", "created_at"])


def downgrade() -> None:
    """Не удалять денежную историю; использовать forward-fix migration."""
    raise RuntimeError("Destructive downgrade запрещён; используйте forward-fix migration.")
