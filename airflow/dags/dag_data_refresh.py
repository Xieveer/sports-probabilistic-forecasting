"""DAG A — Data Refresh: source → raw → interim → processed → validate.

Оркестрирует полный цикл обновления данных:
    1. Ingest:   source CSV → raw parquet
    2. Clean:    raw → interim (типизация, валидация)
    3. Features: interim → processed (генерация фичей)
    4. Validate: проверка quality gates для raw/interim/processed

Все задачи запускаются через CLI (BashOperator).
Никакой ML-логики внутри Airflow.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from airflow.models import Variable
from airflow.operators.bash import BashOperator

from airflow import DAG


# ── Конфигурация ─────────────────────────────────────────────────
PROJECT_DIR = Variable.get("SF_PROJECT_DIR", default_var="/app")
UV_RUN = Variable.get("SF_UV_RUN", default_var="uv run")

TOURNAMENTS = Variable.get(
    "SF_TOURNAMENTS",
    default_var="uel_kz_1,uel_kz_2,uel_cz,lp_ru,lp_eu,lp_eu_a18,lp_by",
)
FEATURES_CONFIG = Variable.get("SF_FEATURES_CONFIG", default_var="basic")

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
    max_active_runs=1,
    doc_md=__doc__,
) as dag:
    # ── Step 1: Ingest ────────────────────────────────────────────
    ingest = BashOperator(
        task_id="ingest",
        bash_command=f"cd {PROJECT_DIR} && {UV_RUN} python -m sports_forecast.data.ingest",
    )

    # ── Step 2: Clean ─────────────────────────────────────────────
    clean = BashOperator(
        task_id="clean",
        bash_command=f"cd {PROJECT_DIR} && {UV_RUN} python -m sports_forecast.data.clean",
    )

    # ── Step 3: Features (Hydra multirun по всем турнирам) ────────
    features = BashOperator(
        task_id="features",
        bash_command=(
            f"cd {PROJECT_DIR} && {UV_RUN} python -m sports_forecast.features.features_build "
            f"--multirun tournament={TOURNAMENTS} features={FEATURES_CONFIG}"
        ),
        execution_timeout=timedelta(hours=1),
    )

    # ── Step 4: Validate ──────────────────────────────────────────
    validate = BashOperator(
        task_id="validate",
        bash_command=f"cd {PROJECT_DIR} && {UV_RUN} python -m sports_forecast.validation.run_validation",
    )

    # ── Dependencies ──────────────────────────────────────────────
    ingest >> clean >> features >> validate
