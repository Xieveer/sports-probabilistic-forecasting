"""Создать baseline schema Prediction Store.

Revision ID: 0001_prediction_store_baseline
Revises:
Create Date: 2026-08-09
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0001_prediction_store_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Создать schema, совместимую с текущим read-only API."""
    op.create_table(
        "predictions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("match_id", sa.String(length=64), nullable=False),
        sa.Column("tournament", sa.String(length=64), nullable=False),
        sa.Column("market", sa.String(length=32), nullable=False),
        sa.Column("market_spec", sa.String(length=32), nullable=False),
        sa.Column("home_player", sa.String(length=128), nullable=True),
        sa.Column("away_player", sa.String(length=128), nullable=True),
        sa.Column("match_datetime", sa.DateTime(), nullable=True),
        sa.Column("model_version", sa.String(length=128), nullable=False),
        sa.Column("algorithm", sa.String(length=32), nullable=False),
        sa.Column("featureset", sa.String(length=32), nullable=False),
        sa.Column("model_tag", sa.String(length=16), nullable=False),
        sa.Column("predictions_json", sa.Text(), nullable=False),
        sa.Column("proba_home", sa.Float(), nullable=True),
        sa.Column("proba_away", sa.Float(), nullable=True),
        sa.Column("odds_raw", sa.Text(), nullable=True),
        sa.Column(
            "prediction_ts",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_predictions_match_id", "predictions", ["match_id"])
    op.create_index("ix_predictions_tournament", "predictions", ["tournament"])
    op.create_index("ix_pred_match_market", "predictions", ["match_id", "market", "market_spec"])
    op.create_index("ix_pred_tournament_status", "predictions", ["tournament", "status"])
    op.create_index("ix_pred_prediction_ts", "predictions", ["prediction_ts"])

    op.create_table(
        "notification_line_states",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("profile_id", sa.String(length=128), nullable=False),
        sa.Column("match_id", sa.String(length=64), nullable=False),
        sa.Column("line_json", sa.Text(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_notification_line_profile_match",
        "notification_line_states",
        ["profile_id", "match_id"],
        unique=True,
    )

    op.create_table(
        "notification_cycles",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("profile_id", sa.String(length=128), nullable=False),
        sa.Column("logical_cycle", sa.String(length=128), nullable=False),
        sa.Column("changes_json", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_notification_cycle_profile_cycle",
        "notification_cycles",
        ["profile_id", "logical_cycle"],
        unique=True,
    )

    op.create_table(
        "notification_deliveries",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("cycle_id", sa.Integer(), nullable=False),
        sa.Column("chat_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_notification_deliveries_cycle_id", "notification_deliveries", ["cycle_id"])
    op.create_index(
        "uq_notification_delivery_cycle_chat",
        "notification_deliveries",
        ["cycle_id", "chat_id"],
        unique=True,
    )


def downgrade() -> None:
    """Откат baseline намеренно запрещён: восстановите backup или forward-fix."""
    raise RuntimeError(
        "Destructive downgrade запрещён; используйте backup или forward-fix migration."
    )
