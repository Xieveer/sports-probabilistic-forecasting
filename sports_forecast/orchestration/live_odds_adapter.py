"""Реестр profile-driven batch-adapter-ов live коэффициентов."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime
from typing import TYPE_CHECKING

from sports_forecast.betting.live_moneyline_extras import nhl_live_match_ref_from_prediction
from sports_forecast.config.loaders import load_bookmaker_config
from sports_forecast.data.providers.odds.live_nhl_pinnacle import (
    PinnacleH2HQuote,
    fetch_nhl_pinnacle_quotes_for_refs,
)
from sports_forecast.data.providers.odds.team_name_registry import (
    load_nhl_team_name_registry,
)
from sports_forecast.orchestration.notification_state import QuoteSnapshot
from sports_forecast.service.db.models import Prediction


if TYPE_CHECKING:
    from sports_forecast.orchestration.notification_profiles import NotificationProfile


LiveOddsAdapter = Callable[["NotificationProfile", Sequence[Prediction]], list[QuoteSnapshot]]


def fetch_profile_snapshots(
    profile: NotificationProfile, predictions: Sequence[Prediction]
) -> list[QuoteSnapshot]:
    """Получить снимки через adapter, заданный notification-профилем.

    Неизвестный adapter — конфигурационная ошибка task: Airflow выполнит его обычную
    failure branch, не подменяя источник или букмекера неявным fallback-ом.
    """
    try:
        adapter = LIVE_ODDS_ADAPTER_REGISTRY[profile.live_odds_adapter]
    except KeyError as exc:
        raise ValueError(
            "Для notification-профиля не настроен поддерживаемый live odds adapter"
        ) from exc
    return adapter(profile, predictions)


def fetch_odds_api_h2h_snapshots(
    predictions: Sequence[Prediction],
    *,
    bookmaker_config: str,
    sport_key: str,
    bookmaker_key: str,
    team_registry: str,
) -> list[QuoteSnapshot]:
    """Получить один batch h2h и нормализовать его для poll state.

    Все параметры приходят из notification-профиля, а не определяются по slug
    турнира в runtime.
    """
    refs = [
        ref
        for prediction in predictions
        if (ref := nhl_live_match_ref_from_prediction(prediction)).commence_utc is not None
    ]
    book_cfg = load_bookmaker_config(bookmaker_config)
    if book_cfg is None:
        raise ValueError("Не найден конфиг букмекера live odds adapter-а")
    registry_loader = TEAM_NAME_REGISTRY_LOADERS.get(team_registry)
    registry = registry_loader() if registry_loader is not None else None
    quotes = fetch_nhl_pinnacle_quotes_for_refs(
        refs,
        book_cfg=book_cfg,
        team_registry=registry,
        sport_key=sport_key,
        bookmaker_key=bookmaker_key,
    )
    return [
        _snapshot_from_quote(ref.match_id, ref.commence_utc, quotes.get(ref.match_id))
        for ref in refs
    ]


def _fetch_odds_api_h2h_snapshots(
    profile: NotificationProfile, predictions: Sequence[Prediction]
) -> list[QuoteSnapshot]:
    """Передать параметры profile в зарегистрированный h2h adapter."""
    return fetch_odds_api_h2h_snapshots(
        predictions,
        bookmaker_config=profile.live_odds_bookmaker_config,
        sport_key=profile.live_odds_sport_key,
        bookmaker_key=profile.live_odds_bookmaker_key,
        team_registry=profile.live_odds_team_registry,
    )


def _snapshot_from_quote(
    match_id: str, starts_at: datetime, quote: PinnacleH2HQuote | None
) -> QuoteSnapshot:
    """Сохранить отсутствие или частичность линии как невалидный снимок."""
    if quote is None or quote.decimal_home is None or quote.decimal_away is None:
        return QuoteSnapshot(match_id=match_id, starts_at=starts_at, line=None)
    return QuoteSnapshot(
        match_id=match_id,
        starts_at=starts_at,
        line={"home": quote.decimal_home, "away": quote.decimal_away},
    )


LIVE_ODDS_ADAPTER_REGISTRY: dict[str, LiveOddsAdapter] = {
    "odds_api_h2h": _fetch_odds_api_h2h_snapshots,
}

TEAM_NAME_REGISTRY_LOADERS = {
    "nhl": load_nhl_team_name_registry,
}


__all__ = [
    "LIVE_ODDS_ADAPTER_REGISTRY",
    "fetch_odds_api_h2h_snapshots",
    "fetch_profile_snapshots",
]
