"""Однозначное определение результата фактической ставки по canonical счёту."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from sports_forecast.betting.real_bets import Result


def _score(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    raw = str(value)
    return int(raw) if raw.isdecimal() and len(raw) <= 3 else None


def resolve_bet_result(
    *,
    sport: str,
    market_spec: str,
    outcome: str,
    status: str,
    result: Mapping[str, Any],
) -> tuple[Result | None, str | None]:
    """Вернуть результат только при подтверждённом исходе поддержанного рынка."""
    if status == "cancelled":
        return None, "Матч отменён; проверьте расчёт букмекера"
    if status == "postponed":
        return None, "Матч перенесён"
    if status != "finished":
        return None, "Матч ещё не завершён"
    if (sport, market_spec) != ("ice_hockey", "winner_withOT"):
        return None, "Автоматический расчёт этого рынка не поддерживается"
    if outcome not in {"home_win", "away_win"}:
        return None, "Исход ставки не соответствует рынку"
    home = _score(result.get("home_score_ft"))
    away = _score(result.get("away_score_ft"))
    if home is None or away is None:
        return None, "Нет полного счёта матча"
    if home == away:
        return None, "Равный полный счёт требует проверки"
    winner: Literal["home_win", "away_win"] = "home_win" if home > away else "away_win"
    return ("win" if outcome == winner else "loss"), None
