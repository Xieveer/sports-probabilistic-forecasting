"""Reusable BashOperator factories for scheduled refresh → validate → digest (R41.3).

One **logical** pattern (heavy path): ``source → … → materialize`` via
:func:`sports_forecast.orchestration.refresh_command.build_refresh_per_tournament_command`,
then validation, then optional Telegram digest.

Multiple leagues are supported by adding a small ``dag_*.py`` that wires the same helpers
with different ``dag_id`` / schedule / Airflow Variables — avoid copying Jinja blocks.
"""

from __future__ import annotations

from datetime import timedelta

from airflow.models import DAG
from airflow.operators.bash import BashOperator

from sports_forecast.orchestration.airflow_post_refresh_digest_bash import (
    build_post_refresh_digest_bash_command,
)
from sports_forecast.orchestration.refresh_command import (
    build_refresh_per_tournament_command,
)


def bash_refresh_per_tournament(
    dag: DAG,
    *,
    task_id: str,
    project_dir: str,
    uv_run: str,
    tournaments_expr: str,
    features_config: str,
    market: str,
    market_spec: str,
    source_cmd: str,
    lock_file: str,
    lock_wait_seconds: int,
    refresh_pool: str,
    execution_timeout_hours: int = 6,
) -> BashOperator:
    """Heavy-path refresh task (one tournament or CSV list via ``tournaments_expr``)."""
    return BashOperator(
        dag=dag,
        task_id=task_id,
        bash_command=build_refresh_per_tournament_command(
            project_dir=project_dir,
            uv_run=uv_run,
            tournaments_expr=tournaments_expr,
            features_config=features_config,
            market=market,
            market_spec=market_spec,
            source_cmd=source_cmd,
            lock_file=lock_file,
            lock_wait_seconds=lock_wait_seconds,
        ),
        execution_timeout=timedelta(hours=execution_timeout_hours),
        pool=refresh_pool,
        pool_slots=1,
    )


def bash_run_validation(
    dag: DAG,
    *,
    task_id: str,
    project_dir: str,
    uv_run: str,
    refresh_pool: str,
) -> BashOperator:
    """Shared ``run_validation`` step after refresh (same pool/slot contract as other DAGs)."""
    return BashOperator(
        dag=dag,
        task_id=task_id,
        bash_command=f"cd {project_dir} && {uv_run} python -m sports_forecast.validation.run_validation",
        pool=refresh_pool,
        pool_slots=1,
    )


def bash_post_refresh_digest(
    dag: DAG,
    *,
    task_id: str,
    project_dir: str,
    uv_run: str,
    refresh_pool: str,
) -> BashOperator:
    """Telegram digest after validate; honors ``SF_TELEGRAM_DIGEST_ENABLE`` + override cmd."""
    return BashOperator(
        dag=dag,
        task_id=task_id,
        bash_command=build_post_refresh_digest_bash_command(
            project_dir=project_dir,
            uv_run=uv_run,
        ),
        pool=refresh_pool,
        pool_slots=1,
    )
