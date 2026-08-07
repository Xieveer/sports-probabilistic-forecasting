"""Контракт tournament-neutral heavy DAG factory без Airflow runtime."""

from __future__ import annotations

from sports_forecast.orchestration.notification_dag import build_heavy_dag_spec, build_poll_dag_spec
from sports_forecast.orchestration.notification_profiles import NotificationProfile


def test_heavy_dag_spec_uses_neutral_profile_and_orders_gate_before_digest() -> None:
    """Factory не зависит от NHL и строит heavy path из параметров профиля."""
    profile = NotificationProfile(
        profile_id="demo-hockey",
        tournament="demo_league",
        market="winner",
        market_spec="winner",
        window_hours=24,
        timezone="Europe/Berlin",
        heavy_schedule="5 6 * * *",
        max_active_runs=2,
        max_active_tasks=1,
        refresh_pool="demo-pool",
        lock_file="/tmp/demo.lock",
        lock_wait_seconds=42,
        enabled=True,
    )

    spec = build_heavy_dag_spec(profile)

    assert spec.dag_id == "notification_demo-hockey_heavy_refresh"
    assert spec.schedule == "5 6 * * *"
    assert spec.timezone == "Europe/Berlin"
    assert spec.max_active_runs == 2
    assert spec.refresh_pool == "demo-pool"
    assert spec.lock_file == "/tmp/demo.lock"
    assert spec.task_ids == ("refresh", "validate", "quality_gate", "initial_digest")
    assert spec.dependencies == (
        ("refresh", "validate"),
        ("validate", "quality_gate"),
        ("quality_gate", "initial_digest"),
    )


def test_poll_dag_spec_uses_profile_schedule_and_isolated_limits() -> None:
    """Лёгкий DAG не содержит tournament-specific параметров и не пересекает свои run."""
    profile = NotificationProfile(
        profile_id="demo-hockey",
        tournament="demo_league",
        market="winner",
        market_spec="winner",
        window_hours=24,
        timezone="Europe/Berlin",
        heavy_schedule="5 6 * * *",
        max_active_runs=2,
        max_active_tasks=1,
        refresh_pool="refresh-pool",
        lock_file="/tmp/demo.lock",
        lock_wait_seconds=42,
        enabled=True,
        poll_schedule="*/7 * * * *",
        poll_max_active_runs=1,
        poll_max_active_tasks=1,
        poll_pool="odds-poll-pool",
        poll_retries=3,
        poll_retry_delay_seconds=11,
        poll_execution_timeout_seconds=90,
        live_odds_adapter="odds_api_h2h",
    )

    spec = build_poll_dag_spec(profile)

    assert spec.dag_id == "notification_demo-hockey_odds_poll"
    assert spec.schedule == "*/7 * * * *"
    assert spec.timezone == "Europe/Berlin"
    assert spec.max_active_runs == 1
    assert spec.max_active_tasks == 1
    assert spec.pool == "odds-poll-pool"
    assert spec.retries == 3
    assert spec.retry_delay_seconds == 11
    assert spec.execution_timeout_seconds == 90
    assert spec.task_ids == ("poll_odds", "notify_failure")
    assert spec.dependencies == (("poll_odds", "notify_failure"),)
