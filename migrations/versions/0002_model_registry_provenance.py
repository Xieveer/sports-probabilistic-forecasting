"""Добавить registry моделей и provenance витрины.

Revision ID: 0002_model_registry_provenance
Revises: 0001_prediction_store_baseline
Create Date: 2026-08-09
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0002_model_registry_provenance"
down_revision = "0001_prediction_store_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Добавить provenance без изменения существующих prediction rows."""
    op.add_column("predictions", sa.Column("model_pool", sa.String(length=128), nullable=True))
    op.add_column(
        "predictions", sa.Column("immutable_model_version", sa.String(length=192), nullable=True)
    )
    op.create_index("ix_predictions_model_pool", "predictions", ["model_pool"])
    op.create_index(
        "ix_predictions_immutable_model_version", "predictions", ["immutable_model_version"]
    )
    op.create_table(
        "model_deployments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("model_pool", sa.String(length=128), nullable=False),
        sa.Column("market_spec", sa.String(length=64), nullable=False),
        sa.Column("model_identity", sa.String(length=192), nullable=False),
        sa.Column("candidate_report_ref", sa.String(length=512), nullable=False),
        sa.Column("artifact_ref", sa.String(length=512), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column(
            "promoted_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("model_identity"),
    )
    op.create_index("ix_model_deployments_model_pool", "model_deployments", ["model_pool"])
    op.create_index(
        "ix_model_deployment_pool_spec_active",
        "model_deployments",
        ["model_pool", "market_spec", "is_active"],
    )


def downgrade() -> None:
    """Destructive downgrade запрещён: используйте rollback pointer или forward-fix."""
    raise RuntimeError(
        "Destructive downgrade запрещён; используйте rollback pointer или forward-fix migration."
    )
