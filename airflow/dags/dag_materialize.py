"""DAG D — Prediction Materialization.

Загружает обученную модель (prod), выполняет inference
на предстоящих матчах и записывает предсказания в Prediction Store.

Этапы:
    1. Для каждого турнира: загрузка модели → batch inference → запись в БД

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
    "SF_MATERIALIZE_TOURNAMENTS",
    default_var="uel_kz_1,uel_kz_2,uel_cz,lp_ru,lp_eu,lp_eu_a18,lp_by",
)
MARKET = Variable.get("SF_MATERIALIZE_MARKET", default_var="winner")
MARKET_SPEC = Variable.get("SF_MATERIALIZE_SPEC", default_var="winner")
ALGORITHM = Variable.get("SF_MATERIALIZE_ALGORITHM", default_var="catboost")
FEATURES = Variable.get("SF_MATERIALIZE_FEATURES", default_var="basic")

# ── DAG ──────────────────────────────────────────────────────────
default_args = {
    "owner": "ml-team",
    "depends_on_past": False,
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
    "execution_timeout": timedelta(hours=1),
}

with DAG(
    dag_id="prediction_materialize",
    description="Batch inference: model → predictions → DB",
    schedule="15 */4 * * *",  # 15 мин после data_refresh
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=["inference", "predictions", "v2"],
    default_args=default_args,
    max_active_runs=1,
    doc_md=__doc__,
) as dag:
    tournament_list = [t.strip() for t in TOURNAMENTS.split(",")]

    prev_task = None
    for tournament in tournament_list:
        task = BashOperator(
            task_id=f"materialize_{tournament}",
            bash_command=(
                f"cd {PROJECT_DIR} && {UV_RUN} python -m sports_forecast.materialize "
                f"tournament={tournament} "
                f"market={MARKET} "
                f"market_spec={MARKET_SPEC} "
                f"algorithm={ALGORITHM} "
                f"features={FEATURES}"
            ),
            execution_timeout=timedelta(minutes=15),
        )

        if prev_task is not None:
            prev_task >> task
        prev_task = task
