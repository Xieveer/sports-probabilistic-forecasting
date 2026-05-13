"""DAG — утреннее обновление NHL (данные, odds post-step в source, фичи, материализация).

Расписание: ``0 9 * * *`` в **UTC** Airflow (по умолчанию) = **09:00 UTC** = **12:00 MSK**
(Москва, UTC+3, без перехода на летнее время с 2014 г.).

Пайплайн совпадает с :mod:`sports_forecast.orchestration.cron_refresh` / ``data_refresh``:
``source`` (включая инкрементальный odds-refresh при ``odds.enabled`` в ``conf/source/nhl.yaml``)
→ ``ingest`` → ``clean`` → ``features`` → ``materialize``.

По умолчанию один турнир ``nhl``, рынок ``winner_withOT`` / ``winner_withOT``, фичи ``advanced``
(см. ``conf/tournament/nhl.yaml``). Переопределение через Airflow Variables / ``dag_run.conf``.

Пул и ``flock`` — те же, что у ``data_refresh``, чтобы не нарушать контракт конкуренции refresh.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from airflow.models import Variable
from airflow.operators.bash import BashOperator

from airflow import DAG
from sports_forecast.orchestration.refresh_command import (
    build_refresh_per_tournament_command,
)


# ── Конфигурация (совместимо с dag_data_refresh) ─────────────────
PROJECT_DIR = Variable.get("SF_PROJECT_DIR", default_var="/app")
UV_RUN = Variable.get("SF_UV_RUN", default_var="uv run")

NHL_MORNING_TOURNAMENT = Variable.get("SF_NHL_MORNING_TOURNAMENT", default_var="nhl")
NHL_MORNING_FEATURES = Variable.get("SF_NHL_MORNING_FEATURES", default_var="advanced")
NHL_MORNING_MARKET = Variable.get("SF_NHL_MORNING_MARKET", default_var="winner_withOT")
NHL_MORNING_SPEC = Variable.get("SF_NHL_MORNING_SPEC", default_var="winner_withOT")

SOURCE_REFRESH_CMD = Variable.get(
    "SF_SOURCE_REFRESH_CMD",
    default_var=(
        f"{UV_RUN} python -m sports_forecast.orchestration.source_refresh --tournament {{tournament}}"
    ),
)
REFRESH_POOL = Variable.get("SF_REFRESH_POOL", default_var="sf_refresh_pool")
LOCK_FILE = Variable.get(
    "SF_REFRESH_LOCK_FILE",
    default_var="/tmp/sf_refresh_pipeline.lock",
)
LOCK_WAIT_SECONDS = int(Variable.get("SF_REFRESH_LOCK_WAIT_SECONDS", default_var="300"))
MAX_ACTIVE_RUNS = int(Variable.get("SF_NHL_MORNING_MAX_ACTIVE_RUNS", default_var="1"))
MAX_ACTIVE_TASKS = int(Variable.get("SF_NHL_MORNING_MAX_ACTIVE_TASKS", default_var="1"))

# ── DAG ───────────────────────────────────────────────────────────
default_args = {
    "owner": "ml-team",
    "depends_on_past": False,
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
    "execution_timeout": timedelta(hours=2),
}

with DAG(
    dag_id="nhl_morning_refresh",
    description="NHL: ежедневное утро MSK (09 UTC) — full refresh + materialize winner_withOT",
    schedule="0 9 * * *",  # 09:00 UTC = 12:00 MSK
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=["nhl", "data", "pipeline", "r37"],
    default_args=default_args,
    max_active_runs=MAX_ACTIVE_RUNS,
    max_active_tasks=MAX_ACTIVE_TASKS,
    doc_md=__doc__,
    params={
        "tournament": NHL_MORNING_TOURNAMENT,
        "features": NHL_MORNING_FEATURES,
        "market": NHL_MORNING_MARKET,
        "market_spec": NHL_MORNING_SPEC,
    },
) as dag:
    refresh_nhl = BashOperator(
        task_id="refresh_nhl_morning",
        bash_command=build_refresh_per_tournament_command(
            project_dir=PROJECT_DIR,
            uv_run=UV_RUN,
            tournaments_expr='{{ dag_run.conf.get("tournaments", params.tournament) }}',
            features_config='{{ dag_run.conf.get("features", params.features) }}',
            market='{{ dag_run.conf.get("market", params.market) }}',
            market_spec='{{ dag_run.conf.get("market_spec", params.market_spec) }}',
            source_cmd=SOURCE_REFRESH_CMD,
            lock_file=LOCK_FILE,
            lock_wait_seconds=LOCK_WAIT_SECONDS,
        ),
        execution_timeout=timedelta(hours=6),
        pool=REFRESH_POOL,
        pool_slots=1,
    )

    validate = BashOperator(
        task_id="validate",
        bash_command=f"cd {PROJECT_DIR} && {UV_RUN} python -m sports_forecast.validation.run_validation",
        pool=REFRESH_POOL,
        pool_slots=1,
    )

    refresh_nhl >> validate
