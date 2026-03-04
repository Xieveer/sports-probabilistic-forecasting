"""
Betting module — симуляция ставок и утилиты для работы с коэффициентами.
"""

from sports_forecast.betting.odds import (
    extract_odds_from_raw,
    find_odds_column,
    get_odds_column_name,
)
from sports_forecast.betting.simulator import BettingMetrics, BettingResult, BettingSimulator


__all__ = [
    "BettingMetrics",
    "BettingResult",
    "BettingSimulator",
    "extract_odds_from_raw",
    "find_odds_column",
    "get_odds_column_name",
]
