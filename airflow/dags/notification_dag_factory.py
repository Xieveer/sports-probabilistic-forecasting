"""Airflow factory для тяжёлых notification-профилей."""

from __future__ import annotations

from datetime import timedelta

import pendulum
from airflow.operators.bash import BashOperator
from airflow.utils.trigger_rule import TriggerRule
from sf_scheduled_refresh_ops import bash_refresh_per_tournament, bash_run_validation

from airflow import DAG
from sports_forecast.orchestration.notification_dag import build_heavy_dag_spec, build_poll_dag_spec
from sports_forecast.orchestration.notification_profiles import NotificationProfile


def build_notification_dags(
    profiles: tuple[NotificationProfile, ...],
    *,
    project_dir: str,
    uv_run: str,
    source_refresh_cmd: str,
) -> dict[str, DAG]:
    """Создать independent heavy и poll DAG на каждый включённый профиль."""
    dags: dict[str, DAG] = {}
    for profile in profiles:
        spec = build_heavy_dag_spec(profile)
        default_args = {
            "owner": "ml-team",
            "depends_on_past": False,
            "retries": 2,
            "retry_delay": timedelta(minutes=5),
            "execution_timeout": timedelta(hours=2),
        }
        dag = DAG(
            dag_id=spec.dag_id,
            description="Конфигурационный heavy refresh и initial digest.",
            schedule=spec.schedule,
            start_date=pendulum.datetime(2026, 1, 1, tz=spec.timezone),
            catchup=False,
            tags=["notification", "heavy", profile.tournament],
            default_args=default_args,
            max_active_runs=spec.max_active_runs,
            max_active_tasks=spec.max_active_tasks,
        )
        with dag:
            watermark_path = (
                f"/tmp/sf_quality_watermark_{profile.profile_id}_"
                "{{ dag_run.run_id | replace('/', '_') }}.json"
            )
            capture_quality_watermark = BashOperator(
                task_id="capture_quality_watermark",
                bash_command=(
                    f"cd {project_dir} && {uv_run} python -m "
                    "sports_forecast.orchestration.tournament_quality_watermark "
                    f"--tournament {profile.tournament} --output '{watermark_path}'"
                ),
                pool=spec.refresh_pool,
                pool_slots=1,
            )
            refresh = bash_refresh_per_tournament(
                dag,
                task_id="refresh",
                project_dir=project_dir,
                uv_run=uv_run,
                tournaments_expr=profile.tournament,
                features_config="advanced",
                market=profile.market,
                market_spec=profile.market_spec,
                source_cmd=source_refresh_cmd,
                lock_file=spec.lock_file,
                lock_wait_seconds=spec.lock_wait_seconds,
                refresh_pool=spec.refresh_pool,
            )
            validate = bash_run_validation(
                dag,
                task_id="validate",
                project_dir=project_dir,
                uv_run=uv_run,
                refresh_pool=spec.refresh_pool,
            )
            quality_gate = BashOperator(
                task_id="quality_gate",
                bash_command=(
                    f"cd {project_dir} && {uv_run} python -m "
                    "sports_forecast.orchestration.tournament_quality_gate_cli "
                    f"--tournament {profile.tournament} --watermark-file '{watermark_path}'"
                ),
                pool=spec.refresh_pool,
                pool_slots=1,
            )
            initial_digest = BashOperator(
                task_id="initial_digest",
                bash_command=(
                    f"cd {project_dir} && {uv_run} python -m "
                    "sports_forecast.orchestration.initial_digest_cli "
                    f"--profile {profile.profile_id}"
                ),
                pool=spec.refresh_pool,
                pool_slots=1,
            )
            notify_failure = BashOperator(
                task_id="notify_failure",
                bash_command=(
                    f"cd {project_dir} && {uv_run} python -m "
                    "sports_forecast.orchestration.notification_failure_cli "
                    "--failure-kind heavy_path_failed"
                ),
                trigger_rule=TriggerRule.ONE_FAILED,
                pool=spec.refresh_pool,
                pool_slots=1,
            )
            capture_quality_watermark >> refresh >> validate >> quality_gate >> initial_digest
            [
                capture_quality_watermark,
                refresh,
                validate,
                quality_gate,
                initial_digest,
            ] >> notify_failure
        dags[spec.dag_id] = dag
        poll_spec = build_poll_dag_spec(profile)
        poll_default_args = {
            "owner": "ml-team",
            "depends_on_past": False,
            "retries": poll_spec.retries,
            "retry_delay": timedelta(seconds=poll_spec.retry_delay_seconds),
            "execution_timeout": timedelta(seconds=poll_spec.execution_timeout_seconds),
        }
        poll_dag = DAG(
            dag_id=poll_spec.dag_id,
            description="Конфигурационный лёгкий poll live коэффициентов.",
            schedule=poll_spec.schedule,
            start_date=pendulum.datetime(2026, 1, 1, tz=poll_spec.timezone),
            catchup=False,
            tags=["notification", "odds-poll", profile.tournament],
            default_args=poll_default_args,
            max_active_runs=poll_spec.max_active_runs,
            max_active_tasks=poll_spec.max_active_tasks,
        )
        with poll_dag:
            poll_odds = BashOperator(
                task_id="poll_odds",
                bash_command=(
                    f"cd {project_dir} && {uv_run} python -m "
                    "sports_forecast.orchestration.odds_poll_cli "
                    f"--profile {profile.profile_id} --logical-cycle '{{{{ run_id }}}}'"
                ),
                pool=poll_spec.pool,
                pool_slots=1,
            )
            notify_poll_failure = BashOperator(
                task_id="notify_failure",
                bash_command=(
                    f"cd {project_dir} && {uv_run} python -m "
                    "sports_forecast.orchestration.notification_failure_cli "
                    "--failure-kind odds_poll_failed"
                ),
                trigger_rule=TriggerRule.ONE_FAILED,
                pool=poll_spec.pool,
                pool_slots=1,
            )
            poll_odds >> notify_poll_failure
        dags[poll_spec.dag_id] = poll_dag
    return dags
