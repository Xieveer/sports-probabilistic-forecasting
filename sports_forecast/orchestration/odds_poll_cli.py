"""CLI лёгкого profile-driven poll live коэффициентов для Airflow."""

from __future__ import annotations

import argparse
import os
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import cast

from sports_forecast.config.loaders import load_notification_profiles
from sports_forecast.orchestration.live_odds_adapter import fetch_profile_snapshots
from sports_forecast.orchestration.notification_profiles import NotificationProfile
from sports_forecast.orchestration.notification_state import QuoteSnapshot
from sports_forecast.orchestration.odds_poll_notification import run_odds_poll
from sports_forecast.service.db.engine import get_engine, get_session, init_db
from sports_forecast.service.db.models import Prediction
from sports_forecast.service.db.repository import NotificationStateRepository, PredictionRepository
from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Проверить live коэффициенты notification-профиля."
    )
    parser.add_argument("--profile", required=True, help="Идентификатор notification-профиля.")
    parser.add_argument(
        "--logical-cycle", required=True, help="Стабильный ID Airflow logical cycle."
    )
    return parser.parse_args(argv)


def _profile(profile_id: str) -> NotificationProfile:
    """Найти включённый профиль без привязки к tournament slug."""
    for profile in load_notification_profiles():
        if profile.profile_id == profile_id:
            return profile
    raise ValueError("Включённый notification-профиль не найден")


def _chat_ids(name: str) -> tuple[str, ...]:
    """Разобрать Telegram IDs, не выводя их значения в журнал."""
    return tuple(value.strip() for value in os.environ.get(name, "").split(",") if value.strip())


def _fetch_quotes(
    profile: NotificationProfile, predictions: Sequence[Prediction]
) -> list[QuoteSnapshot]:
    """Передать profile-driven adapter-у параметры выбранного notification-контура."""
    return fetch_profile_snapshots(profile, predictions)


def main(argv: list[str] | None = None) -> int:
    """Прочитать materialized витрину и выполнить один poll cycle."""
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
            run_odds_poll(
                profile=profile,
                now=now,
                predictions=predictions,
                fetch_quotes=lambda prediction_inputs: _fetch_quotes(
                    profile, cast(Sequence[Prediction], prediction_inputs)
                ),
                allowed_chat_ids=_chat_ids("BOT_ALLOWED_USER_IDS"),
                token=os.environ.get("BOT_TOKEN", ""),
                state_repository=NotificationStateRepository(session),
                logical_cycle=args.logical_cycle,
            )
    except Exception:
        logger.exception("Poll коэффициентов не выполнен profile=%s", args.profile)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
