"""
Тесты для генераторов фичей (form, ewm, count) и FeaturePipeline.

Покрывают:
- BaseFeatureGenerator: __call__, prefix logic, enabled/disabled
- FormFeatureGenerator: формы игроков (FG, DP, Form)
- EWMFeatureGenerator: EWM в разных контекстах + multi-metric + warmup
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
        "pl_points": np.random.randint(1, 10, n).astype(float),
        "opp_points": np.random.randint(1, 10, n).astype(float),
        "side": ["h" if i % 2 == 0 else "a" for i in range(n)],
    }
    df = pd.DataFrame(data)
    df["diff_ps"] = df["pl_points"] - df["opp_points"]
    df["total_ps"] = df["pl_points"] + df["opp_points"]
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
        assert "f_diff_mins_prev_match" in result.columns

        # match_state — контекстная колонка, НЕ получает f_ префикс
        assert "match_state" in result.columns
        assert "f_match_state" not in result.columns

    def test_match_state_stays_as_context(self, long_df: pd.DataFrame) -> None:
        """match_state и pl_state остаются контекстными колонками (без f_ prefix)."""
        config = {
            "type": "form",
            "enabled": True,
            "fg_trigger_minutes": 480,
            "dp_trigger_minutes": 30,
            "players": ["pl", "opp"],
        }
        gen = FormFeatureGenerator(config)
        result = gen(long_df)

        # Контекстные колонки: доступны для EWM/Count group-by
        assert "match_state" in result.columns
        assert "pl_state" in result.columns
        assert "opp_state" in result.columns
        # Не должны иметь f_ prefix
        assert "f_match_state" not in result.columns
        assert "f_pl_state" not in result.columns

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
        assert "diff_mins_prev_match" in names
        # match_state НЕ в feature_names (контекстная колонка)
        assert "match_state" not in names

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
                    "name": "h2h_global",
                    "keys": ["pl", "opp"],
                    "h2h": True,
                }
            ],
        }
        gen = CountFeatureGenerator(config)
        result = gen(long_df)

        assert "f_h2h_global_count" in result.columns

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
                {"name": "h2h_global", "keys": ["pl", "opp"], "h2h": True},
            ],
        }
        gen = CountFeatureGenerator(config)
        names = gen.get_feature_names()

        assert "pl_global_count" in names
        assert "opp_global_count" in names
        assert "h2h_global_count" in names

    def test_actual_vs_expected_feature_names_count(self, long_df: pd.DataFrame) -> None:
        """get_actual_feature_names(df) исключает пропущенные контексты."""
        config = {
            "type": "count",
            "contexts": [
                {"name": "global", "keys": ["pl"], "players": ["pl", "opp"]},
                {"name": "team", "keys": ["pl", "pl_cteam"], "players": ["pl", "opp"]},
            ],
        }
        gen = CountFeatureGenerator(config)
        expected = gen.get_expected_feature_names()
        actual = gen.get_actual_feature_names(long_df)

        assert "pl_team_count" in expected
        assert "pl_team_count" not in actual
        assert len(actual) < len(expected)
        assert set(actual).issubset(set(expected))


# ==================== EWMFeatureGenerator Tests ====================


class TestEWMFeatureGenerator:
    """Тесты для EWMFeatureGenerator."""

    # ---------- Backward compat (no metric_label) ----------

    def test_backward_compat_no_metric_label(self, long_df: pd.DataFrame) -> None:
        """Без metric_label → старое именование (обратная совместимость)."""
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

        # Old naming: pl_global_ewm_5 (без metric_label)
        assert "f_pl_global_ewm_5" in result.columns
        assert "f_opp_global_ewm_5" in result.columns
        assert "f_all_global_ewm_5_diff" in result.columns

    def test_backward_compat_h2h_no_metric_label(self, long_df: pd.DataFrame) -> None:
        """H2H без metric_label → old naming."""
        config = {
            "type": "ewm",
            "metric": "diff_ps",
            "spans": [5],
            "shift": 1,
            "min_periods": 1,
            "adjust": False,
            "contexts": [
                {
                    "name": "h2h_global",
                    "keys": ["pl", "opp"],
                    "h2h": True,
                }
            ],
        }
        gen = EWMFeatureGenerator(config)
        result = gen(long_df)

        assert "f_h2h_global_ewm_5" in result.columns

    # ---------- New metric_label naming ----------

    def test_metric_label_diff_naming(self, long_df: pd.DataFrame) -> None:
        """metric_label='diff' → pl_global_diff_ewm_5."""
        config = {
            "type": "ewm",
            "metric": "diff_ps",
            "metric_label": "diff",
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

        assert "f_pl_global_diff_ewm_5" in result.columns
        assert "f_opp_global_diff_ewm_5" in result.columns
        assert "f_all_global_diff_ewm_5" in result.columns

    def test_metric_label_total_naming(self, long_df: pd.DataFrame) -> None:
        """metric_label='total' + compute_diff=false → no all_*."""
        config = {
            "type": "ewm",
            "metric": "total_ps",
            "metric_label": "total",
            "spans": [5],
            "shift": 1,
            "min_periods": 1,
            "adjust": False,
            "contexts": [
                {
                    "name": "global",
                    "keys": ["pl"],
                    "players": ["pl", "opp"],
                    "compute_diff": False,
                }
            ],
        }
        gen = EWMFeatureGenerator(config)
        result = gen(long_df)

        assert "f_pl_global_total_ewm_5" in result.columns
        assert "f_opp_global_total_ewm_5" in result.columns
        # compute_diff=false → нет all_*
        assert "f_all_global_total_ewm_5" not in result.columns

    def test_h2h_with_metric_label(self, long_df: pd.DataFrame) -> None:
        """H2H с metric_label → h2h_global_diff_ewm_5."""
        config = {
            "type": "ewm",
            "metric": "diff_ps",
            "metric_label": "diff",
            "spans": [5],
            "shift": 1,
            "min_periods": 1,
            "adjust": False,
            "contexts": [
                {
                    "name": "h2h_global",
                    "keys": ["pl", "opp"],
                    "h2h": True,
                }
            ],
        }
        gen = EWMFeatureGenerator(config)
        result = gen(long_df)

        assert "f_h2h_global_diff_ewm_5" in result.columns

    def test_feature_names_with_metric_label(self) -> None:
        """get_feature_names с metric_label корректен."""
        config = {
            "type": "ewm",
            "metric": "diff_ps",
            "metric_label": "diff",
            "spans": [5, 10],
            "contexts": [
                {
                    "name": "global",
                    "keys": ["pl"],
                    "players": ["pl", "opp"],
                    "compute_diff": True,
                },
                {
                    "name": "h2h_global",
                    "keys": ["pl", "opp"],
                    "h2h": True,
                },
            ],
        }
        gen = EWMFeatureGenerator(config)
        names = gen.get_feature_names()

        assert "pl_global_diff_ewm_5" in names
        assert "opp_global_diff_ewm_5" in names
        assert "all_global_diff_ewm_5" in names
        assert "pl_global_diff_ewm_10" in names
        assert "h2h_global_diff_ewm_5" in names
        assert "h2h_global_diff_ewm_10" in names

    # ---------- Multiple spans ----------

    def test_multiple_spans(self, long_df: pd.DataFrame) -> None:
        """Генерация для нескольких spans."""
        config = {
            "type": "ewm",
            "metric": "diff_ps",
            "metric_label": "diff",
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

        assert "f_pl_global_diff_ewm_5" in result.columns
        assert "f_pl_global_diff_ewm_10" in result.columns

    # ---------- Error handling ----------

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

    def test_missing_context_column_skips(self, long_df: pd.DataFrame) -> None:
        """Контекст с несуществующей колонкой пропускается (soft-fail)."""
        config = {
            "type": "ewm",
            "metric": "diff_ps",
            "metric_label": "diff",
            "spans": [5],
            "shift": 1,
            "min_periods": 1,
            "adjust": False,
            "contexts": [
                {
                    "name": "team",
                    "keys": ["pl", "pl_cteam"],
                    "players": ["pl", "opp"],
                    "compute_diff": True,
                }
            ],
        }
        gen = EWMFeatureGenerator(config)
        result = gen(long_df)

        # pl_cteam не существует → контекст пропущен
        assert "f_pl_team_diff_ewm_5" not in result.columns

    def test_actual_vs_expected_feature_names_ewm(self, long_df: pd.DataFrame) -> None:
        """get_actual_feature_names(df) исключает пропущенные контексты; get_expected — полный список."""
        config = {
            "type": "ewm",
            "metric": "diff_ps",
            "metric_label": "diff",
            "spans": [5],
            "shift": 1,
            "min_periods": 1,
            "adjust": False,
            "contexts": [
                {"name": "global", "keys": ["pl"], "players": ["pl", "opp"], "compute_diff": True},
                {"name": "team", "keys": ["pl", "pl_cteam"], "players": ["pl", "opp"]},
            ],
        }
        gen = EWMFeatureGenerator(config)
        expected = gen.get_expected_feature_names()
        actual = gen.get_actual_feature_names(long_df)

        assert "pl_team_diff_ewm_5" in expected
        assert "pl_team_diff_ewm_5" not in actual
        assert len(actual) < len(expected)
        assert set(actual).issubset(set(expected))

    # ---------- NaN strategy ----------

    def test_cold_start_produces_nan(self) -> None:
        """Первые матчи (< min_periods) дают NaN — не фиктивный 0."""
        df = pd.DataFrame(
            {
                "pl": ["A"] * 5,
                "opp": ["B"] * 5,
                "diff_ps": [3.0, -1.0, 5.0, 2.0, -4.0],
            }
        )
        config = {
            "type": "ewm",
            "metric": "diff_ps",
            "metric_label": "diff",
            "spans": [3],
            "shift": 1,
            "min_periods": 3,
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
        result = gen.generate(df)

        ewm_col = result["pl_global_diff_ewm_3"]
        # Первые 3 строки (shift=1 + min_periods=3): NaN
        assert ewm_col.iloc[0:3].isna().all(), "Cold-start строки должны быть NaN"
        # 4-я строка и далее: есть значение
        assert ewm_col.iloc[3:].notna().all(), "После cold-start должны быть значения"

    def test_upcoming_nan_metric_does_not_affect_ewm(self) -> None:
        """Upcoming-матчи (metric=NaN) не влияют на EWM — ignore_na."""
        df = pd.DataFrame(
            {
                "pl": ["A"] * 6,
                "opp": ["B"] * 6,
                "diff_ps": [3.0, -1.0, 5.0, 2.0, float("nan"), float("nan")],
            }
        )
        config = {
            "type": "ewm",
            "metric": "diff_ps",
            "metric_label": "diff",
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
        result = gen.generate(df)

        ewm_col = result["pl_global_diff_ewm_3"]
        # Строка 4 (shift=1 → видит diff_ps[3]=2.0): имеет EWM значение
        assert pd.notna(ewm_col.iloc[4]), "Строка после finished должна иметь EWM"
        # Строка 5 (shift=1 → видит diff_ps[4]=NaN): EWM carry-forward
        assert pd.notna(ewm_col.iloc[5]), "Upcoming строка: EWM carry-forward"
        # EWM для upcoming = EWM для предыдущей строки (NaN не обновляет)
        assert ewm_col.iloc[4] == ewm_col.iloc[5], (
            "Upcoming NaN не должен менять EWM (carry-forward)"
        )

    def test_no_fillna_zero_in_ewm(self) -> None:
        """EWM не содержит артефактов от fillna(0)."""
        df = pd.DataFrame(
            {
                "pl": ["A"] * 4,
                "opp": ["B"] * 4,
                "diff_ps": [10.0, 12.0, 8.0, 11.0],
            }
        )
        config = {
            "type": "ewm",
            "metric": "diff_ps",
            "metric_label": "diff",
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
        result = gen.generate(df)

        ewm_col = result["pl_global_diff_ewm_3"]
        # Строка 1 (shift=1 → видит diff_ps[0]=10.0): EWM = 10.0
        assert ewm_col.iloc[1] == 10.0, (
            f"Первое EWM должно быть == первому значению, получили: {ewm_col.iloc[1]}"
        )

    # ---------- Warmup ----------

    def test_warmup_feature_values(self) -> None:
        """Warmup-фича: 0→1 по мере накопления матчей."""
        df = pd.DataFrame(
            {
                "pl": ["A"] * 15,
                "opp": ["B"] * 15,
                "diff_ps": list(range(15)),
            }
        )
        config = {
            "type": "ewm",
            "metric": "diff_ps",
            "metric_label": "diff",
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
            "warmup": {"enabled": True, "threshold": 10, "players": ["pl"]},
        }
        gen = EWMFeatureGenerator(config)
        result = gen.generate(df)

        warmup = result["pl_ewm_warmup"]
        assert warmup.iloc[0] == 0.0
        assert warmup.iloc[4] == pytest.approx(0.4)
        assert warmup.iloc[9] == pytest.approx(0.9)
        assert warmup.iloc[10] == 1.0
        assert warmup.iloc[14] == 1.0

    def test_warmup_with_upcoming_nan(self) -> None:
        """Warmup не считает upcoming-матчи (NaN metric) как наблюдения."""
        df = pd.DataFrame(
            {
                "pl": ["A"] * 6,
                "opp": ["B"] * 6,
                "diff_ps": [1.0, 2.0, 3.0, 4.0, float("nan"), float("nan")],
            }
        )
        config = {
            "type": "ewm",
            "metric": "diff_ps",
            "metric_label": "diff",
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
            "warmup": {"enabled": True, "threshold": 10, "players": ["pl"]},
        }
        gen = EWMFeatureGenerator(config)
        result = gen.generate(df)

        warmup = result["pl_ewm_warmup"]
        assert warmup.iloc[3] == pytest.approx(0.3)
        assert warmup.iloc[4] == pytest.approx(0.4)
        # NaN не увеличивает count
        assert warmup.iloc[5] == pytest.approx(0.4)

    def test_feature_names_with_warmup(self) -> None:
        """get_feature_names включает warmup когда enabled=True."""
        config = {
            "type": "ewm",
            "metric": "diff_ps",
            "metric_label": "diff",
            "spans": [5],
            "contexts": [
                {
                    "name": "global",
                    "keys": ["pl"],
                    "players": ["pl"],
                    "compute_diff": False,
                },
            ],
            "warmup": {"enabled": True, "threshold": 10, "players": ["pl", "opp"]},
        }
        gen = EWMFeatureGenerator(config)
        names = gen.get_feature_names()

        assert "pl_ewm_warmup" in names
        assert "opp_ewm_warmup" in names

    # ---------- Total metric ----------

    def test_total_ewm_values_are_positive(self, long_df: pd.DataFrame) -> None:
        """EWM по total_ps > 0 (сумма очков всегда положительная)."""
        config = {
            "type": "ewm",
            "metric": "total_ps",
            "metric_label": "total",
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
        result = gen.generate(long_df)

        ewm_total = result["pl_global_total_ewm_5"].dropna()
        assert (ewm_total > 0).all(), "EWM по total_ps должен быть > 0"


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
                "ewm_diff": {
                    "type": "ewm",
                    "enabled": True,
                    "metric": "diff_ps",
                    "metric_label": "diff",
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
            "create_metrics": ["diff", "total"],
        }
        pipeline = FeaturePipeline(config)
        result_df, feature_names = pipeline.generate_features(long_df, format="long")

        assert len(feature_names) > 0
        assert "f_pl_is_dp" in result_df.columns
        assert "f_pl_global_diff_ewm_5" in result_df.columns

    def test_multi_metric_pipeline(self, long_df: pd.DataFrame) -> None:
        """Pipeline с двумя EWM генераторами (diff + total)."""
        config = {
            "generators": {
                "ewm_diff": {
                    "type": "ewm",
                    "enabled": True,
                    "metric": "diff_ps",
                    "metric_label": "diff",
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
                        },
                        {
                            "name": "h2h_global",
                            "keys": ["pl", "opp"],
                            "h2h": True,
                        },
                    ],
                },
                "ewm_total": {
                    "type": "ewm",
                    "enabled": True,
                    "metric": "total_ps",
                    "metric_label": "total",
                    "spans": [5],
                    "shift": 1,
                    "min_periods": 1,
                    "adjust": False,
                    "contexts": [
                        {
                            "name": "global",
                            "keys": ["pl"],
                            "players": ["pl", "opp"],
                            "compute_diff": False,
                        },
                        {
                            "name": "h2h_global",
                            "keys": ["pl", "opp"],
                            "h2h": True,
                        },
                    ],
                },
            },
            "requires_long": False,
            "create_metrics": ["diff", "total"],
        }
        pipeline = FeaturePipeline(config)
        result_df, feature_names = pipeline.generate_features(long_df, format="long")

        # diff features
        assert "f_pl_global_diff_ewm_5" in result_df.columns
        assert "f_opp_global_diff_ewm_5" in result_df.columns
        assert "f_all_global_diff_ewm_5" in result_df.columns
        assert "f_h2h_global_diff_ewm_5" in result_df.columns

        # total features
        assert "f_pl_global_total_ewm_5" in result_df.columns
        assert "f_opp_global_total_ewm_5" in result_df.columns
        assert "f_h2h_global_total_ewm_5" in result_df.columns

        # no diff for total (compute_diff=false)
        assert "f_all_global_total_ewm_5" not in result_df.columns

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
