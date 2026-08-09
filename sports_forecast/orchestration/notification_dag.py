"""Нейтральная декларация heavy DAG для notification-профиля."""

from __future__ import annotations

from dataclasses import dataclass

from sports_forecast.orchestration.notification_profiles import NotificationProfile


@dataclass(frozen=True)
class HeavyDagSpec:
    """Проверяемая без Airflow часть контракта тяжёлого контура."""

    dag_id: str
    schedule: str
    timezone: str
    max_active_runs: int
    max_active_tasks: int
    refresh_pool: str
    lock_file: str
    lock_wait_seconds: int
    task_ids: tuple[str, str, str, str]
    dependencies: tuple[tuple[str, str], tuple[str, str], tuple[str, str]]


@dataclass(frozen=True)
class PollDagSpec:
    """Проверяемая без Airflow декларация лёгкого poll контура."""

    dag_id: str
    schedule: str
    timezone: str
    max_active_runs: int
    max_active_tasks: int
    pool: str
    retries: int
    retry_delay_seconds: int
    execution_timeout_seconds: int
    task_ids: tuple[str, str]
    dependencies: tuple[tuple[str, str], ...]


def build_heavy_dag_spec(profile: NotificationProfile) -> HeavyDagSpec:
    """Собрать контракт DAG только из notification-профиля."""
    return HeavyDagSpec(
        dag_id=f"notification_{profile.profile_id}_heavy_refresh",
        schedule=profile.heavy_schedule,
        timezone=profile.timezone,
        max_active_runs=profile.max_active_runs,
        max_active_tasks=profile.max_active_tasks,
        refresh_pool=profile.refresh_pool,
        lock_file=profile.lock_file,
        lock_wait_seconds=profile.lock_wait_seconds,
        task_ids=("refresh", "validate", "quality_gate", "initial_digest"),
        dependencies=(
            ("refresh", "validate"),
            ("validate", "quality_gate"),
            ("quality_gate", "initial_digest"),
        ),
    )


def build_poll_dag_spec(profile: NotificationProfile) -> PollDagSpec:
    """Собрать контракт независимого лёгкого DAG только из профиля."""
    return PollDagSpec(
        dag_id=f"notification_{profile.profile_id}_odds_poll",
        schedule=profile.poll_schedule,
        timezone=profile.timezone,
        max_active_runs=profile.poll_max_active_runs,
        max_active_tasks=profile.poll_max_active_tasks,
        pool=profile.poll_pool,
        retries=profile.poll_retries,
        retry_delay_seconds=profile.poll_retry_delay_seconds,
        execution_timeout_seconds=profile.poll_execution_timeout_seconds,
        task_ids=("poll_odds", "notify_failure"),
        dependencies=(("poll_odds", "notify_failure"),),
    )
