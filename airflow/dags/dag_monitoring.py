"""DAG E — Model Monitoring & Retraining Triggers.

Отслеживает качество модели на новых данных:
    1. Проверка свежести данных (data freshness)
    2. Проверка распределения предсказаний (prediction drift)
    3. Триггер переобучения при деградации метрик

Все задачи запускаются через CLI (BashOperator).
Никакой ML-логики внутри Airflow.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from airflow.models import Variable
from airflow.operators.bash import BashOperator
from airflow.operators.python import BranchPythonOperator

from airflow import DAG


# ── Конфигурация ─────────────────────────────────────────────────
PROJECT_DIR = Variable.get("SF_PROJECT_DIR", default_var="/app")
UV_RUN = Variable.get("SF_UV_RUN", default_var="uv run")

# Порог деградации: если accuracy падает ниже, запускаем переобучение
MIN_ACCURACY = float(Variable.get("SF_MIN_ACCURACY", default_var="0.50"))
MAX_ECE = float(Variable.get("SF_MAX_ECE", default_var="0.10"))
DATA_FRESHNESS_HOURS = int(Variable.get("SF_DATA_FRESHNESS_HOURS", default_var="12"))


def _decide_retrain(**context):  # type: ignore[no-untyped-def]
    """Решить, нужно ли запускать переобучение.

    Проверяет XCom от задачи check_model_quality.
    Если деградация обнаружена → 'trigger_retrain', иначе → 'skip_retrain'.
    """
    ti = context["ti"]
    quality_ok = ti.xcom_pull(task_ids="check_model_quality", key="quality_ok")

    if quality_ok == "false":
        return "trigger_retrain"
    return "skip_retrain"


# ── DAG ──────────────────────────────────────────────────────────
default_args = {
    "owner": "ml-team",
    "depends_on_past": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
    "execution_timeout": timedelta(minutes=30),
}

with DAG(
    dag_id="model_monitoring",
    description="Monitor model quality & trigger retraining",
    schedule="0 8 * * *",  # ежедневно в 8:00
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=["monitoring", "quality", "v2"],
    default_args=default_args,
    max_active_runs=1,
    doc_md=__doc__,
) as dag:
    # ── Step 1: Проверка свежести данных ──────────────────────────
    check_data_freshness = BashOperator(
        task_id="check_data_freshness",
        bash_command=(
            f'cd {PROJECT_DIR} && {UV_RUN} python -c "'
            "from sports_forecast.validation.gates import check_data_freshness; "
            f"check_data_freshness(max_hours={DATA_FRESHNESS_HOURS})"
            '"'
        ),
    )

    # ── Step 2: Проверка качества модели ──────────────────────────
    check_model_quality = BashOperator(
        task_id="check_model_quality",
        bash_command=(
            f'cd {PROJECT_DIR} && {UV_RUN} python -c "'
            "from sports_forecast.validation.gates import check_model_quality; "
            f"check_model_quality(min_accuracy={MIN_ACCURACY}, max_ece={MAX_ECE})"
            '"'
        ),
    )

    # ── Step 3: Решение о переобучении ────────────────────────────
    decide = BranchPythonOperator(
        task_id="decide_retrain",
        python_callable=_decide_retrain,
    )

    # ── Step 4a: Триггер переобучения ─────────────────────────────
    trigger_retrain = BashOperator(
        task_id="trigger_retrain",
        bash_command=(
            'echo "⚠️  Деградация модели обнаружена. Запустите DAG training_sweep для переобучения."'
        ),
    )

    # ── Step 4b: Пропуск ──────────────────────────────────────────
    skip_retrain = BashOperator(
        task_id="skip_retrain",
        bash_command='echo "✅ Качество модели в норме. Переобучение не требуется."',
    )

    # ── Dependencies ──────────────────────────────────────────────
    check_data_freshness >> check_model_quality >> decide
    decide >> [trigger_retrain, skip_retrain]
