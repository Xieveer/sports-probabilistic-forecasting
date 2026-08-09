"""Совместимая точка discovery для DAG, созданных notification factory."""

from __future__ import annotations

from airflow.models import Variable
from notification_dag_factory import build_notification_dags

from sports_forecast.config.loaders import load_notification_profiles


PROJECT_DIR = Variable.get("SF_PROJECT_DIR", default_var="/app")
UV_RUN = Variable.get("SF_UV_RUN", default_var="uv run")
SOURCE_REFRESH_CMD = Variable.get(
    "SF_SOURCE_REFRESH_CMD",
    default_var=(
        f"{UV_RUN} python -m sports_forecast.orchestration.source_refresh --tournament {{tournament}}"
    ),
)

globals().update(
    build_notification_dags(
        load_notification_profiles(),
        project_dir=PROJECT_DIR,
        uv_run=UV_RUN,
        source_refresh_cmd=SOURCE_REFRESH_CMD,
    )
)
