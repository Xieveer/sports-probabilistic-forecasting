"""Проверки конфигурационных notification-профилей."""

from __future__ import annotations

import pytest

from sports_forecast.config.loaders import (
    load_notification_profiles,
    load_tournament_quality_gate_config,
)
from sports_forecast.orchestration.notification_profiles import NotificationProfile


def test_nhl_notification_profile_contains_heavy_and_poll_contract() -> None:
    """NHL задаётся YAML-профилем, включая 10:00 МСК, poll и защиту refresh."""
    profile = load_notification_profiles()[0]

    assert profile.tournament == "nhl"
    assert profile.timezone == "Europe/Moscow"
    assert profile.heavy_schedule == "0 10 * * *"
    assert profile.window_hours == 48
    assert profile.max_active_runs == 1
    assert profile.refresh_pool == "sf_refresh_pool"
    assert profile.lock_file
    assert profile.poll_schedule == "*/15 * * * *"
    assert profile.poll_max_active_runs == 1
    assert profile.poll_max_active_tasks == 1
    assert profile.poll_pool == "sf_odds_poll_pool"
    assert profile.live_odds_adapter == "odds_api_h2h"
    assert profile.live_odds_bookmaker_config == "the_odds_api"
    assert profile.live_odds_sport_key == "icehockey_nhl"
    assert profile.live_odds_bookmaker_key == "pinnacle"
    quality_gate = load_tournament_quality_gate_config(profile.tournament)
    assert quality_gate.required_result_fields == ("home_score_ft", "away_score_ft", "match_end")


def test_notification_profile_rejects_invalid_limits() -> None:
    """Некорректный профиль не получает fallback к legacy DAG-настройкам."""
    with pytest.raises(ValueError, match="недопустимые лимиты"):
        NotificationProfile(
            profile_id="demo",
            tournament="demo",
            market="winner",
            market_spec="winner",
            window_hours=0,
            timezone="Europe/Moscow",
            heavy_schedule="0 10 * * *",
            max_active_runs=1,
            max_active_tasks=1,
            refresh_pool="pool",
            lock_file="/tmp/demo.lock",
            lock_wait_seconds=0,
            enabled=True,
        )
