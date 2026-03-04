"""Тесты для SingleExperimentRunner — новая логика фазы 4.

Покрывают:
- _select_features: приоритет f_ колонок vs fallback
- _save_feature_names: сохранение features.txt на диск
- _evaluate_on_test: ML-метрики на holdout
- _compute_business_metrics: интеграция с BettingSimulator
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
from omegaconf import DictConfig, OmegaConf

from sports_forecast.features.column_utils import FEATURE_PREFIX
from sports_forecast.training.models.dummy import DummyModel
from sports_forecast.training.trainer import SingleExperimentRunner


# ─────────────────────────────────────────────────────────────────────────────
# Фикстуры
# ─────────────────────────────────────────────────────────────────────────────


def _make_cfg(**overrides: Any) -> DictConfig:
    """Создать минимальный конфиг для тестов."""
    base = {
        "tournament": {"name": "test_tournament"},
        "market": {"family": "winner"},
        "market_spec": {
            "name": "winner",
            "data_format": "long",
            "target_name": "target_is_win",
            "market_family": "winner",
            "side": "player",
        },
        "algorithm": {
            "name": "dummy",
            "_target_": "DummyModel",
            "params": {},
        },
        "features": {
            "name": "basic",
            "exclude_cols": ["id", "datetime"],
            "result_cols": ["home_points", "away_points"],
        },
        "split": {"test_size": 0.1, "tscv_n_splits": 2, "time_column": "datetime"},
        "calibration": {"enabled": False},
        "betting": {"enabled": False},
        "seed": 42,
    }
    cfg = OmegaConf.create(base)
    if overrides:
        cfg = OmegaConf.merge(cfg, OmegaConf.create(overrides))
    return cfg


@pytest.fixture
def runner() -> SingleExperimentRunner:
    """Создать SingleExperimentRunner с минимальным конфигом."""
    cfg = _make_cfg()
    return SingleExperimentRunner(cfg, Path("/tmp/test_project"))


@pytest.fixture
def df_with_features() -> pd.DataFrame:
    """DataFrame с f_ фичами (как после FeaturePipeline)."""
    np.random.seed(42)
    n = 100
    return pd.DataFrame(
        {
            "id": range(n),
            "datetime": pd.date_range("2024-01-01", periods=n, freq="h"),
            "home_points": np.random.randint(0, 10, n),
            "away_points": np.random.randint(0, 10, n),
            "f_ewm_10": np.random.randn(n),
            "f_ewm_25": np.random.randn(n),
            "f_count_global": np.random.randint(1, 50, n),
            "f_form_dp": np.random.randint(0, 2, n),
            "tour_num": np.random.randint(1, 5, n),
        }
    )


@pytest.fixture
def df_without_features() -> pd.DataFrame:
    """DataFrame без f_ фичей (fallback mode)."""
    np.random.seed(42)
    n = 100
    return pd.DataFrame(
        {
            "id": range(n),
            "datetime": pd.date_range("2024-01-01", periods=n, freq="h"),
            "home_points": np.random.randint(0, 10, n),
            "away_points": np.random.randint(0, 10, n),
            "tour_num": np.random.randint(1, 5, n),
            "weekday": np.random.randint(0, 7, n),
            "numeric_feat_1": np.random.randn(n),
            "numeric_feat_2": np.random.randn(n),
            "text_col": ["a"] * n,
        }
    )


# ─────────────────────────────────────────────────────────────────────────────
# _select_features
# ─────────────────────────────────────────────────────────────────────────────


class TestSelectFeatures:
    """Тесты для _select_features."""

    def test_prefers_f_prefix_columns(
        self, runner: SingleExperimentRunner, df_with_features: pd.DataFrame
    ) -> None:
        """Выбирает колонки с f_ префиксом, если они есть."""
        features, names = runner._select_features(df_with_features, runner.config)

        # Все выбранные колонки должны начинаться с f_
        for col in names:
            assert col.startswith(FEATURE_PREFIX), f"Колонка '{col}' не имеет префикса f_"

        assert len(names) == 4  # f_ewm_10, f_ewm_25, f_count_global, f_form_dp
        assert "id" not in names
        assert "home_points" not in names

    def test_fallback_to_numeric_when_no_f_prefix(
        self, runner: SingleExperimentRunner, df_without_features: pd.DataFrame
    ) -> None:
        """Fallback к числовым колонкам минус exclude/result."""
        features, names = runner._select_features(df_without_features, runner.config)

        # id и datetime должны быть исключены (exclude_cols)
        assert "id" not in names
        assert "datetime" not in names

        # home_points и away_points должны быть исключены (result_cols)
        assert "home_points" not in names
        assert "away_points" not in names

        # text_col не числовая — не должна быть
        assert "text_col" not in names

        # Числовые колонки (не в exclude/result) должны быть
        assert "tour_num" in names
        assert "weekday" in names
        assert "numeric_feat_1" in names
        assert "numeric_feat_2" in names

    def test_returns_correct_dataframe_shape(
        self, runner: SingleExperimentRunner, df_with_features: pd.DataFrame
    ) -> None:
        """Возвращает DataFrame с правильным количеством строк."""
        features, names = runner._select_features(df_with_features, runner.config)
        assert len(features) == len(df_with_features)
        assert list(features.columns) == names


# ─────────────────────────────────────────────────────────────────────────────
# _save_feature_names
# ─────────────────────────────────────────────────────────────────────────────


class TestSaveFeatureNames:
    """Тесты для _save_feature_names."""

    def test_saves_features_txt(self, runner: SingleExperimentRunner, tmp_path: Path) -> None:
        """Сохраняет features.txt с правильным содержимым."""
        feature_names = ["f_ewm_10", "f_ewm_25", "f_count"]
        runner._save_feature_names(tmp_path, feature_names)

        features_path = tmp_path / "features.txt"
        assert features_path.exists()

        content = features_path.read_text()
        loaded_names = content.strip().split("\n")
        assert loaded_names == feature_names

    def test_overwrites_existing_file(self, runner: SingleExperimentRunner, tmp_path: Path) -> None:
        """Перезаписывает features.txt при повторном вызове."""
        runner._save_feature_names(tmp_path, ["old_feature"])
        runner._save_feature_names(tmp_path, ["new_feature_1", "new_feature_2"])

        content = (tmp_path / "features.txt").read_text()
        loaded_names = content.strip().split("\n")
        assert loaded_names == ["new_feature_1", "new_feature_2"]


# ─────────────────────────────────────────────────────────────────────────────
# _evaluate_on_test
# ─────────────────────────────────────────────────────────────────────────────


class TestEvaluateOnTest:
    """Тесты для _evaluate_on_test."""

    def test_returns_all_metrics(self, runner: SingleExperimentRunner) -> None:
        """Возвращает словарь со всеми ML-метриками включая MCE."""
        np.random.seed(42)
        n = 50
        features = pd.DataFrame(np.random.randn(n, 5), columns=[f"f_{i}" for i in range(5)])
        target = pd.Series(np.random.randint(0, 2, n))

        model = DummyModel()
        model.fit(features, target)

        metrics = runner._evaluate_on_test(model, features, target)

        assert "logloss" in metrics
        assert "auc" in metrics
        assert "accuracy" in metrics
        assert "brier" in metrics
        assert "ece" in metrics
        assert "mce" in metrics

        # Все метрики должны быть числовыми
        for key, value in metrics.items():
            assert isinstance(value, float), f"Метрика '{key}' не float: {type(value)}"

    def test_logloss_positive(self, runner: SingleExperimentRunner) -> None:
        """LogLoss должен быть > 0."""
        np.random.seed(42)
        n = 100
        features = pd.DataFrame(np.random.randn(n, 3), columns=[f"f_{i}" for i in range(3)])
        target = pd.Series(np.random.randint(0, 2, n))

        model = DummyModel()
        model.fit(features, target)

        metrics = runner._evaluate_on_test(model, features, target)
        assert metrics["logloss"] > 0


# ─────────────────────────────────────────────────────────────────────────────
# _compute_business_metrics
# ─────────────────────────────────────────────────────────────────────────────


class TestComputeBusinessMetrics:
    """Тесты для _compute_business_metrics."""

    def test_returns_empty_when_disabled(self) -> None:
        """Возвращает пустой словарь если betting.enabled=false."""
        cfg = _make_cfg(betting={"enabled": False})
        runner = SingleExperimentRunner(cfg, Path("/tmp"))

        np.random.seed(42)
        n = 20
        features = pd.DataFrame(np.random.randn(n, 3), columns=[f"f_{i}" for i in range(3)])
        target = pd.Series(np.random.randint(0, 2, n))
        df = pd.DataFrame({"col": range(n)})

        model = DummyModel()
        model.fit(features, target)

        result = runner._compute_business_metrics(model, features, target, df, cfg)
        assert result == {}

    def test_returns_empty_when_no_odds(self) -> None:
        """Возвращает пустой словарь если odds не найдены."""
        cfg = _make_cfg(betting={"enabled": True, "initial_bankroll": 1000})
        runner = SingleExperimentRunner(cfg, Path("/tmp"))

        np.random.seed(42)
        n = 20
        features = pd.DataFrame(np.random.randn(n, 3), columns=[f"f_{i}" for i in range(3)])
        target = pd.Series(np.random.randint(0, 2, n))
        df = pd.DataFrame({"no_odds_here": range(n)})

        model = DummyModel()
        model.fit(features, target)

        result = runner._compute_business_metrics(model, features, target, df, cfg)
        assert result == {}

    def test_returns_metrics_when_odds_present(self) -> None:
        """Возвращает бизнес-метрики когда odds доступны."""
        cfg = _make_cfg(
            market_spec={
                "name": "winner_home",
                "data_format": "wide",
                "target_name": "target_home_win",
                "market_family": "winner",
                "side": "home",
            },
            betting={
                "enabled": True,
                "initial_bankroll": 1000.0,
                "stake_strategy": "flat",
                "flat_stake": 10.0,
                "min_value_threshold": 0.01,
                "max_stake_fraction": 0.1,
            },
        )
        runner = SingleExperimentRunner(cfg, Path("/tmp"))

        np.random.seed(42)
        n = 50
        features = pd.DataFrame(np.random.randn(n, 3), columns=[f"f_{i}" for i in range(3)])
        target = pd.Series(np.random.randint(0, 2, n))
        df = pd.DataFrame(
            {
                "odds_home_win": np.random.uniform(1.5, 3.0, n),
                "other": range(n),
            }
        )

        model = DummyModel()
        model.fit(features, target)

        result = runner._compute_business_metrics(model, features, target, df, cfg)

        # Core metrics (v2 naming)
        assert "roi" in result
        assert "profit_units" in result
        assert "n_bets" in result
        assert "sharpe_like" in result
        assert "max_drawdown_pct" in result
        assert "odds_column" in result
        assert result["odds_column"] == "odds_home_win"

        # New v2 metrics
        assert "turnover_units" in result
        assert "coverage" in result
        assert "avg_edge" in result
        assert "avg_ev" in result
        assert "ev_sum_units" in result
        assert "ev_realization" in result
        assert "hit_rate" in result
        assert "profit_factor" in result
        assert "std_return_per_bet" in result
        assert "max_drawdown_units" in result

        # Calibration on selected
        assert "cal_selected_brier" in result
        assert "cal_selected_logloss" in result
        assert "cal_selected_ece" in result

        # Odds bins
        assert "odds_bin_metrics" in result
        assert isinstance(result["odds_bin_metrics"], dict)

        # Artifacts
        assert "equity_curve" in result
        assert "sweep_df" in result

    def test_skips_invalid_odds(self) -> None:
        """Пропускает строки с невалидными odds (NaN, <= 1.0)."""
        cfg = _make_cfg(
            market_spec={
                "name": "winner_home",
                "data_format": "wide",
                "target_name": "target_home_win",
                "market_family": "winner",
                "side": "home",
            },
            betting={
                "enabled": True,
                "initial_bankroll": 1000.0,
                "min_value_threshold": 0.01,
            },
        )
        runner = SingleExperimentRunner(cfg, Path("/tmp"))

        np.random.seed(42)
        n = 10
        features = pd.DataFrame(np.random.randn(n, 2), columns=["f_0", "f_1"])
        target = pd.Series(np.random.randint(0, 2, n))

        odds = [2.0, float("nan"), 0.5, 1.0, 2.5, 1.8, float("nan"), 3.0, 2.1, 1.9]
        df = pd.DataFrame({"odds_home_win": odds})

        model = DummyModel()
        model.fit(features, target)

        result = runner._compute_business_metrics(model, features, target, df, cfg)
        # 6 строк имеют валидные odds (> 1.0, не NaN): 2.0, 2.5, 1.8, 3.0, 2.1, 1.9
        assert result["valid_odds_count"] == 6
