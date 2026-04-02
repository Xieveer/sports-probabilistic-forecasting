"""DAG B/C — Training Sweep + Validation & Promotion.

Запускает обучение моделей по указанным турнирам и алгоритмам,
после чего выбирает лучшую модель для продакшена.

Этапы:
    1. Training sweep (Hydra --multirun): перебор алгоритмов × наборов фичей
    2. Model promotion: выбор лучшего run по метрике → копирование артефактов

Все задачи запускаются через CLI (BashOperator).
Никакой ML-логики внутри Airflow.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from airflow.models import Variable
from airflow.operators.bash import BashOperator

from airflow import DAG
from sports_forecast.deploy.promote_command import (
    build_promote_per_tournament_command,
)


# ── Конфигурация ─────────────────────────────────────────────────
PROJECT_DIR = Variable.get("SF_PROJECT_DIR", default_var="/app")
UV_RUN = Variable.get("SF_UV_RUN", default_var="uv run")

TOURNAMENTS = Variable.get("SF_TRAIN_TOURNAMENTS", default_var="uel_kz_1")
ALGORITHMS = Variable.get("SF_TRAIN_ALGORITHMS", default_var="catboost,lgbm,logreg")
FEATURES = Variable.get("SF_TRAIN_FEATURES", default_var="basic")
MARKET = Variable.get("SF_TRAIN_MARKET", default_var="winner")
MARKET_SPEC = Variable.get("SF_TRAIN_MARKET_SPEC", default_var="winner")
PROMOTE_METRIC = Variable.get("SF_PROMOTE_METRIC", default_var="test_logloss")
PROMOTE_DIRECTION = Variable.get("SF_PROMOTE_DIRECTION", default_var="minimize")

# ── DAG ──────────────────────────────────────────────────────────
default_args = {
    "owner": "ml-team",
    "depends_on_past": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=10),
    "execution_timeout": timedelta(hours=6),
}

with DAG(
    dag_id="training_sweep",
    description="Training pipeline: sweep models → promote best",
    schedule=None,  # Только ручной запуск или триггер
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=["training", "mlflow", "v2"],
    default_args=default_args,
    max_active_runs=1,
    doc_md=__doc__,
    params={
        "tournaments": TOURNAMENTS,
        "algorithms": ALGORITHMS,
        "features": FEATURES,
        "market": MARKET,
        "market_spec": MARKET_SPEC,
    },
) as dag:
    # ── Step 1: Training sweep ────────────────────────────────────
    train_sweep = BashOperator(
        task_id="train_sweep",
        bash_command=(
            f"cd {PROJECT_DIR} && {UV_RUN} python -m sports_forecast.train --multirun "
            "tournament={{ params.tournaments }} "
            "market={{ params.market }} "
            "market_spec={{ params.market_spec }} "
            "algorithm={{ params.algorithms }} "
            "features={{ params.features }}"
        ),
    )

    # ── Step 2: Promote best model ────────────────────────────────
    # Для каждого турнира запускаем promoter
    promote = BashOperator(
        task_id="promote_best",
        bash_command=build_promote_per_tournament_command(
            project_dir=PROJECT_DIR,
            uv_run=UV_RUN,
            tournaments_expr="{{ params.tournaments }}",
            market_spec_expr="{{ params.market_spec }}",
            metric=PROMOTE_METRIC,
            direction=PROMOTE_DIRECTION,
            top_n=5,
        ),
    )

    # ── Dependencies ──────────────────────────────────────────────
    train_sweep >> promote
