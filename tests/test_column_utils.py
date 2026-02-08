"""
Тесты для модуля column_utils.

Покрывают:
- get_feature_columns / get_meta_columns / get_target_columns / get_source_columns
- add/remove_feature_prefix, add/remove_target_prefix
- filter_feature_columns / exclude_feature_columns
- validate_required_columns
"""

from __future__ import annotations

import pandas as pd
import pytest

from sports_forecast.features.column_utils import (
    FEATURE_PREFIX,
    META_COLUMNS,
    TARGET_PREFIX,
    add_feature_prefix,
    add_target_prefix,
    exclude_feature_columns,
    filter_feature_columns,
    get_feature_columns,
    get_meta_columns,
    get_source_columns,
    get_target_columns,
    remove_feature_prefix,
    remove_target_prefix,
    validate_required_columns,
)


# ==================== Fixtures ====================


@pytest.fixture
def mixed_df() -> pd.DataFrame:
    """Датафрейм с колонками всех категорий."""
    return pd.DataFrame(
        {
            # Meta
            "id": [1, 2],
            "datetime": ["2024-01-01", "2024-01-02"],
            "pl": ["player1", "player2"],
            # Source
            "home_points": [10, 12],
            "away_points": [8, 9],
            "tour_num": [1, 2],
            # Features
            "f_ewm_10": [0.5, 0.6],
            "f_count_global": [3, 5],
            "f_form_score": [1.2, -0.3],
            # Targets
            "target_home_win": [1, 1],
            "target_total_over_6_5": [0, 1],
        }
    )


# ==================== get_*_columns Tests ====================


class TestGetColumns:
    """Тесты для функций получения колонок по категориям."""

    def test_get_feature_columns(self, mixed_df: pd.DataFrame) -> None:
        """Только колонки с префиксом f_."""
        features = get_feature_columns(mixed_df)
        assert features == ["f_ewm_10", "f_count_global", "f_form_score"]

    def test_get_meta_columns(self, mixed_df: pd.DataFrame) -> None:
        """Мета-колонки из глобального списка META_COLUMNS."""
        meta = get_meta_columns(mixed_df)
        assert "id" in meta
        assert "datetime" in meta
        assert "pl" in meta
        assert len(meta) == 3

    def test_get_target_columns(self, mixed_df: pd.DataFrame) -> None:
        """Колонки с префиксом target_."""
        targets = get_target_columns(mixed_df)
        assert targets == ["target_home_win", "target_total_over_6_5"]

    def test_get_source_columns(self, mixed_df: pd.DataFrame) -> None:
        """Source: не meta, не feature, не target."""
        sources = get_source_columns(mixed_df)
        assert "home_points" in sources
        assert "away_points" in sources
        assert "tour_num" in sources
        assert len(sources) == 3

    def test_get_feature_columns_empty_df(self) -> None:
        """Пустой датафрейм — пустой список."""
        df = pd.DataFrame({"id": [1], "home_points": [10]})
        assert get_feature_columns(df) == []

    def test_get_target_columns_empty_df(self) -> None:
        """Без таргетов — пустой список."""
        df = pd.DataFrame({"id": [1], "f_feat": [0.5]})
        assert get_target_columns(df) == []


# ==================== Prefix Tests ====================


class TestPrefixes:
    """Тесты для add/remove prefix функций."""

    def test_add_feature_prefix(self) -> None:
        """Добавление префикса f_."""
        assert add_feature_prefix("ewm_10") == "f_ewm_10"

    def test_add_feature_prefix_idempotent(self) -> None:
        """Повторное добавление не дублирует префикс."""
        assert add_feature_prefix("f_ewm_10") == "f_ewm_10"

    def test_remove_feature_prefix(self) -> None:
        """Удаление префикса f_."""
        assert remove_feature_prefix("f_ewm_10") == "ewm_10"

    def test_remove_feature_prefix_no_prefix(self) -> None:
        """Без префикса — строка без изменений."""
        assert remove_feature_prefix("ewm_10") == "ewm_10"

    def test_add_target_prefix(self) -> None:
        """Добавление префикса target_."""
        assert add_target_prefix("home_win") == "target_home_win"

    def test_add_target_prefix_idempotent(self) -> None:
        """Повторное добавление не дублирует."""
        assert add_target_prefix("target_home_win") == "target_home_win"

    def test_remove_target_prefix(self) -> None:
        """Удаление префикса target_."""
        assert remove_target_prefix("target_home_win") == "home_win"

    def test_remove_target_prefix_no_prefix(self) -> None:
        """Без префикса — без изменений."""
        assert remove_target_prefix("home_win") == "home_win"


# ==================== Filter/Exclude Tests ====================


class TestFilterExclude:
    """Тесты filter_feature_columns и exclude_feature_columns."""

    def test_filter_feature_columns(self, mixed_df: pd.DataFrame) -> None:
        """Только фичи в результирующем датафрейме."""
        result = filter_feature_columns(mixed_df)
        assert list(result.columns) == ["f_ewm_10", "f_count_global", "f_form_score"]
        assert len(result) == len(mixed_df)

    def test_exclude_feature_columns(self, mixed_df: pd.DataFrame) -> None:
        """Датафрейм без фичей."""
        result = exclude_feature_columns(mixed_df)
        for col in result.columns:
            assert not col.startswith(FEATURE_PREFIX)
        assert "id" in result.columns
        assert "home_points" in result.columns
        assert "target_home_win" in result.columns


# ==================== validate_required_columns Tests ====================


class TestValidateRequiredColumns:
    """Тесты для validate_required_columns."""

    def test_all_present(self, mixed_df: pd.DataFrame) -> None:
        """Все требуемые колонки есть — без ошибок."""
        validate_required_columns(mixed_df, ["id", "datetime", "home_points"])

    def test_missing_column_raises(self, mixed_df: pd.DataFrame) -> None:
        """Отсутствующая колонка — ValueError."""
        with pytest.raises(ValueError, match="Отсутствуют обязательные колонки.*missing_col"):
            validate_required_columns(mixed_df, ["id", "missing_col"])

    def test_empty_required_list(self, mixed_df: pd.DataFrame) -> None:
        """Пустой список обязательных — без ошибок."""
        validate_required_columns(mixed_df, [])


# ==================== Constants Tests ====================


class TestConstants:
    """Тесты для констант модуля."""

    def test_feature_prefix(self) -> None:
        """FEATURE_PREFIX = 'f_'."""
        assert FEATURE_PREFIX == "f_"

    def test_target_prefix(self) -> None:
        """TARGET_PREFIX = 'target_'."""
        assert TARGET_PREFIX == "target_"

    def test_meta_columns_contains_core(self) -> None:
        """META_COLUMNS содержит ключевые системные колонки."""
        assert "id" in META_COLUMNS
        assert "datetime" in META_COLUMNS
        assert "tournament" in META_COLUMNS
        assert "pl" in META_COLUMNS
        assert "opp" in META_COLUMNS
        assert "side" in META_COLUMNS
