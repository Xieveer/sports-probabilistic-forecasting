"""
Тесты для модуля вычисления таргетов.

Покрывают:
- compute_target_from_market_spec: основная точка входа
- _compute_target_from_source: новая архитектура (target_source_key)
- get_target_name: генерация имени таргета
- Обработка ошибок (отсутствующие колонки, неизвестные comparison)
"""

from __future__ import annotations

import pandas as pd
import pytest
from omegaconf import DictConfig

from sports_forecast.utils.targets import (
    TargetComputationError,
    compute_target_from_market_spec,
    get_target_name,
)


# ==================== Fixtures ====================


@pytest.fixture
def match_data_wide() -> pd.DataFrame:
    """Wide format данные матчей."""
    return pd.DataFrame(
        {
            "id": [1, 2, 3, 4, 5],
            "home_points": [5, 3, 7, 4, 6],
            "away_points": [3, 5, 2, 4, 8],
        }
    )


@pytest.fixture
def match_data_long() -> pd.DataFrame:
    """Long format данные матчей."""
    return pd.DataFrame(
        {
            "id": [1, 1, 2, 2, 3, 3],
            "pl_points": [5, 3, 3, 5, 7, 2],
            "opp_points": [3, 5, 5, 3, 2, 7],
            "side": ["h", "a", "h", "a", "h", "a"],
        }
    )


@pytest.fixture
def tournament_cfg() -> DictConfig:
    """Tournament config с target_sources."""
    return DictConfig(
        {
            "name": "uel_kz_1",
            "target_sources": {
                "player_win": {
                    "format": "long",
                    "player_column": "pl_points",
                    "opponent_column": "opp_points",
                    "comparison": "greater",
                },
                "total_sum": {
                    "format": "wide",
                    "home_column": "home_points",
                    "away_column": "away_points",
                    "comparison": "total_over",
                },
                "total_sum_under": {
                    "format": "wide",
                    "home_column": "home_points",
                    "away_column": "away_points",
                    "comparison": "total_under",
                },
            },
        }
    )


# ==================== Winner target Tests ====================


class TestWinnerTarget:
    """Тесты для winner таргета (новая архитектура с target_source_key)."""

    def test_player_win_long_format(
        self,
        match_data_long: pd.DataFrame,
        tournament_cfg: DictConfig,
    ) -> None:
        """Таргет победы игрока в long format: pl_points > opp_points."""
        market_spec = DictConfig(
            {
                "name": "winner",
                "target_source_key": "player_win",
                "data_format": "long",
            }
        )

        target = compute_target_from_market_spec(match_data_long, market_spec, tournament_cfg)

        assert len(target) == len(match_data_long)
        assert target.dtype == int
        # Матч 1: home=5, away=3 → home wins (1), away loses (0)
        assert target.iloc[0] == 1  # pl=5 > opp=3
        assert target.iloc[1] == 0  # pl=3 < opp=5
        # Матч 2: home=3, away=5 → home loses, away wins
        assert target.iloc[2] == 0
        assert target.iloc[3] == 1


# ==================== Total target Tests ====================


class TestTotalTarget:
    """Тесты для total таргетов."""

    def test_total_over(
        self,
        match_data_wide: pd.DataFrame,
        tournament_cfg: DictConfig,
    ) -> None:
        """Таргет total over: (home + away) > line."""
        market_spec = DictConfig(
            {
                "name": "total_over",
                "target_source_key": "total_sum",
                "data_format": "wide",
                "line": 6.5,
            }
        )

        target = compute_target_from_market_spec(
            match_data_wide, market_spec, tournament_cfg, line=6.5
        )

        # Матч 1: 5+3=8 > 6.5 → 1
        # Матч 2: 3+5=8 > 6.5 → 1
        # Матч 3: 7+2=9 > 6.5 → 1
        # Матч 4: 4+4=8 > 6.5 → 1
        # Матч 5: 6+8=14 > 6.5 → 1
        expected = pd.Series([1, 1, 1, 1, 1])
        pd.testing.assert_series_equal(target, expected, check_names=False)

    def test_total_under(
        self,
        match_data_wide: pd.DataFrame,
        tournament_cfg: DictConfig,
    ) -> None:
        """Таргет total under: (home + away) < line."""
        market_spec = DictConfig(
            {
                "name": "total_under",
                "target_source_key": "total_sum_under",
                "data_format": "wide",
                "line": 9.5,
            }
        )

        target = compute_target_from_market_spec(
            match_data_wide, market_spec, tournament_cfg, line=9.5
        )

        # Матч 1: 5+3=8 < 9.5 → 1
        # Матч 2: 3+5=8 < 9.5 → 1
        # Матч 3: 7+2=9 < 9.5 → 1
        # Матч 4: 4+4=8 < 9.5 → 1
        # Матч 5: 6+8=14 < 9.5 → 0
        expected = pd.Series([1, 1, 1, 1, 0])
        pd.testing.assert_series_equal(target, expected, check_names=False)

    def test_total_over_without_line_raises(
        self,
        match_data_wide: pd.DataFrame,
        tournament_cfg: DictConfig,
    ) -> None:
        """Total over без line вызывает ошибку."""
        market_spec = DictConfig(
            {
                "name": "total_over",
                "target_source_key": "total_sum",
                "data_format": "wide",
            }
        )

        with pytest.raises(TargetComputationError, match="Line обязательна"):
            compute_target_from_market_spec(match_data_wide, market_spec, tournament_cfg)

    def test_total_over_boundary_value(
        self,
        tournament_cfg: DictConfig,
    ) -> None:
        """Граничное значение: total == line → 0 (строго больше)."""
        df = pd.DataFrame({"home_points": [3], "away_points": [4]})
        market_spec = DictConfig(
            {
                "name": "total_over",
                "target_source_key": "total_sum",
                "data_format": "wide",
                "line": 7.0,
            }
        )

        target = compute_target_from_market_spec(df, market_spec, tournament_cfg, line=7.0)
        # 3+4=7 > 7.0 → False → 0
        assert target.iloc[0] == 0


# ==================== Error handling Tests ====================


class TestTargetErrors:
    """Тесты обработки ошибок."""

    def test_missing_column_raises(self, tournament_cfg: DictConfig) -> None:
        """Отсутствие колонки вызывает TargetComputationError."""
        df = pd.DataFrame({"other_col": [1, 2]})
        market_spec = DictConfig(
            {
                "name": "total_over",
                "target_source_key": "total_sum",
                "data_format": "wide",
                "line": 6.5,
            }
        )

        with pytest.raises(TargetComputationError, match="Колонка.*не найдена"):
            compute_target_from_market_spec(df, market_spec, tournament_cfg, line=6.5)

    def test_missing_target_source_key_raises(
        self,
        match_data_wide: pd.DataFrame,
        tournament_cfg: DictConfig,
    ) -> None:
        """Несуществующий target_source_key вызывает ошибку."""
        market_spec = DictConfig(
            {
                "name": "test",
                "target_source_key": "nonexistent",
                "data_format": "wide",
            }
        )

        with pytest.raises(TargetComputationError, match="не найден"):
            compute_target_from_market_spec(match_data_wide, market_spec, tournament_cfg)

    def test_no_target_sources_in_tournament_raises(
        self,
        match_data_wide: pd.DataFrame,
    ) -> None:
        """Tournament без target_sources вызывает ошибку."""
        tournament_cfg = DictConfig({"name": "empty"})
        market_spec = DictConfig(
            {
                "name": "test",
                "target_source_key": "player_win",
                "data_format": "long",
            }
        )

        with pytest.raises(TargetComputationError, match="не содержит target_sources"):
            compute_target_from_market_spec(match_data_wide, market_spec, tournament_cfg)


# ==================== get_target_name Tests ====================


class TestGetTargetName:
    """Тесты для get_target_name."""

    def test_winner_target_name(self) -> None:
        """Имя таргета для winner market."""
        market_spec = DictConfig(
            {
                "name": "winner",
                "market_family": "winner",
                "target_name": "target_is_win",
            }
        )
        name = get_target_name(market_spec)
        assert name == "target_is_win"

    def test_total_target_name_with_line(self) -> None:
        """Имя таргета для total market с линией."""
        market_spec = DictConfig(
            {
                "name": "total_over",
                "market_family": "total",
                "target_name": "target_total_over",
                "line": 6.5,
            }
        )
        name = get_target_name(market_spec, line=6.5)
        assert name == "target_total_over_6_5"

    def test_total_target_name_line_from_spec(self) -> None:
        """Линия берётся из market_spec если не передана явно."""
        market_spec = DictConfig(
            {
                "name": "total_over",
                "market_family": "total",
                "target_name": "target_total_over",
                "line": 9.5,
            }
        )
        name = get_target_name(market_spec)
        assert name == "target_total_over_9_5"

    def test_fallback_target_name(self) -> None:
        """Если target_name не задан, используется 'target'."""
        market_spec = DictConfig({"name": "test", "market_family": "winner"})
        name = get_target_name(market_spec)
        assert name == "target"
