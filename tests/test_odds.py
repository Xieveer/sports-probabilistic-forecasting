"""Тесты для sports_forecast.betting.odds — утилиты для работы с odds колонками."""

from __future__ import annotations

import pandas as pd
import pytest
from omegaconf import OmegaConf

from sports_forecast.betting.odds import (
    find_odds_column,
    get_odds_column_long_format,
    get_odds_column_name,
)


# ─────────────────────────────────────────────────────────────────────────────
# Фикстуры
# ─────────────────────────────────────────────────────────────────────────────


def _make_market_spec(**kwargs) -> object:
    """Создать mock MarketSpec."""
    return OmegaConf.create(kwargs)


# ─────────────────────────────────────────────────────────────────────────────
# get_odds_column_name
# ─────────────────────────────────────────────────────────────────────────────


class TestGetOddsColumnName:
    """Тесты для get_odds_column_name."""

    def test_winner_home(self) -> None:
        spec = _make_market_spec(name="winner_home")
        assert get_odds_column_name(spec) == "odds_home_win"

    def test_winner_away(self) -> None:
        spec = _make_market_spec(name="winner_away")
        assert get_odds_column_name(spec) == "odds_away_win"

    def test_total_over_with_line(self) -> None:
        spec = _make_market_spec(name="total_over", line=6.5)
        assert get_odds_column_name(spec) == "odds_total_over_6.5"

    def test_total_under_with_line(self) -> None:
        spec = _make_market_spec(name="total_under", line=5.5)
        assert get_odds_column_name(spec) == "odds_total_under_5.5"

    def test_total_over_without_line(self) -> None:
        spec = _make_market_spec(name="total_over")
        assert get_odds_column_name(spec) is None

    def test_unknown_market(self) -> None:
        spec = _make_market_spec(name="exotic_market")
        assert get_odds_column_name(spec) is None

    def test_total_integer_line(self) -> None:
        spec = _make_market_spec(name="total_over", line=7)
        assert get_odds_column_name(spec) == "odds_total_over_7"

    def test_handicap_home(self) -> None:
        spec = _make_market_spec(name="handicap_home", line=-1.5)
        assert get_odds_column_name(spec) == "odds_handicap_home_-1.5"

    def test_handicap_away(self) -> None:
        spec = _make_market_spec(name="handicap_away", line=1.5)
        assert get_odds_column_name(spec) == "odds_handicap_away_1.5"


# ─────────────────────────────────────────────────────────────────────────────
# get_odds_column_long_format
# ─────────────────────────────────────────────────────────────────────────────


class TestGetOddsColumnLongFormat:
    """Тесты для get_odds_column_long_format."""

    def test_winner_home_side(self) -> None:
        spec = _make_market_spec(name="winner")
        assert get_odds_column_long_format(spec, "h") == "odds_home_win"

    def test_winner_away_side(self) -> None:
        spec = _make_market_spec(name="winner")
        assert get_odds_column_long_format(spec, "a") == "odds_away_win"

    def test_winner_unknown_side(self) -> None:
        spec = _make_market_spec(name="winner")
        assert get_odds_column_long_format(spec, "x") is None

    def test_total_over_long(self) -> None:
        spec = _make_market_spec(name="total_over", line=6.5)
        assert get_odds_column_long_format(spec, "h") == "odds_total_over_6.5"


# ─────────────────────────────────────────────────────────────────────────────
# find_odds_column
# ─────────────────────────────────────────────────────────────────────────────


class TestFindOddsColumn:
    """Тесты для find_odds_column."""

    def test_exact_match(self) -> None:
        df = pd.DataFrame({"odds_total_over_6.5": [2.0, 1.8], "other": [1, 2]})
        spec = _make_market_spec(name="total_over", line=6.5)
        assert find_odds_column(df, spec) == "odds_total_over_6.5"

    def test_not_found(self) -> None:
        df = pd.DataFrame({"other_col": [1, 2]})
        spec = _make_market_spec(name="total_over", line=6.5)
        assert find_odds_column(df, spec) is None

    def test_underscore_variant(self) -> None:
        df = pd.DataFrame({"odds_total_over_6_5": [2.0, 1.8]})
        spec = _make_market_spec(name="total_over", line=6.5)
        assert find_odds_column(df, spec) == "odds_total_over_6_5"

    def test_winner_home(self) -> None:
        df = pd.DataFrame({"odds_home_win": [1.5, 2.3], "home_points": [3, 4]})
        spec = _make_market_spec(name="winner_home")
        assert find_odds_column(df, spec) == "odds_home_win"

    def test_unknown_market_returns_none(self) -> None:
        df = pd.DataFrame({"some_col": [1]})
        spec = _make_market_spec(name="unknown_market")
        assert find_odds_column(df, spec) is None

    def test_missing_line_returns_none(self) -> None:
        df = pd.DataFrame({"odds_total_over_6.5": [2.0]})
        spec = _make_market_spec(name="total_over")
        assert find_odds_column(df, spec) is None

    @pytest.mark.parametrize(
        "line,expected_col",
        [
            (3.5, "odds_total_over_3.5"),
            (9.5, "odds_total_over_9.5"),
        ],
    )
    def test_parametrized_lines(self, line: float, expected_col: str) -> None:
        df = pd.DataFrame({expected_col: [2.0, 1.5]})
        spec = _make_market_spec(name="total_over", line=line)
        assert find_odds_column(df, spec) == expected_col
