"""
Тесты для генераторов фичей (form, ewm, count) и FeaturePipeline.

Покрывают:
- BaseFeatureGenerator: __call__, prefix logic, enabled/disabled
- FormFeatureGenerator: формы игроков (FG, DP, Form)
- EWMFeatureGenerator: EWM в разных контекстах
- CountFeatureGenerator: подсчёт встреч в контексте
- FeaturePipeline: инициализация из dict и list конфигов
- Обработка ошибок: отсутствующие колонки, невалидные конфиги
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from sports_forecast.features.generators.count_generator import CountFeatureGenerator
from sports_forecast.features.generators.ewm_generator import EWMFeatureGenerator
from sports_forecast.features.generators.form_generator import FormFeatureGenerator
from sports_forecast.features.pipeline import FeaturePipeline


# ==================== Fixtures ====================


@pytest.fixture
def long_df() -> pd.DataFrame:
    """Long-format датафрейм для тестирования генераторов."""
    np.random.seed(42)
    n = 20

    players = ["Alice", "Bob", "Charlie", "Dave"]
    data = {
        "id": list(range(n)),
        "datetime": pd.date_range("2024-01-01", periods=n, freq="30min"),
        "pl": [players[i % len(players)] for i in range(n)],
        "opp": [players[(i + 1) % len(players)] for i in range(n)],
        "pl_points": np.random.randint(1, 10, n),
        "opp_points": np.random.randint(1, 10, n),
        "side": ["h" if i % 2 == 0 else "a" for i in range(n)],
    }
    df = pd.DataFrame(data)
    df["diff_ps"] = df["pl_points"] - df["opp_points"]
    return df


# ==================== FormFeatureGenerator Tests ====================


class TestFormFeatureGenerator:
    """Тесты для FormFeatureGenerator."""

    def test_generates_form_features(self, long_df: pd.DataFrame) -> None:
        """Генерирует все ожидаемые фичи формы."""
        config = {
            "type": "form",
            "enabled": True,
            "fg_trigger_minutes": 480,
            "dp_trigger_minutes": 30,
            "players": ["pl", "opp"],
        }
        gen = FormFeatureGenerator(config)
        result = gen(long_df)

        # Проверяем наличие фичей (с префиксом f_)
        assert "f_pl_mins_prev_match" in result.columns
        assert "f_pl_is_dp" in result.columns
        assert "f_pl_is_fg" in result.columns
        assert "f_pl_is_form" in result.columns
        assert "f_opp_mins_prev_match" in result.columns
        assert "f_match_state" in result.columns
        assert "f_diff_mins_prev_match" in result.columns

    def test_dp_fg_form_mutually_exclusive(self, long_df: pd.DataFrame) -> None:
        """DP, FG, Form взаимоисключающи для каждого игрока."""
        config = {
            "type": "form",
            "enabled": True,
            "fg_trigger_minutes": 480,
            "dp_trigger_minutes": 30,
            "players": ["pl"],
        }
        gen = FormFeatureGenerator(config)
        result = gen.generate(long_df)

        # Для каждой строки: ровно одно из (is_dp, is_fg, is_form) = 1
        total = result["pl_is_dp"] + result["pl_is_fg"] + result["pl_is_form"]
        assert (total == 1).all(), "DP + FG + Form должны = 1 для каждой строки"

    def test_disabled_generator_returns_original(self, long_df: pd.DataFrame) -> None:
        """Отключённый генератор возвращает исходный датафрейм."""
        config = {
            "type": "form",
            "enabled": False,
            "players": ["pl"],
        }
        gen = FormFeatureGenerator(config)
        result = gen(long_df)

        assert list(result.columns) == list(long_df.columns)

    def test_missing_datetime_raises(self) -> None:
        """Отсутствие datetime вызывает ValueError."""
        df = pd.DataFrame({"pl": ["A"], "opp": ["B"]})
        config = {"type": "form", "players": ["pl"]}
        gen = FormFeatureGenerator(config)

        with pytest.raises(ValueError, match="обязательные колонки"):
            gen.generate(df)

    def test_feature_names_list(self) -> None:
        """get_feature_names возвращает корректный список."""
        config = {"type": "form", "players": ["pl", "opp"]}
        gen = FormFeatureGenerator(config)
        names = gen.get_feature_names()

        assert "pl_mins_prev_match" in names
        assert "pl_is_dp" in names
        assert "match_state" in names
        assert "diff_mins_prev_match" in names

    def test_prefixed_feature_names(self) -> None:
        """get_prefixed_feature_names добавляет f_ ко всем именам."""
        config = {"type": "form", "players": ["pl"]}
        gen = FormFeatureGenerator(config)
        prefixed = gen.get_prefixed_feature_names()

        for name in prefixed:
            assert name.startswith("f_")

    def test_no_prefix_mode(self, long_df: pd.DataFrame) -> None:
        """add_prefix=False не добавляет f_ к колонкам."""
        config = {
            "type": "form",
            "enabled": True,
            "add_prefix": False,
            "players": ["pl"],
        }
        gen = FormFeatureGenerator(config)
        result = gen(long_df)

        assert "pl_mins_prev_match" in result.columns
        assert "f_pl_mins_prev_match" not in result.columns


# ==================== CountFeatureGenerator Tests ====================


class TestCountFeatureGenerator:
    """Тесты для CountFeatureGenerator."""

    def test_generates_global_count(self, long_df: pd.DataFrame) -> None:
        """Генерирует глобальный count для игроков."""
        config = {
            "type": "count",
            "shift": 1,
            "contexts": [
                {
                    "name": "global",
                    "keys": ["pl"],
                    "players": ["pl", "opp"],
                }
            ],
        }
        gen = CountFeatureGenerator(config)
        result = gen(long_df)

        assert "f_pl_global_count" in result.columns
        assert "f_opp_global_count" in result.columns

    def test_h2h_count(self, long_df: pd.DataFrame) -> None:
        """Head-to-head count."""
        config = {
            "type": "count",
            "shift": 1,
            "contexts": [
                {
                    "name": "h2h",
                    "keys": ["pl", "opp"],
                    "h2h": True,
                }
            ],
        }
        gen = CountFeatureGenerator(config)
        result = gen(long_df)

        assert "f_h2h_count" in result.columns

    def test_count_starts_at_zero_with_shift(self, long_df: pd.DataFrame) -> None:
        """С shift=1 первый матч каждого игрока = 0."""
        config = {
            "type": "count",
            "shift": 1,
            "contexts": [
                {
                    "name": "global",
                    "keys": ["pl"],
                    "players": ["pl"],
                }
            ],
        }
        gen = CountFeatureGenerator(config)
        result = gen.generate(long_df)

        # Для каждого уникального игрока его первый count = 0
        for player in long_df["pl"].unique():
            mask = result["pl"] == player
            first_count = result.loc[mask, "pl_global_count"].iloc[0]
            assert first_count == 0, f"Первый count для {player} должен быть 0 (shift=1)"

    def test_missing_context_field_raises(self) -> None:
        """Отсутствие обязательного поля в context вызывает ошибку."""
        config = {
            "type": "count",
            "contexts": [
                {"name": "test"}  # Нет 'keys'
            ],
        }
        with pytest.raises(ValueError, match="keys"):
            CountFeatureGenerator(config)

    def test_empty_contexts_raises(self) -> None:
        """Пустой contexts вызывает ошибку."""
        config = {"type": "count", "contexts": []}
        with pytest.raises(ValueError, match="непустым списком"):
            CountFeatureGenerator(config)

    def test_missing_column_skips(self, long_df: pd.DataFrame) -> None:
        """Контекст с несуществующей колонкой пропускается (warning)."""
        config = {
            "type": "count",
            "shift": 1,
            "contexts": [
                {
                    "name": "nonexistent",
                    "keys": ["nonexistent_col"],
                    "players": ["pl"],
                }
            ],
        }
        gen = CountFeatureGenerator(config)
        result = gen(long_df)
        # Колонка не должна быть создана (пропущена с warning)
        assert "f_pl_nonexistent_count" not in result.columns

    def test_feature_names(self) -> None:
        """get_feature_names возвращает корректные имена."""
        config = {
            "type": "count",
            "contexts": [
                {"name": "global", "keys": ["pl"], "players": ["pl", "opp"]},
                {"name": "h2h", "keys": ["pl", "opp"], "h2h": True},
            ],
        }
        gen = CountFeatureGenerator(config)
        names = gen.get_feature_names()

        assert "pl_global_count" in names
        assert "opp_global_count" in names
        assert "h2h_count" in names


# ==================== EWMFeatureGenerator Tests ====================


class TestEWMFeatureGenerator:
    """Тесты для EWMFeatureGenerator."""

    def test_generates_global_ewm(self, long_df: pd.DataFrame) -> None:
        """Генерирует глобальный EWM для игроков."""
        config = {
            "type": "ewm",
            "metric": "diff_ps",
            "spans": [5],
            "shift": 1,
            "min_periods": 1,
            "adjust": False,
            "contexts": [
                {
                    "name": "global",
                    "keys": ["pl"],
                    "players": ["pl", "opp"],
                    "compute_diff": True,
                }
            ],
        }
        gen = EWMFeatureGenerator(config)
        result = gen(long_df)

        assert "f_pl_global_ewm_5" in result.columns
        assert "f_opp_global_ewm_5" in result.columns
        assert "f_all_global_ewm_5_diff" in result.columns

    def test_h2h_ewm(self, long_df: pd.DataFrame) -> None:
        """Head-to-head EWM с суффиксом _diff."""
        config = {
            "type": "ewm",
            "metric": "diff_ps",
            "spans": [5],
            "shift": 1,
            "min_periods": 1,
            "adjust": False,
            "contexts": [
                {
                    "name": "h2h",
                    "keys": ["pl", "opp"],
                    "h2h": True,
                    "output_suffix": "_diff",
                }
            ],
        }
        gen = EWMFeatureGenerator(config)
        result = gen(long_df)

        assert "f_h2h_ewm_5_diff" in result.columns

    def test_multiple_spans(self, long_df: pd.DataFrame) -> None:
        """Генерация для нескольких spans."""
        config = {
            "type": "ewm",
            "metric": "diff_ps",
            "spans": [5, 10],
            "shift": 1,
            "min_periods": 1,
            "adjust": False,
            "contexts": [
                {
                    "name": "global",
                    "keys": ["pl"],
                    "players": ["pl"],
                    "compute_diff": False,
                }
            ],
        }
        gen = EWMFeatureGenerator(config)
        result = gen(long_df)

        assert "f_pl_global_ewm_5" in result.columns
        assert "f_pl_global_ewm_10" in result.columns

    def test_missing_metric_raises(self, long_df: pd.DataFrame) -> None:
        """Отсутствие metric колонки вызывает ValueError."""
        config = {
            "type": "ewm",
            "metric": "nonexistent_metric",
            "spans": [5],
            "shift": 1,
            "min_periods": 1,
            "adjust": False,
            "contexts": [
                {
                    "name": "global",
                    "keys": ["pl"],
                    "players": ["pl"],
                    "compute_diff": False,
                }
            ],
        }
        gen = EWMFeatureGenerator(config)
        with pytest.raises(ValueError, match="nonexistent_metric"):
            gen.generate(long_df)

    def test_missing_spans_raises(self) -> None:
        """Конфиг без spans вызывает ошибку при инициализации."""
        config = {
            "type": "ewm",
            "metric": "diff_ps",
            "contexts": [{"name": "global", "keys": ["pl"]}],
        }
        with pytest.raises(ValueError, match="spans"):
            EWMFeatureGenerator(config)

    def test_feature_names(self) -> None:
        """get_feature_names корректен для разных contexts."""
        config = {
            "type": "ewm",
            "metric": "diff_ps",
            "spans": [5, 10],
            "contexts": [
                {
                    "name": "global",
                    "keys": ["pl"],
                    "players": ["pl", "opp"],
                    "compute_diff": True,
                },
                {
                    "name": "h2h",
                    "keys": ["pl", "opp"],
                    "h2h": True,
                    "output_suffix": "_diff",
                },
            ],
        }
        gen = EWMFeatureGenerator(config)
        names = gen.get_feature_names()

        # Global: pl, opp, diff для каждого span
        assert "pl_global_ewm_5" in names
        assert "opp_global_ewm_5" in names
        assert "all_global_ewm_5_diff" in names
        assert "pl_global_ewm_10" in names
        # H2H: один на span
        assert "h2h_ewm_5_diff" in names
        assert "h2h_ewm_10_diff" in names

    def test_ewm_values_not_all_nan(self, long_df: pd.DataFrame) -> None:
        """EWM значения не все NaN (минимум некоторые заполнены)."""
        config = {
            "type": "ewm",
            "metric": "diff_ps",
            "spans": [3],
            "shift": 1,
            "min_periods": 1,
            "adjust": False,
            "contexts": [
                {
                    "name": "global",
                    "keys": ["pl"],
                    "players": ["pl"],
                    "compute_diff": False,
                }
            ],
        }
        gen = EWMFeatureGenerator(config)
        result = gen.generate(long_df)

        assert not result["pl_global_ewm_3"].isna().all(), "Все EWM значения NaN!"


# ==================== Base Generator Tests ====================


class TestBaseGenerator:
    """Тесты общего поведения BaseFeatureGenerator через конкретные генераторы."""

    def test_missing_type_raises(self) -> None:
        """Конфиг без type вызывает ValueError."""
        config = {"enabled": True, "players": ["pl"]}
        with pytest.raises(ValueError, match="type"):
            FormFeatureGenerator(config)

    def test_repr(self) -> None:
        """__repr__ содержит имя и статус."""
        config = {"type": "form", "enabled": True, "players": ["pl"]}
        gen = FormFeatureGenerator(config)

        repr_str = repr(gen)
        assert "FormFeatureGenerator" in repr_str
        assert "enabled" in repr_str

    def test_repr_disabled(self) -> None:
        """__repr__ показывает disabled."""
        config = {"type": "form", "enabled": False, "players": ["pl"]}
        gen = FormFeatureGenerator(config)

        assert "disabled" in repr(gen)

    def test_callable_interface(self, long_df: pd.DataFrame) -> None:
        """Генератор можно вызывать как функцию: gen(df)."""
        config = {"type": "form", "enabled": True, "players": ["pl"]}
        gen = FormFeatureGenerator(config)

        # __call__ должен работать
        result = gen(long_df)
        assert isinstance(result, pd.DataFrame)
        assert len(result) == len(long_df)


# ==================== FeaturePipeline Tests ====================


class TestFeaturePipelineDictFormat:
    """Тесты для FeaturePipeline с dict-форматом generators (новый формат)."""

    def test_dict_format_initializes_generators(self) -> None:
        """Pipeline корректно инициализируется из dict-формата generators."""
        config = {
            "generators": {
                "form": {
                    "type": "form",
                    "enabled": True,
                    "fg_trigger_minutes": 480,
                    "dp_trigger_minutes": 30,
                    "players": ["pl", "opp"],
                },
                "count": {
                    "type": "count",
                    "enabled": True,
                    "shift": 1,
                    "contexts": [
                        {"name": "global", "keys": ["pl"], "players": ["pl", "opp"]},
                    ],
                },
            },
            "requires_long": False,
        }
        pipeline = FeaturePipeline(config)
        assert len(pipeline.generators) == 2

    def test_dict_format_type_from_key(self) -> None:
        """Если type не указан, используется ключ словаря."""
        config = {
            "generators": {
                "form": {
                    # type не указан — берём из ключа "form"
                    "enabled": True,
                    "fg_trigger_minutes": 480,
                    "dp_trigger_minutes": 30,
                    "players": ["pl"],
                },
            },
            "requires_long": False,
        }
        pipeline = FeaturePipeline(config)
        assert len(pipeline.generators) == 1
        assert pipeline.generators[0].config["type"] == "form"

    def test_dict_format_disabled_generator_skipped(self) -> None:
        """Отключённый генератор в dict-формате пропускается."""
        config = {
            "generators": {
                "form": {
                    "type": "form",
                    "enabled": False,
                    "players": ["pl"],
                },
                "count": {
                    "type": "count",
                    "enabled": True,
                    "shift": 1,
                    "contexts": [
                        {"name": "global", "keys": ["pl"], "players": ["pl"]},
                    ],
                },
            },
            "requires_long": False,
        }
        pipeline = FeaturePipeline(config)
        assert len(pipeline.generators) == 1

    def test_dict_format_generates_features(self, long_df: pd.DataFrame) -> None:
        """Pipeline с dict-форматом генерирует фичи."""
        config = {
            "generators": {
                "form": {
                    "type": "form",
                    "enabled": True,
                    "fg_trigger_minutes": 480,
                    "dp_trigger_minutes": 30,
                    "players": ["pl", "opp"],
                },
                "ewm": {
                    "type": "ewm",
                    "enabled": True,
                    "metric": "diff_ps",
                    "spans": [5],
                    "shift": 1,
                    "min_periods": 1,
                    "adjust": False,
                    "contexts": [
                        {
                            "name": "global",
                            "keys": ["pl"],
                            "players": ["pl"],
                            "compute_diff": False,
                        }
                    ],
                },
            },
            "requires_long": False,
            "create_metrics": ["diff"],
        }
        pipeline = FeaturePipeline(config)
        result_df, feature_names = pipeline.generate_features(long_df, format="long")

        assert len(feature_names) > 0
        assert "f_pl_is_dp" in result_df.columns
        assert "f_pl_global_ewm_5" in result_df.columns

    def test_unknown_generator_type_skipped(self) -> None:
        """Неизвестный тип генератора пропускается с warning."""
        config = {
            "generators": {
                "unknown_gen": {
                    "type": "nonexistent_type",
                    "enabled": True,
                },
            },
            "requires_long": False,
        }
        pipeline = FeaturePipeline(config)
        assert len(pipeline.generators) == 0


class TestFeaturePipelineLegacyFormat:
    """Тесты для FeaturePipeline с list-форматом generators (legacy)."""

    def test_list_format_still_works(self) -> None:
        """Pipeline по-прежнему работает с list-форматом generators."""
        config = {
            "generators": [
                {
                    "type": "form",
                    "enabled": True,
                    "fg_trigger_minutes": 480,
                    "dp_trigger_minutes": 30,
                    "players": ["pl"],
                },
                {
                    "type": "count",
                    "enabled": True,
                    "shift": 1,
                    "contexts": [
                        {"name": "global", "keys": ["pl"], "players": ["pl"]},
                    ],
                },
            ],
            "requires_long": False,
        }
        pipeline = FeaturePipeline(config)
        assert len(pipeline.generators) == 2

    def test_missing_generators_raises(self) -> None:
        """Отсутствие generators вызывает ValueError."""
        config = {"requires_long": False}
        with pytest.raises(ValueError, match="generators"):
            FeaturePipeline(config)
