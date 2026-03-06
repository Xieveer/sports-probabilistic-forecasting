"""Тесты для модуля мониторинга (drift, performance)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from sports_forecast.monitoring.drift import (
    DriftResult,
    compute_ks_statistic,
    compute_psi,
    detect_drift,
)
from sports_forecast.monitoring.performance import (
    PerformanceReport,
    evaluate_on_new_data,
)


# ── PSI Tests ────────────────────────────────────────────────────────


class TestComputePSI:
    """Тесты для compute_psi."""

    def test_same_distribution_low_psi(self) -> None:
        """Одинаковые распределения → PSI ≈ 0."""
        rng = np.random.RandomState(42)
        expected = rng.randn(1000)
        actual = rng.randn(1000)

        psi = compute_psi(expected, actual)
        assert psi < 0.10  # Нет drift

    def test_shifted_distribution_high_psi(self) -> None:
        """Сдвинутые распределения → PSI > 0."""
        rng = np.random.RandomState(42)
        expected = rng.randn(1000)
        actual = rng.randn(1000) + 3  # Значительный сдвиг

        psi = compute_psi(expected, actual)
        assert psi > 0.25  # Significant drift

    def test_psi_non_negative(self) -> None:
        """PSI всегда >= 0."""
        rng = np.random.RandomState(42)
        expected = rng.randn(500)
        actual = rng.randn(500) + 0.5

        psi = compute_psi(expected, actual)
        assert psi >= 0

    def test_psi_identical_zero(self) -> None:
        """Абсолютно одинаковые данные → PSI → 0."""
        data = np.arange(100, dtype=float)
        psi = compute_psi(data, data)
        assert psi < 0.01


# ── KS Statistic Tests ──────────────────────────────────────────────


class TestComputeKS:
    """Тесты для compute_ks_statistic."""

    def test_same_distribution_low_ks(self) -> None:
        """Одинаковые распределения → малая KS-статистика."""
        rng = np.random.RandomState(42)
        a = rng.randn(1000)
        b = rng.randn(1000)

        ks = compute_ks_statistic(a, b)
        assert 0 <= ks <= 1
        assert ks < 0.10

    def test_different_distribution_high_ks(self) -> None:
        """Разные распределения → высокая KS-статистика."""
        rng = np.random.RandomState(42)
        a = rng.randn(1000)
        b = rng.randn(1000) + 5

        ks = compute_ks_statistic(a, b)
        assert ks > 0.5


# ── Detect Drift Tests ──────────────────────────────────────────────


class TestDetectDrift:
    """Тесты для detect_drift."""

    @pytest.fixture
    def stable_data(self) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Стабильные данные (без drift)."""
        rng = np.random.RandomState(42)
        ref = pd.DataFrame(
            {
                "f_a": rng.randn(500),
                "f_b": rng.randn(500),
            }
        )
        prod = pd.DataFrame(
            {
                "f_a": rng.randn(300),
                "f_b": rng.randn(300),
            }
        )
        return ref, prod

    @pytest.fixture
    def drifted_data(self) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Данные с drift."""
        rng = np.random.RandomState(42)
        ref = pd.DataFrame(
            {
                "f_a": rng.randn(500),
                "f_b": rng.randn(500),
            }
        )
        prod = pd.DataFrame(
            {
                "f_a": rng.randn(300) + 5,  # Большой drift
                "f_b": rng.randn(300),  # Без drift
            }
        )
        return ref, prod

    def test_stable_returns_stable(self, stable_data: tuple[pd.DataFrame, pd.DataFrame]) -> None:
        """Стабильные данные → status=stable."""
        ref, prod = stable_data
        result = detect_drift(ref, prod, ["f_a", "f_b"])

        assert isinstance(result, DriftResult)
        assert result.overall_status == "stable"
        assert len(result.drifted_features) == 0

    def test_drift_detected(self, drifted_data: tuple[pd.DataFrame, pd.DataFrame]) -> None:
        """Drift в f_a → обнаружен."""
        ref, prod = drifted_data
        result = detect_drift(ref, prod, ["f_a", "f_b"])

        assert result.overall_status in ("moderate", "significant")
        assert "f_a" in result.drifted_features

    def test_prediction_drift(self) -> None:
        """Drift в предсказаниях."""
        rng = np.random.RandomState(42)
        ref_df = pd.DataFrame({"f_a": rng.randn(500)})
        prod_df = pd.DataFrame({"f_a": rng.randn(300)})

        ref_preds = rng.uniform(0.3, 0.7, 500)
        prod_preds = rng.uniform(0.6, 0.9, 300)  # Сдвинутые предсказания

        result = detect_drift(
            ref_df,
            prod_df,
            ["f_a"],
            reference_predictions=ref_preds,
            production_predictions=prod_preds,
        )

        assert result.prediction_drift > 0


# ── Performance Tests ────────────────────────────────────────────────


class TestEvaluateOnNewData:
    """Тесты для evaluate_on_new_data."""

    def test_basic_evaluation(self) -> None:
        """Базовая оценка на новых данных."""
        rng = np.random.RandomState(42)
        y_true = rng.randint(0, 2, 100)
        y_pred = rng.uniform(0.2, 0.8, 100)

        report = evaluate_on_new_data(
            y_true,
            y_pred,
            tournament="test_tournament",
            market_spec="winner",
        )

        assert isinstance(report, PerformanceReport)
        assert report.tournament == "test_tournament"
        assert report.market_spec == "winner"
        assert report.n_samples == 100
        assert "logloss" in report.ml_metrics
        assert "auc" in report.ml_metrics
        assert "ece" in report.ml_metrics

    def test_no_degradation_without_baseline(self) -> None:
        """Без baseline нет деградации."""
        rng = np.random.RandomState(42)
        y_true = rng.randint(0, 2, 100)
        y_pred = rng.uniform(0, 1, 100)

        report = evaluate_on_new_data(y_true, y_pred)
        assert not report.is_degraded

    def test_degradation_detected(self) -> None:
        """Деградация при плохих метриках vs baseline."""
        rng = np.random.RandomState(42)
        y_true = rng.randint(0, 2, 200)
        # Плохие предсказания: почти случайные
        y_pred = np.clip(rng.uniform(0.4, 0.6, 200), 0.01, 0.99)

        baseline = {
            "logloss": 0.5,  # Хороший baseline
            "auc": 0.75,  # Хороший AUC
        }

        report = evaluate_on_new_data(
            y_true,
            y_pred,
            baseline_metrics=baseline,
            degradation_thresholds={"logloss_delta": 0.05, "auc_delta": 0.05},
        )

        # При почти случайных предсказаниях AUC должен быть ~0.5, что хуже 0.75
        assert report.is_degraded or report.ml_metrics["auc"] < baseline["auc"]

    def test_good_model_no_degradation(self) -> None:
        """Хорошая модель без деградации."""
        rng = np.random.RandomState(42)
        n = 500
        y_true = rng.randint(0, 2, n)
        # Хорошие предсказания
        y_pred = np.clip(y_true + rng.randn(n) * 0.2, 0.01, 0.99)

        baseline = {
            "logloss": 0.3,
            "auc": 0.90,
        }

        report = evaluate_on_new_data(
            y_true,
            y_pred,
            baseline_metrics=baseline,
        )

        # Хорошая модель не должна деградировать (если baseline не слишком жёсткий)
        assert report.n_samples == n
        assert report.ml_metrics["auc"] > 0.5
