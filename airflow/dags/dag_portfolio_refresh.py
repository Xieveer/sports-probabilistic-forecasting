"""Heavy refresh из канонического portfolio catalog с bounded fan-out.

Каждый deployment profile раскрывается в отдельную задачу. Lock принадлежит
паре tournament/source, поэтому повтор того же target сериализуется, а разные
турниры ограничиваются обычным Airflow pool без глобального ``flock``.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from airflow.models import Variable
from airflow.operators.bash import BashOperator

from airflow import DAG
from sports_forecast.orchestration.portfolio_refresh import (
    build_heavy_refresh_command,
    load_heavy_refresh_targets,
)


PROJECT_DIR = Variable.get("SF_PROJECT_DIR", default_var="/app")
UV_RUN = Variable.get("SF_UV_RUN", default_var="uv run")
CATALOG_PATH = Path(
    Variable.get("SF_PORTFOLIO_CATALOG", default_var=f"{PROJECT_DIR}/conf/portfolio/default.yaml")
)
REFRESH_POOL = Variable.get("SF_REFRESH_POOL", default_var="sf_refresh_pool")
MAX_ACTIVE_RUNS = int(Variable.get("SF_REFRESH_MAX_ACTIVE_RUNS", default_var="1"))

default_args = {
    "owner": "ml-team",
    "depends_on_past": False,
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
    "execution_timeout": timedelta(hours=6),
}

with DAG(
    dag_id="portfolio_refresh",
    description="Catalog-driven source → ingest → clean → features → materialize",
    schedule="0 */4 * * *",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=["data", "portfolio", "pipeline"],
    default_args=default_args,
    max_active_runs=MAX_ACTIVE_RUNS,
    doc_md=__doc__,
) as dag:
    for target in load_heavy_refresh_targets(CATALOG_PATH):
        BashOperator(
            task_id=f"refresh_{target.tournament}_{target.market_spec}",
            bash_command=build_heavy_refresh_command(
                target, project_dir=PROJECT_DIR, uv_run=UV_RUN
            ),
            pool=REFRESH_POOL,
            pool_slots=1,
        )
