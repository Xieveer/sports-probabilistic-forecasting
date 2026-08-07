"""CLI initial digest для задачи Airflow heavy path."""

from __future__ import annotations

import argparse
import os
from datetime import UTC, datetime

from sports_forecast.config.loaders import load_notification_profiles
from sports_forecast.orchestration.initial_notification import run_initial_digest
from sports_forecast.orchestration.live_odds_adapter import fetch_profile_snapshots
from sports_forecast.orchestration.notification_profiles import NotificationProfile
from sports_forecast.orchestration.notification_state import QuoteSnapshot
from sports_forecast.service.db.engine import get_engine, get_session, init_db
from sports_forecast.service.db.models import Prediction
from sports_forecast.service.db.repository import NotificationStateRepository, PredictionRepository
from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Отправить initial digest notification-профиля.")
    parser.add_argument("--profile", required=True, help="Идентификатор notification-профиля.")
    return parser.parse_args(argv)


def _profile(profile_id: str):
    """Найти включённый профиль, не привязываясь к турниру."""
    for profile in load_notification_profiles():
        if profile.profile_id == profile_id:
            return profile
    raise ValueError("Включённый notification-профиль не найден")


def _chat_ids(name: str) -> tuple[str, ...]:
    """Разобрать список Telegram ID без вывода значений в журнал."""
    return tuple(value.strip() for value in os.environ.get(name, "").split(",") if value.strip())


def main(argv: list[str] | None = None) -> int:
    """Прочитать materialized прогнозы и выполнить initial fan-out."""
    args = _parse_args(argv)
    try:
        profile = _profile(args.profile)
        now = datetime.now(UTC)
        engine = get_engine()
        init_db(engine)
        with get_session(engine=engine) as session:
            predictions = PredictionRepository(session).get_upcoming_predictions(
                tournament=profile.tournament,
                market=profile.market,
                market_spec=profile.market_spec,
                hours=profile.window_hours,
                now_utc=now,
            )
            run_initial_digest(
                profile=profile,
                now=now,
                predictions=predictions,
                quote_snapshots=_quote_snapshots(profile, predictions),
                allowed_chat_ids=_chat_ids("BOT_ALLOWED_USER_IDS"),
                token=os.environ.get("BOT_TOKEN", ""),
                state_repository=NotificationStateRepository(session),
            )
    except Exception:
        logger.exception("Initial digest notification-профиля не выполнен profile=%s", args.profile)
        return 1
    return 0


def _quote_snapshots(
    profile: NotificationProfile, predictions: list[Prediction]
) -> list[QuoteSnapshot]:
    """Получить batch-котировки для baseline начального digest."""
    return fetch_profile_snapshots(profile, predictions)


if __name__ == "__main__":
    raise SystemExit(main())
