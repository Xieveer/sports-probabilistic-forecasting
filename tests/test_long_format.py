"""
Тесты для трансформации wide ↔ long форматов данных.

Тестируем критическую логику разворота датафрейма для Feature Generation System.
"""

import pandas as pd
import pytest

from sports_forecast.features.long_format import long_to_wide, wide_to_long


class TestWideToLong:
    """Тесты для трансформации wide → long."""

    def test_basic_transformation(self):
        """Базовая трансформация: один матч → две строки."""
        # Arrange
        df = pd.DataFrame(
            {
                "id": [1],
                "datetime": pd.to_datetime(["2024-01-01"]),
                "status": ["finished"],
                "home_name": ["Team A"],
                "away_name": ["Team B"],
                "home_points": [10],
                "away_points": [8],
            }
        )

        # Act
        long = wide_to_long(df, player_id_attr="name")

        # Assert
        assert len(long) == 2, "Один матч должен дать две строки"
        assert list(long["side"].unique()) == ["h", "a"], "Должны быть обе стороны (h, a)"

        # Проверка home строки (side='h')
        home_row = long[long["side"] == "h"].iloc[0]
        assert home_row["is_home"] == 1
        assert home_row["pl_points"] == 10
        assert home_row["opp_points"] == 8

        # Проверка away строки (side='a')
        away_row = long[long["side"] == "a"].iloc[0]
        assert away_row["is_home"] == 0
        assert away_row["pl_points"] == 8  # Для away игрока pl=away
        assert away_row["opp_points"] == 10  # opp=home

    def test_multiple_attributes(self):
        """Трансформация с несколькими атрибутами (points, sets, etc.)."""
        # Arrange
        df = pd.DataFrame(
            {
                "id": [1],
                "datetime": pd.to_datetime(["2024-01-01"]),
                "home_name": ["Player1"],
                "away_name": ["Player2"],
                "home_points": [70],
                "away_points": [65],
                "home_sets": [3],
                "away_sets": [1],
            }
        )

        # Act
        long = wide_to_long(df, player_id_attr="name")

        # Assert
        assert len(long) == 2
        assert "pl_points" in long.columns
        assert "pl_sets" in long.columns
        assert "opp_points" in long.columns
        assert "opp_sets" in long.columns

        # Проверка home строки
        home_row = long[long["side"] == "h"].iloc[0]
        assert home_row["pl_points"] == 70
        assert home_row["pl_sets"] == 3
        assert home_row["opp_points"] == 65
        assert home_row["opp_sets"] == 1

    def test_context_columns_preservation(self):
        """Контекстные колонки должны копироваться в обе строки."""
        # Arrange
        df = pd.DataFrame(
            {
                "id": [1],
                "datetime": pd.to_datetime(["2024-01-01"]),
                "home_name": ["Player1"],

                "away_name": ["Player2"],

                "home_points": [10],
                "away_points": [8],
                "tour_num": [5],
                "weekday": [3],
            }
        )

        # Act
        long = wide_to_long(df, context_columns=["tour_num", "weekday"], player_id_attr="name")

        # Assert
        assert "tour_num" in long.columns
        assert "weekday" in long.columns

        # Обе строки должны иметь одинаковые значения контекста
        assert long["tour_num"].nunique() == 1
        assert long["tour_num"].iloc[0] == 5
        assert long["weekday"].iloc[0] == 3

    def test_player_name_aliases(self):
        """Создание алиасов pl/opp из pl_name/opp_name."""
        # Arrange
        df = pd.DataFrame(
            {
                "id": [1],
                "datetime": pd.to_datetime(["2024-01-01"]),
                "home_name": ["Team A"],
                "away_name": ["Team B"],
                "home_points": [10],
                "away_points": [8],
            }
        )

        # Act
        long = wide_to_long(df, player_id_attr="name")

        # Assert
        assert "pl" in long.columns
        assert "opp" in long.columns

        home_row = long[long["side"] == "h"].iloc[0]
        assert home_row["pl"] == "Team A"
        assert home_row["opp"] == "Team B"

        away_row = long[long["side"] == "a"].iloc[0]
        assert away_row["pl"] == "Team B"
        assert away_row["opp"] == "Team A"

    def test_multiple_matches(self):
        """Трансформация нескольких матчей одновременно."""
        # Arrange
        df = pd.DataFrame(
            {
                "id": [1, 2, 3],
                "datetime": pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]),
                "home_name": ["A", "B", "C"],
                "away_name": ["X", "Y", "Z"],
                "home_points": [10, 12, 8],
                "away_points": [8, 9, 11],
            }
        )

        # Act
        long = wide_to_long(df, player_id_attr="name")

        # Assert
        assert len(long) == 6, "3 матча должны дать 6 строк"
        assert long["id"].nunique() == 3
        assert len(long[long["side"] == "h"]) == 3
        assert len(long[long["side"] == "a"]) == 3

    def test_sorting_by_datetime_and_id(self):
        """Результат должен быть отсортирован по datetime и id."""
        # Arrange
        df = pd.DataFrame(
            {
                "id": [2, 1, 3],
                "datetime": pd.to_datetime(["2024-01-02", "2024-01-01", "2024-01-03"]),
                "home_name": ["P1", "P2", "P3"],
                "away_name": ["P4", "P5", "P6"],
                "home_points": [10, 12, 8],
                "away_points": [8, 9, 11],
            }
        )

        # Act
        long = wide_to_long(df, player_id_attr="name")

        # Assert
        # Должны быть отсортированы по datetime (возрастание), затем по id (убывание)
        dates = long["datetime"].tolist()
        assert dates == sorted(dates), "Должна быть сортировка по datetime"

    def test_custom_prefixes(self):
        """Использование кастомных префиксов для home/away."""
        # Arrange
        df = pd.DataFrame(
            {
                "id": [1],
                "datetime": pd.to_datetime(["2024-01-01"]),
                "h_name": ["Home"],
                "a_name": ["Away"],
                "h_score": [10],
                "a_score": [8],
            }
        )

        # Act
        long = wide_to_long(df, home_prefix="h_", away_prefix="a_", player_id_attr="name")

        # Assert
        assert len(long) == 2
        assert "pl_score" in long.columns
        assert "opp_score" in long.columns

    def test_no_common_columns_raises_error(self):
        """Если нет общих колонок home/away - должна быть ошибка."""
        # Arrange
        df = pd.DataFrame(
            {
                "id": [1],
                "datetime": pd.to_datetime(["2024-01-01"]),
                "home_points": [10],
                "away_score": [8],  # Разные названия: points vs score
            }
        )

        # Act & Assert
        with pytest.raises(ValueError, match="Не найдено общих колонок"):
            wide_to_long(df, player_id_attr="name")

    def test_missing_player_id_attr_raises_error(self):
        """Если player_id_attr не указан - должна быть ошибка."""
        # Arrange
        df = pd.DataFrame(
            {
                "id": [1],
                "datetime": pd.to_datetime(["2024-01-01"]),
                "home_name": ["Player1"],
                "away_name": ["Player2"],
                "home_points": [10],
                "away_points": [8],
            }
        )

        # Act & Assert
        with pytest.raises(ValueError, match="Параметр player_id_attr обязателен"):
            wide_to_long(df)  # НЕ передаём player_id_attr

    def test_player_id_attr_column_not_found_raises_error(self):
        """Если указанный player_id_attr не найден - должна быть ошибка."""
        # Arrange
        df = pd.DataFrame(
            {
                "id": [1],
                "datetime": pd.to_datetime(["2024-01-01"]),
                "home_points": [10],
                "away_points": [8],
            }
        )

        # Act & Assert
        with pytest.raises(ValueError, match="Колонка 'pl_name' не найдена"):
            wide_to_long(df, player_id_attr="name")

    def test_empty_dataframe(self):
        """Пустой датафрейм должен вернуть пустой long формат."""
        # Arrange
        df = pd.DataFrame({"id": [], "datetime": [], "home_name": [], "away_name": [], "home_points": [], "away_points": []})

        # Act
        long = wide_to_long(df, player_id_attr="name")

        # Assert
        assert len(long) == 0
        assert "side" in long.columns
        assert "is_home" in long.columns

    def test_meta_columns_preservation(self):
        """Мета-колонки (id, datetime, status) должны сохраняться."""
        # Arrange
        df = pd.DataFrame(
            {
                "id": [1],
                "datetime": pd.to_datetime(["2024-01-01"]),
                "status": ["finished"],
                "tournament": ["UEL"],
                "home_name": ["Team1"],
                "away_name": ["Team2"],
                "home_points": [10],
                "away_points": [8],
            }
        )

        # Act
        long = wide_to_long(df, player_id_attr="name")

        # Assert
        assert "id" in long.columns
        assert "datetime" in long.columns
        assert "status" in long.columns
        assert "tournament" in long.columns

        # Обе строки имеют одинаковые мета-значения
        assert long["id"].nunique() == 1
        assert long["tournament"].nunique() == 1


class TestLongToWide:
    """Тесты для трансформации long → wide."""

    def test_basic_transformation(self):
        """Базовая трансформация: две строки → один матч."""
        # Arrange
        long = pd.DataFrame(
            {
                "id": [1, 1],
                "datetime": pd.to_datetime(["2024-01-01", "2024-01-01"]),
                "side": ["h", "a"],
                "is_home": [1, 0],
                "pl_points": [10, 8],
                "opp_points": [8, 10],
            }
        )

        # Act
        wide = long_to_wide(long)

        # Assert
        assert len(wide) == 1, "Две строки должны свернуться в один матч"
        assert wide["home_points"].iloc[0] == 10
        assert wide["away_points"].iloc[0] == 8

    def test_multiple_matches(self):
        """Трансформация нескольких матчей одновременно."""
        # Arrange
        long = pd.DataFrame(
            {
                "id": [1, 1, 2, 2],
                "datetime": pd.to_datetime(
                    ["2024-01-01", "2024-01-01", "2024-01-02", "2024-01-02"]
                ),
                "side": ["h", "a", "h", "a"],
                "is_home": [1, 0, 1, 0],
                "pl_points": [10, 8, 12, 9],
                "opp_points": [8, 10, 9, 12],
            }
        )

        # Act
        wide = long_to_wide(long)

        # Assert
        assert len(wide) == 2, "4 строки (2 матча × 2) должны дать 2 строки"

    def test_feature_aggregation(self):
        """Фичи должны агрегироваться с префиксами home_/away_."""
        # Arrange
        long = pd.DataFrame(
            {
                "id": [1, 1],
                "datetime": pd.to_datetime(["2024-01-01", "2024-01-01"]),
                "side": ["h", "a"],
                "is_home": [1, 0],
                "pl_points": [10, 8],
                "opp_points": [8, 10],
                "f_ewm_10": [0.5, 0.3],  # Фича с префиксом f_
            }
        )

        # Act
        wide = long_to_wide(long, aggregate_features=True)

        # Assert
        assert "home_f_ewm_10" in wide.columns
        assert "away_f_ewm_10" in wide.columns
        assert wide["home_f_ewm_10"].iloc[0] == 0.5
        assert wide["away_f_ewm_10"].iloc[0] == 0.3


class TestRoundTrip:
    """Тесты обратимости трансформаций wide ↔ long ↔ wide."""

    def test_wide_to_long_to_wide(self):
        """Wide → Long → Wide должно вернуть исходный датафрейм."""
        # Arrange
        original = pd.DataFrame(
            {
                "id": [1],
                "datetime": pd.to_datetime(["2024-01-01"]),
                "status": ["finished"],
                "home_name": ["Team1"],
                "away_name": ["Team2"],
                "home_points": [10],
                "away_points": [8],
            }
        )

        # Act
        long = wide_to_long(original, player_id_attr="name")
        restored = long_to_wide(long, aggregate_features=False)

        # Assert
        assert len(restored) == len(original)
        assert restored["home_points"].iloc[0] == original["home_points"].iloc[0]
        assert restored["away_points"].iloc[0] == original["away_points"].iloc[0]

    def test_preserves_match_id_uniqueness(self):
        """ID матчей должны оставаться уникальными после round-trip."""
        # Arrange
        original = pd.DataFrame(
            {
                "id": [1, 2, 3],
                "datetime": pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]),
                "home_name": ["A", "B", "C"],
                "away_name": ["X", "Y", "Z"],
                "home_name": ["A", "B", "C"],
                "away_name": ["X", "Y", "Z"],
                "home_points": [10, 12, 8],
                "away_points": [8, 9, 11],
            }
        )

        # Act
        long = wide_to_long(original, player_id_attr="name")
        restored = long_to_wide(long, aggregate_features=False)

        # Assert
        assert len(restored) == len(original)
        assert list(restored["id"].unique()) == [1, 2, 3]
