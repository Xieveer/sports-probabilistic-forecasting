"""DAG — утреннее обновление NHL (данные, odds post-step в source, фичи, материализация).

Расписание: ``0 9 * * *`` в **UTC** Airflow (по умолчанию) = **09:00 UTC** = **12:00 MSK**
(Москва, UTC+3, без перехода на летнее время с 2014 г.).

Пайплайн совпадает с :mod:`sports_forecast.orchestration.cron_refresh` / ``data_refresh``:
``source`` (включая инкрементальный odds-refresh при ``odds.enabled`` в ``conf/source/nhl.yaml``)
→ ``ingest`` → ``clean`` → ``features`` → ``materialize``.

После refresh и шага ``validate`` выполняется задача ``post_refresh_digest`` (тот же пул
``SF_REFRESH_POOL``, слот 1 — digest стартует только после освобождения flock refresh):
сводка витрины / live Pinnacle и одно Telegram-сообщение через
:mod:`sports_forecast.orchestration.post_refresh_digest`, если не отключено.

Airflow Variables (см. также ``docs/source/nhl_local_operations.rst``):

* ``SF_TELEGRAM_DIGEST_ENABLE`` (по умолчанию ``true``) — при значениях ``0``, ``false``, ``no``,
  ``off`` (без учёта регистра) задача **runtime** завершается успешно без вызова CLI/Telegram.
* ``SF_POST_REFRESH_DIGEST_CMD`` — непустая строка (после trim): выполняется
  ``cd <SF_PROJECT_DIR> && bash -lc "<cmd>"``; оператор должен сам включать ``uv run`` / активацию
  venv при необходимости. Иначе — встроенная команда ``<SF_UV_RUN> python -m ...post_refresh_digest``.

По умолчанию один турнир ``nhl``, рынок ``winner_withOT`` / ``winner_withOT``, фичи ``advanced``
(см. ``conf/tournament/nhl.yaml``). Переопределение через Airflow Variables / ``dag_run.conf``.

Пул и ``flock`` — те же, что у ``data_refresh``, чтобы не нарушать контракт конкуренции refresh.
"""

from __future__ import annotations

import shlex
from datetime import datetime, timedelta
from textwrap import dedent

from airflow.models import Variable
from airflow.operators.bash import BashOperator

from airflow import DAG
from sports_forecast.orchestration.refresh_command import (
    build_refresh_per_tournament_command,
)


def _build_post_refresh_digest_bash_command(*, project_dir: str, uv_run: str) -> str:
    """Собрать ``bash_command`` с Jinja (Airflow 2 ``var.value``, ``dag_run``, ``params``).

    Литералы ``project_dir`` / ``uv_run`` подставляются при парсинге DAG; условный skip и override
    команды читаются из Variables **на каждый запуск** через шаблонизацию.
    """
    tmpl = dedent(
        """
        {% set _en = (var.value.get('SF_TELEGRAM_DIGEST_ENABLE', 'true') | lower | trim) %}
        {% if _en in ['0', 'false', 'no', 'off'] %}
        echo "post_refresh_digest skipped (SF_TELEGRAM_DIGEST_ENABLE)" && exit 0
        {% else %}
        {% set _cmd = (var.value.get('SF_POST_REFRESH_DIGEST_CMD', '') | default('', true) | trim) %}
        set -euo pipefail
        cd __PROJECT_DIR__ && \
        {% if _cmd %}
        bash -lc {{ _cmd | tojson }}
        {% else %}
        __UV_RUN__ python -m sports_forecast.orchestration.post_refresh_digest \
          --tournament {{ dag_run.conf.get("tournament", params.tournament) | tojson }} \
          --market {{ dag_run.conf.get("market", params.market) | tojson }} \
          --market-spec {{ dag_run.conf.get("market_spec", params.market_spec) | tojson }} \
          --project-root __PROJECT_ROOT__
        {% endif %}
        {% endif %}
        """
    ).strip()
    qdir = shlex.quote(project_dir)
    return (
        tmpl.replace("__PROJECT_DIR__", qdir)
        .replace("__PROJECT_ROOT__", qdir)
        .replace("__UV_RUN__", uv_run)
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
# default_args содержит retries=2: при падении digest после успешного send возможен повтор —
# см. модуль sports_forecast.orchestration.post_refresh_digest (дубликаты Telegram) и опцию
# SF_TELEGRAM_DIGEST_DEDUP + маркер в .cache/digest_telegram_sent/.
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

    # BashOperator без собственных retries наследует default_args["retries"]; при ошибке между
    # отправкой Telegram и кодом возврата возможен второй успешный send — см. post_refresh_digest + SF_TELEGRAM_DIGEST_DEDUP.
    post_refresh_digest = BashOperator(
        task_id="post_refresh_digest",
        bash_command=_build_post_refresh_digest_bash_command(
            project_dir=PROJECT_DIR,
            uv_run=UV_RUN,
        ),
        pool=REFRESH_POOL,
        pool_slots=1,
    )

    refresh_nhl >> validate >> post_refresh_digest
