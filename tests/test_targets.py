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
    FormulaTargetBuilder,
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


# ==================== FormulaTargetBuilder Tests ====================


class TestFormulaTargetBuilder:
    """Тесты для FormulaTargetBuilder (декларативные формулы)."""

    @pytest.fixture
    def df(self) -> pd.DataFrame:
        """Данные для тестирования формул."""
        return pd.DataFrame(
            {
                "pl_points": [5, 3, 7, 4, 6],
                "opp_points": [3, 5, 2, 4, 8],
                "home_points": [5, 3, 7, 4, 6],
                "away_points": [3, 5, 2, 4, 8],
            }
        )

    def test_simple_comparison(self, df: pd.DataFrame) -> None:
        """Простое сравнение двух колонок: pl_points > opp_points."""
        builder = FormulaTargetBuilder("pl_points > opp_points")
        target = builder.compute(df)

        assert len(target) == 5
        assert target.iloc[0] == 1  # 5 > 3
        assert target.iloc[1] == 0  # 3 > 5 → False
        assert target.iloc[2] == 1  # 7 > 2
        assert target.iloc[3] == 0  # 4 > 4 → False (strict)
        assert target.iloc[4] == 0  # 6 > 8 → False

    def test_sum_comparison_with_literal(self, df: pd.DataFrame) -> None:
        """Сумма колонок vs числовой литерал: (pl_points + opp_points) > 6.5."""
        builder = FormulaTargetBuilder("(pl_points + opp_points) > 6.5")
        target = builder.compute(df)

        # Суммы: 8, 8, 9, 8, 14 — все > 6.5
        assert target.sum() == 5

    def test_sum_comparison_with_line_placeholder(self, df: pd.DataFrame) -> None:
        """Подстановка {line}: (pl_points + opp_points) > {line}."""
        builder = FormulaTargetBuilder("(pl_points + opp_points) > {line}", line=9.5)
        target = builder.compute(df)

        # Суммы: 8, 8, 9, 8, 14 → только 14 > 9.5
        assert target.iloc[0] == 0  # 8 <= 9.5
        assert target.iloc[4] == 1  # 14 > 9.5

    def test_difference_comparison(self, df: pd.DataFrame) -> None:
        """Разность колонок: pl_points - opp_points >= 0."""
        builder = FormulaTargetBuilder("pl_points - opp_points >= 0")
        target = builder.compute(df)

        # Разности: 2, -2, 5, 0, -2
        assert target.iloc[0] == 1  # 2 >= 0
        assert target.iloc[1] == 0  # -2 >= 0 → False
        assert target.iloc[3] == 1  # 0 >= 0 → True

    def test_less_than_operator(self, df: pd.DataFrame) -> None:
        """Оператор <: pl_points < opp_points."""
        builder = FormulaTargetBuilder("pl_points < opp_points")
        target = builder.compute(df)

        assert target.iloc[0] == 0  # 5 < 3 → False
        assert target.iloc[1] == 1  # 3 < 5 → True
        assert target.iloc[3] == 0  # 4 < 4 → False (strict)
        assert target.iloc[4] == 1  # 6 < 8 → True

    def test_equality_operator(self, df: pd.DataFrame) -> None:
        """Оператор ==: pl_points == opp_points."""
        builder = FormulaTargetBuilder("pl_points == opp_points")
        target = builder.compute(df)

        assert target.iloc[3] == 1  # 4 == 4
        assert target.iloc[0] == 0  # 5 != 3

    def test_not_equal_operator(self, df: pd.DataFrame) -> None:
        """Оператор !=: pl_points != opp_points."""
        builder = FormulaTargetBuilder("pl_points != opp_points")
        target = builder.compute(df)

        assert target.iloc[3] == 0  # 4 != 4 → False
        assert target.iloc[0] == 1  # 5 != 3 → True

    def test_line_placeholder_missing_raises(self) -> None:
        """Формула с {line} без указания line вызывает ошибку."""
        with pytest.raises(TargetComputationError, match="line не указан"):
            FormulaTargetBuilder("pl_points > {line}")

    def test_invalid_formula_raises(self) -> None:
        """Невалидная формула вызывает ошибку."""
        with pytest.raises(TargetComputationError, match="Невалидная формула"):
            FormulaTargetBuilder("just_a_word")

    def test_missing_column_raises(self, df: pd.DataFrame) -> None:
        """Ссылка на несуществующую колонку вызывает ошибку."""
        builder = FormulaTargetBuilder("nonexistent_col > pl_points")
        with pytest.raises(TargetComputationError, match="Невозможно вычислить"):
            builder.compute(df)

    def test_get_referenced_columns(self, df: pd.DataFrame) -> None:
        """get_referenced_columns возвращает реальные колонки из формулы."""
        builder = FormulaTargetBuilder("pl_points + opp_points > 6.5")
        refs = builder.get_referenced_columns(df)

        assert "pl_points" in refs
        assert "opp_points" in refs
        assert len(refs) == 2

    def test_repr(self) -> None:
        """Проверка __repr__."""
        builder = FormulaTargetBuilder("a > b")
        assert "FormulaTargetBuilder" in repr(builder)
        assert "a > b" in repr(builder)


# ==================== Formula via compute_target_from_market_spec ====================


class TestFormulaIntegration:
    """Интеграционные тесты: формула через compute_target_from_market_spec."""

    def test_formula_in_market_spec(self) -> None:
        """Formula из market_spec.target.formula корректно вычисляется."""
        df = pd.DataFrame(
            {
                "pl_points": [5, 3, 7],
                "opp_points": [3, 5, 2],
            }
        )
        market_spec = DictConfig(
            {
                "name": "winner",
                "market_family": "winner",
                "data_format": "long",
                "side": "home",
                "target": {
                    "name": "target_win",
                    "formula": "pl_points > opp_points",
                    "source_columns": [],
                },
            }
        )

        target = compute_target_from_market_spec(df, market_spec)
        assert target.iloc[0] == 1  # 5 > 3
        assert target.iloc[1] == 0  # 3 > 5 → False
        assert target.iloc[2] == 1  # 7 > 2

    def test_formula_with_line_in_market_spec(self) -> None:
        """Formula с {line} корректно подставляет значение."""
        df = pd.DataFrame(
            {
                "home_points": [5, 3, 7],
                "away_points": [3, 5, 2],
            }
        )
        market_spec = DictConfig(
            {
                "name": "total_over",
                "market_family": "total",
                "data_format": "wide",
                "side": "over",
                "target": {
                    "name": "target_total",
                    "formula": "(home_points + away_points) > {line}",
                    "source_columns": [],
                },
            }
        )

        target = compute_target_from_market_spec(df, market_spec, line=8.5)
        # Суммы: 8, 8, 9 → только 9 > 8.5
        assert target.iloc[0] == 0
        assert target.iloc[1] == 0
        assert target.iloc[2] == 1
