"""DAG A — Data Refresh per tournament.

Оркестрирует по-турнирный контур обновления:
    1. source
    2. ingest
    3. clean
    4. features
    5. materialize

Для каждого турнира стадии обязательны и выполняются последовательно.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from airflow.models import Variable
from airflow.operators.bash import BashOperator

from airflow import DAG
from sports_forecast.orchestration.refresh_command import (
    build_refresh_per_tournament_command,
)


# ── Конфигурация ─────────────────────────────────────────────────
PROJECT_DIR = Variable.get("SF_PROJECT_DIR", default_var="/app")
UV_RUN = Variable.get("SF_UV_RUN", default_var="uv run")

TOURNAMENTS = Variable.get(
    "SF_REFRESH_TOURNAMENTS",
    default_var="uel_kz_1,uel_kz_2,uel_cz,lp_ru,lp_eu,lp_eu_a18,lp_by",
)
FEATURES_CONFIG = Variable.get("SF_FEATURES_CONFIG", default_var="basic")
MARKET = Variable.get("SF_MATERIALIZE_MARKET", default_var="winner")
MARKET_SPEC = Variable.get("SF_MATERIALIZE_SPEC", default_var="winner")
SOURCE_REFRESH_CMD = Variable.get(
    "SF_SOURCE_REFRESH_CMD",
    default_var='test -f "data/source/{tournament}/source.csv"',
)
REFRESH_POOL = Variable.get("SF_REFRESH_POOL", default_var="sf_refresh_pool")
LOCK_FILE = Variable.get(
    "SF_REFRESH_LOCK_FILE",
    default_var="/tmp/sf_refresh_pipeline.lock",
)
LOCK_WAIT_SECONDS = int(Variable.get("SF_REFRESH_LOCK_WAIT_SECONDS", default_var="300"))
MAX_ACTIVE_RUNS = int(Variable.get("SF_REFRESH_MAX_ACTIVE_RUNS", default_var="1"))
MAX_ACTIVE_TASKS = int(Variable.get("SF_REFRESH_MAX_ACTIVE_TASKS", default_var="1"))

# ── DAG ──────────────────────────────────────────────────────────
default_args = {
    "owner": "ml-team",
    "depends_on_past": False,
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
    "execution_timeout": timedelta(hours=2),
}

with DAG(
    dag_id="data_refresh",
    description="Data pipeline: source → raw → interim → processed",
    schedule="0 */4 * * *",  # каждые 4 часа
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=["data", "pipeline", "v2"],
    default_args=default_args,
    max_active_runs=MAX_ACTIVE_RUNS,
    max_active_tasks=MAX_ACTIVE_TASKS,
    doc_md=__doc__,
    params={
        "tournaments": TOURNAMENTS,
        "features": FEATURES_CONFIG,
        "market": MARKET,
        "market_spec": MARKET_SPEC,
    },
) as dag:
    refresh_per_tournament = BashOperator(
        task_id="refresh_per_tournament",
        bash_command=build_refresh_per_tournament_command(
            project_dir=PROJECT_DIR,
            uv_run=UV_RUN,
            tournaments_expr='{{ dag_run.conf.get("tournaments", params.tournaments) }}',
            features_config='{{ dag_run.conf.get("features", params.features) }}',
            market='{{ dag_run.conf.get("market", params.market) }}',
            market_spec='{{ dag_run.conf.get("market_spec", params.market_spec) }}',
            source_cmd=SOURCE_REFRESH_CMD,
            lock_file=LOCK_FILE,
            lock_wait_seconds=LOCK_WAIT_SECONDS,
        ),
        execution_timeout=timedelta(hours=2),
        pool=REFRESH_POOL,
        pool_slots=1,
    )

    validate = BashOperator(
        task_id="validate",
        bash_command=f"cd {PROJECT_DIR} && {UV_RUN} python -m sports_forecast.validation.run_validation",
        pool=REFRESH_POOL,
        pool_slots=1,
    )

    refresh_per_tournament >> validate
