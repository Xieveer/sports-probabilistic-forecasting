"""
Решение bet / no_bet по edge модели относительно implied prob из decimal odds.

Использует ту же базовую формулу, что и ``conf/betting.yaml`` для симулятора:
``p_implied = 1 / decimal_odds`` (без de-vig). Парсинг ``odds_raw`` не дублируется —
для извлечения decimal из сырых данных см. :mod:`sports_forecast.betting.odds`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import isfinite
from typing import Final


class BetDecision(str, Enum):
    """Итог сравнения модельной вероятности с линией."""

    BET = "bet"
    NO_BET = "no_bet"
    INSUFFICIENT_DATA = "insufficient_data"


@dataclass(frozen=True, slots=True)
class EdgeDecisionParams:
    """Пороги из ``conf/service_api.yaml`` (или явно переданные в коде)."""

    edge_threshold: float
    min_odds: float = 1.01


_DEFAULT_MIN_ODDS: Final[float] = 1.01


def implied_probability_from_decimal(decimal_odds: float) -> float:
    """Implied probability (с маржой букмекера) из decimal коэффициента.

    Args:
        decimal_odds: Decimal odds стороны (например 1.95).

    Returns:
        ``1 / decimal_odds``.

    Raises:
        ValueError: Если коэффициент не конечен или ``<= 1``.
    """
    if not isfinite(decimal_odds) or decimal_odds <= 1.0:
        msg = f"decimal_odds must be finite and > 1.0, got {decimal_odds!r}"
        raise ValueError(msg)
    return 1.0 / decimal_odds


def compute_edge(model_proba: float, decimal_odds: float) -> float:
    """Edge в единицах вероятности: ``p_model - p_implied``.

    Args:
        model_proba: Оценённая вероятность исхода ``[0, 1]``.
        decimal_odds: Decimal odds на тот же исход.

    Returns:
        Разница вероятностей.

    Raises:
        ValueError: При невалидных входных данных.
    """
    if not isfinite(model_proba):
        msg = f"model_proba must be finite, got {model_proba!r}"
        raise ValueError(msg)
    implied = implied_probability_from_decimal(decimal_odds)
    return float(model_proba) - implied


def decide_bet(
    model_proba: float | None,
    decimal_odds: float | None,
    params: EdgeDecisionParams,
) -> tuple[BetDecision, float | None]:
    """Сравнить модель с линией и вернуть решение и edge (если посчитан).

    * ``BET`` — если ``model_proba - 1/decimal_odds >= edge_threshold``.
    * ``NO_BET`` — данные достаточны, но edge строго ниже порога.
    * ``INSUFFICIENT_DATA`` — нет валидных коэффициентов/вероятности.

    Args:
        model_proba: Вероятность исхода или ``None`` / нечисло.
        decimal_odds: Decimal odds на тот же исход или ``None``.
        params: Порог edge и минимально допустимый коэффициент.

    Returns:
        Пара ``(решение, edge или None)``.
    """
    min_odds = params.min_odds if isfinite(params.min_odds) else _DEFAULT_MIN_ODDS
    if min_odds <= 1.0:
        min_odds = _DEFAULT_MIN_ODDS

    if decimal_odds is None or not isfinite(decimal_odds) or decimal_odds < min_odds:
        return (BetDecision.INSUFFICIENT_DATA, None)

    if model_proba is None or not isfinite(model_proba):
        return (BetDecision.INSUFFICIENT_DATA, None)

    p = float(model_proba)
    if p < 0.0 or p > 1.0:
        return (BetDecision.INSUFFICIENT_DATA, None)

    try:
        edge = compute_edge(p, float(decimal_odds))
    except ValueError:
        return (BetDecision.INSUFFICIENT_DATA, None)

    if edge >= params.edge_threshold:
        return (BetDecision.BET, edge)
    return (BetDecision.NO_BET, edge)
