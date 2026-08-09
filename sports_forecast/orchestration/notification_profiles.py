"""Конфигурационный профиль tournament-neutral уведомлений."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NotificationProfile:
    """Параметры heavy и лёгкого poll path без slug-specific логики."""

    profile_id: str
    tournament: str
    market: str
    market_spec: str
    window_hours: int
    timezone: str
    heavy_schedule: str
    max_active_runs: int
    max_active_tasks: int
    refresh_pool: str
    lock_file: str
    lock_wait_seconds: int
    enabled: bool
    poll_schedule: str = "*/15 * * * *"
    poll_max_active_runs: int = 1
    poll_max_active_tasks: int = 1
    poll_pool: str = "sf_odds_poll_pool"
    poll_retries: int = 2
    poll_retry_delay_seconds: int = 60
    poll_execution_timeout_seconds: int = 300
    live_odds_adapter: str = "odds_api_h2h"
    live_odds_bookmaker_config: str = "the_odds_api"
    live_odds_sport_key: str = "icehockey_nhl"
    live_odds_bookmaker_key: str = "pinnacle"
    live_odds_team_registry: str = "nhl"

    def __post_init__(self) -> None:
        """Отклонить профиль, который нельзя безопасно передать в DAG."""
        required = (
            self.profile_id,
            self.tournament,
            self.market,
            self.market_spec,
            self.timezone,
            self.heavy_schedule,
            self.refresh_pool,
            self.lock_file,
            self.poll_schedule,
            self.poll_pool,
            self.live_odds_adapter,
            self.live_odds_bookmaker_config,
            self.live_odds_sport_key,
            self.live_odds_bookmaker_key,
        )
        if not all(value.strip() for value in required):
            raise ValueError("Профиль уведомлений содержит пустое обязательное поле")
        if self.window_hours <= 0 or self.max_active_runs <= 0 or self.max_active_tasks <= 0:
            raise ValueError("Профиль уведомлений содержит недопустимые лимиты")
        if self.lock_wait_seconds < 0:
            raise ValueError("Профиль уведомлений содержит недопустимое время ожидания lock")
        if (
            self.poll_max_active_runs <= 0
            or self.poll_max_active_tasks <= 0
            or self.poll_retries < 0
            or self.poll_retry_delay_seconds < 0
            or self.poll_execution_timeout_seconds <= 0
        ):
            raise ValueError("Профиль уведомлений содержит недопустимые лимиты poll")
