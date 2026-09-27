"""Ограничить право Control API отмечать просроченный executor stalled.

Revision ID: 0016_control_stall_monotonic
Revises: 0015_data_cycle_executor_fencing
"""

from __future__ import annotations

from alembic import op


revision = "0016_control_stall_monotonic"
down_revision = "0015_data_cycle_executor_fencing"
branch_labels = None
depends_on = None


_STALL_FUNCTION = """
CREATE OR REPLACE FUNCTION public.mark_data_cycle_executor_stalled(
    p_run_id text
) RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    updated_rows integer;
    checked_at timestamp without time zone := statement_timestamp() AT TIME ZONE 'UTC';
BEGIN
    UPDATE public.data_cycle_runs
       SET executor_stalled_at = checked_at
     WHERE run_id = p_run_id
       AND status = 'running'
       AND executor_owner_id IS NOT NULL
       AND heartbeat_at IS NOT NULL
       AND heartbeat_at <= checked_at - INTERVAL '95 minutes'
       AND executor_stalled_at IS NULL;
    GET DIAGNOSTICS updated_rows = ROW_COUNT;
    RETURN updated_rows = 1;
END;
$$
"""


def upgrade() -> None:
    """Создать узкую монотонную операцию; Control API не получает UPDATE права."""
    if op.get_bind().dialect.name == "postgresql":
        op.execute(_STALL_FUNCTION)
        op.execute(
            "REVOKE ALL ON FUNCTION public.mark_data_cycle_executor_stalled(text) FROM PUBLIC"
        )


def downgrade() -> None:
    """Удалить функцию после возврата к совместимой runtime роли."""
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP FUNCTION IF EXISTS public.mark_data_cycle_executor_stalled(text)")
