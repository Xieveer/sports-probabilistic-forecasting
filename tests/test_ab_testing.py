"""Тесты для A/B Testing модуля."""

from __future__ import annotations

import numpy as np
import pytest

from sports_forecast.monitoring.ab_testing import (
    ABTestResult,
    ModelComparator,
    _compute_model_metrics,
)


class TestComputeModelMetrics:
    """Тесты для _compute_model_metrics."""

    def test_perfect_predictions(self) -> None:
        """Идеальные предсказания → AUC=1, LogLoss≈0."""
        y_true = np.array([1, 0, 1, 0, 1])
        y_pred = np.array([0.99, 0.01, 0.99, 0.01, 0.99])

        metrics = _compute_model_metrics(y_true, y_pred)

        assert metrics["auc"] == pytest.approx(1.0, abs=0.01)
        assert metrics["logloss"] < 0.1
        assert metrics["accuracy"] == 1.0

    def test_random_predictions(self) -> None:
        """Случайные предсказания → AUC≈0.5."""
        rng = np.random.RandomState(42)
        y_true = rng.randint(0, 2, 200)
        y_pred = rng.uniform(0.3, 0.7, 200)

        metrics = _compute_model_metrics(y_true, y_pred)

        assert 0.4 <= metrics["auc"] <= 0.7
        assert metrics["logloss"] > 0.5

    def test_returns_all_keys(self) -> None:
        """Возвращает все ожидаемые ключи."""
        y_true = np.array([1, 0])
        y_pred = np.array([0.8, 0.2])

        metrics = _compute_model_metrics(y_true, y_pred)

        assert "logloss" in metrics
        assert "auc" in metrics
        assert "brier" in metrics
        assert "accuracy" in metrics


class TestModelComparator:
    """Тесты для ModelComparator."""

    @pytest.fixture
    def comparator(self) -> ModelComparator:
        """Стандартный comparator."""
        return ModelComparator(
            tournament="uel_kz_1",
            market_spec="winner",
            primary_metric="logloss",
            direction="minimize",
            min_improvement_pct=5.0,
            min_samples=10,
        )

    def test_shadow_better_promotes(self, comparator: ModelComparator) -> None:
        """Shadow лучше на 10%+ → рекомендация PROMOTE."""
        rng = np.random.RandomState(42)
        n = 200
        y_true = rng.randint(0, 2, n)

        # Prod: средние предсказания
        prod_preds = np.clip(y_true + rng.randn(n) * 0.5, 0.05, 0.95)
        # Shadow: более точные
        shadow_preds = np.clip(y_true + rng.randn(n) * 0.2, 0.05, 0.95)

        result = comparator.compare_predictions(y_true, prod_preds, shadow_preds)

        assert isinstance(result, ABTestResult)
        assert result.n_common_matches == n
        assert result.shadow_value < result.prod_value  # Меньше LogLoss = лучше
        assert result.should_promote_shadow

    def test_prod_better_keeps(self, comparator: ModelComparator) -> None:
        """Prod лучше → рекомендация KEEP."""
        rng = np.random.RandomState(42)
        n = 200
        y_true = rng.randint(0, 2, n)

        # Prod: точные
        prod_preds = np.clip(y_true + rng.randn(n) * 0.2, 0.05, 0.95)
        # Shadow: хуже
        shadow_preds = np.clip(y_true + rng.randn(n) * 0.5, 0.05, 0.95)

        result = comparator.compare_predictions(y_true, prod_preds, shadow_preds)

        assert not result.should_promote_shadow

    def test_insufficient_data(self) -> None:
        """Мало данных → не промотируем."""
        comparator = ModelComparator(min_samples=100)
        y_true = np.array([1, 0, 1])
        prod_preds = np.array([0.8, 0.2, 0.7])
        shadow_preds = np.array([0.9, 0.1, 0.8])

        result = comparator.compare_predictions(y_true, prod_preds, shadow_preds)

        assert not result.should_promote_shadow
        assert result.metadata.get("reason") == "insufficient_data"

    def test_maximize_direction(self) -> None:
        """direction=maximize: больше AUC = лучше."""
        comparator = ModelComparator(
            primary_metric="auc",
            direction="maximize",
            min_improvement_pct=3.0,
            min_samples=10,
        )

        rng = np.random.RandomState(42)
        n = 200
        y_true = rng.randint(0, 2, n)
        prod_preds = np.clip(rng.uniform(0.3, 0.7, n), 0.01, 0.99)
        # Shadow значительно лучше
        shadow_preds = np.clip(y_true + rng.randn(n) * 0.2, 0.01, 0.99)

        result = comparator.compare_predictions(y_true, prod_preds, shadow_preds)

        assert result.shadow_value > result.prod_value  # Больше AUC = лучше
        assert result.should_promote_shadow

    def test_marginal_improvement_no_promote(self) -> None:
        """Улучшение < min_improvement_pct → не промотируем."""
        comparator = ModelComparator(
            primary_metric="logloss",
            direction="minimize",
            min_improvement_pct=50.0,  # Очень высокий порог
            min_samples=10,
        )

        rng = np.random.RandomState(42)
        n = 100
        y_true = rng.randint(0, 2, n)
        preds = np.clip(y_true + rng.randn(n) * 0.3, 0.05, 0.95)

        # Одинаковые предсказания
        result = comparator.compare_predictions(y_true, preds, preds)

        assert not result.should_promote_shadow
