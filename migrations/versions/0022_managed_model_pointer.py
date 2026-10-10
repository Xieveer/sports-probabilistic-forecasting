"""Добавить bundle binding для managed model deployment.

Revision ID: 0022_managed_model_pointer
Revises: 0021_odds_registry_snapshot_provenance
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0022_managed_model_pointer"
down_revision = "0021_odds_registry_snapshot_provenance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Добавить nullable binding, сохранив старые deployment как legacy."""
    with op.batch_alter_table("model_deployments") as batch_op:
        batch_op.add_column(sa.Column("bundle_id", sa.String(length=80), nullable=True))
        batch_op.add_column(
            sa.Column("managed_artifact_location", sa.String(length=512), nullable=True)
        )
        batch_op.add_column(
            sa.Column("is_managed", sa.Boolean(), server_default=sa.text("false"), nullable=False)
        )
        batch_op.create_check_constraint(
            "ck_model_deployment_managed_bundle_bound",
            "is_managed = false OR (bundle_id IS NOT NULL AND managed_artifact_location IS NOT NULL)",
        )
    op.create_index(
        "uq_model_deployment_active_pair",
        "model_deployments",
        ["model_pool", "market_spec"],
        unique=True,
        postgresql_where=sa.text("is_active"),
        sqlite_where=sa.text("is_active = 1"),
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            """
            CREATE FUNCTION prevent_managed_deployment_rebind() RETURNS trigger AS $$
            BEGIN
                IF OLD.is_managed AND (
                    NEW.is_managed IS DISTINCT FROM OLD.is_managed OR
                    NEW.model_pool IS DISTINCT FROM OLD.model_pool OR
                    NEW.market_spec IS DISTINCT FROM OLD.market_spec OR
                    NEW.model_identity IS DISTINCT FROM OLD.model_identity OR
                    NEW.bundle_id IS DISTINCT FROM OLD.bundle_id OR
                    NEW.managed_artifact_location IS DISTINCT FROM OLD.managed_artifact_location
                ) THEN
                    RAISE EXCEPTION 'managed model deployment identity and bundle are immutable';
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_managed_deployment_immutable
            BEFORE UPDATE ON model_deployments
            FOR EACH ROW EXECUTE FUNCTION prevent_managed_deployment_rebind()
            """
        )
    elif op.get_bind().dialect.name == "sqlite":
        op.execute(
            """
            CREATE TRIGGER trg_managed_deployment_immutable
            BEFORE UPDATE ON model_deployments
            WHEN OLD.is_managed = 1 AND (
                NEW.is_managed != OLD.is_managed OR
                NEW.model_pool != OLD.model_pool OR
                NEW.market_spec != OLD.market_spec OR
                NEW.model_identity != OLD.model_identity OR
                NEW.bundle_id IS NOT OLD.bundle_id OR
                NEW.managed_artifact_location IS NOT OLD.managed_artifact_location
            )
            BEGIN
                SELECT RAISE(ABORT, 'managed model deployment identity and bundle are immutable');
            END
            """
        )


def downgrade() -> None:
    """Destructive downgrade запрещён; исправлять схему forward migration."""
    raise RuntimeError("Destructive downgrade запрещён; используйте forward-fix migration.")
