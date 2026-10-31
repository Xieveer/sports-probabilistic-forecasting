"""Добавить отдельный тип сводки ставок в Data Cycle notification outbox.

Revision ID: 0026_bet_summary_notification
Revises: 0025_real_bets_ledger
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0026_bet_summary_notification"
down_revision = "0025_real_bets_ledger"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Сохранить terminal строки и разрешить независимую сводку ставок."""
    table = "data_cycle_notification_outbox"
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table(table, recreate="always") as batch:
            batch.add_column(
                sa.Column("kind", sa.String(16), nullable=False, server_default="terminal")
            )
            batch.add_column(sa.Column("payload_json", sa.Text(), nullable=True))
            batch.drop_constraint("uq_data_cycle_notification_run_alias", type_="unique")
            batch.create_unique_constraint(
                "uq_data_cycle_notification_run_alias_kind", ["run_id", "destination_alias", "kind"]
            )
            batch.create_check_constraint(
                "ck_data_cycle_notification_kind", "kind IN ('terminal','bet_summary')"
            )
        return
    op.add_column(
        table, sa.Column("kind", sa.String(16), nullable=False, server_default="terminal")
    )
    op.add_column(table, sa.Column("payload_json", sa.Text(), nullable=True))
    op.drop_constraint("uq_data_cycle_notification_run_alias", table, type_="unique")
    op.create_unique_constraint(
        "uq_data_cycle_notification_run_alias_kind",
        table,
        ["run_id", "destination_alias", "kind"],
    )
    op.create_check_constraint(
        "ck_data_cycle_notification_kind", table, "kind IN ('terminal','bet_summary')"
    )


def downgrade() -> None:
    """Откатить схему после удаления bet-summary строк отдельной процедурой."""
    table = "data_cycle_notification_outbox"
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table(table, recreate="always") as batch:
            batch.drop_constraint("ck_data_cycle_notification_kind", type_="check")
            batch.drop_constraint("uq_data_cycle_notification_run_alias_kind", type_="unique")
            batch.create_unique_constraint(
                "uq_data_cycle_notification_run_alias", ["run_id", "destination_alias"]
            )
            batch.drop_column("payload_json")
            batch.drop_column("kind")
        return
    op.drop_constraint("ck_data_cycle_notification_kind", table, type_="check")
    op.drop_constraint("uq_data_cycle_notification_run_alias_kind", table, type_="unique")
    op.create_unique_constraint(
        "uq_data_cycle_notification_run_alias", table, ["run_id", "destination_alias"]
    )
    op.drop_column(table, "payload_json")
    op.drop_column(table, "kind")
