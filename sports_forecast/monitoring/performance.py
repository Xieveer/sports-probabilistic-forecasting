"""Model Performance Tracker.

Отслеживает качество модели на новых данных (после того как
результаты матчей стали известны).

Сценарий:
    1. Забираем предсказания из Prediction Store (status = ``materialized``).
    2. Забираем фактические результаты из ``processed`` данных.
    3. Вычисляем ML + Betting метрики.
    4. Экспортируем в Prometheus Gauges.
    5. При деградации — триггерим алерт / переобучение.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score

from sports_forecast.utils.log_config import get_logger
from sports_forecast.utils.metrics import compute_expected_calibration_error


logger = get_logger(__name__)


@dataclass
class PerformanceReport:
    """Отчёт о качестве модели на новых данных.

    Attributes:
        tournament: Название турнира.
        market_spec: Название market_spec.
        n_samples: Количество матчей с результатами.
        ml_metrics: ML-метрики (AUC, LogLoss, Brier, ECE).
        betting_metrics: Бизнес-метрики (ROI, profit, n_bets).
        is_degraded: Есть ли деградация.
        degradation_details: Подробности деградации.
    """

    tournament: str
    market_spec: str
    n_samples: int
    ml_metrics: dict[str, float]
    betting_metrics: dict[str, float] = field(default_factory=dict)
    is_degraded: bool = False
    degradation_details: list[str] = field(default_factory=list)


def evaluate_on_new_data(
    y_true: np.ndarray,
    y_pred_proba: np.ndarray,
    tournament: str = "unknown",
    market_spec: str = "unknown",
    baseline_metrics: dict[str, float] | None = None,
    degradation_thresholds: dict[str, float] | None = None,
) -> PerformanceReport:
    """Оценить модель на новых данных.

    Args:
        y_true: Фактические метки (0/1).
        y_pred_proba: Предсказанные вероятности.
        tournament: Название турнира.
        market_spec: Название market_spec.
        baseline_metrics: Baseline метрики (от training run).
            Ключи: ``"logloss"``, ``"auc"``, ``"ece"``.
        degradation_thresholds: Пороги деградации.
            Ключи: ``"logloss_delta"``, ``"auc_delta"``, ``"ece_delta"``.
            По умолчанию: 10% ухудшение.

    Returns:
        PerformanceReport.

    Examples:
        >>> report = evaluate_on_new_data(y_true, y_pred, tournament="uel_kz_1")
        >>> if report.is_degraded:
        ...     trigger_retraining()
    """
    if degradation_thresholds is None:
        degradation_thresholds = {
            "logloss_delta": 0.10,  # 10% ухудшение LogLoss
            "auc_delta": 0.05,  # 5% ухудшение AUC
            "ece_delta": 0.10,  # 10% ухудшение ECE
        }

    # Вычисляем метрики
    ml_metrics: dict[str, float] = {}
    try:
        ml_metrics["logloss"] = float(log_loss(y_true, y_pred_proba))
    except Exception as e:
        logger.warning("LogLoss ошибка: %s", e)
        ml_metrics["logloss"] = 0.0

    try:
        ml_metrics["auc"] = float(roc_auc_score(y_true, y_pred_proba))
    except Exception as e:
        logger.warning("AUC ошибка: %s", e)
        ml_metrics["auc"] = 0.0

    try:
        ml_metrics["brier"] = float(brier_score_loss(y_true, y_pred_proba))
    except Exception as e:
        logger.warning("Brier ошибка: %s", e)
        ml_metrics["brier"] = 0.0

    try:
        ml_metrics["ece"] = float(compute_expected_calibration_error(y_true, y_pred_proba))
    except Exception as e:
        logger.warning("ECE ошибка: %s", e)
        ml_metrics["ece"] = 0.0

    # Проверяем деградацию
    is_degraded = False
    degradation_details: list[str] = []

    if baseline_metrics:
        # LogLoss: увеличение = деградация
        if "logloss" in baseline_metrics and ml_metrics["logloss"] > 0:
            baseline_ll = baseline_metrics["logloss"]
            if baseline_ll > 0:
                delta = (ml_metrics["logloss"] - baseline_ll) / baseline_ll
                if delta > degradation_thresholds.get("logloss_delta", 0.10):
                    is_degraded = True
                    degradation_details.append(
                        f"LogLoss деградация: {baseline_ll:.4f} → {ml_metrics['logloss']:.4f} "
                        f"(+{delta * 100:.1f}%)"
                    )

        # AUC: уменьшение = деградация
        if "auc" in baseline_metrics and ml_metrics["auc"] > 0:
            baseline_auc = baseline_metrics["auc"]
            if baseline_auc > 0:
                delta = (baseline_auc - ml_metrics["auc"]) / baseline_auc
                if delta > degradation_thresholds.get("auc_delta", 0.05):
                    is_degraded = True
                    degradation_details.append(
                        f"AUC деградация: {baseline_auc:.4f} → {ml_metrics['auc']:.4f} "
                        f"(-{delta * 100:.1f}%)"
                    )

        # ECE: увеличение = деградация
        if "ece" in baseline_metrics and ml_metrics["ece"] > 0:
            baseline_ece = baseline_metrics["ece"]
            if baseline_ece > 0:
                delta = (ml_metrics["ece"] - baseline_ece) / baseline_ece
                if delta > degradation_thresholds.get("ece_delta", 0.10):
                    is_degraded = True
                    degradation_details.append(
                        f"ECE деградация: {baseline_ece:.4f} → {ml_metrics['ece']:.4f} "
                        f"(+{delta * 100:.1f}%)"
                    )

    # Логируем
    if is_degraded:
        logger.warning(
            "⚠ ДЕГРАДАЦИЯ [%s / %s]: %d проблем",
            tournament,
            market_spec,
            len(degradation_details),
        )
        for detail in degradation_details:
            logger.warning("  %s", detail)
    else:
        logger.info(
            "✓ Качество [%s / %s]: OK (AUC=%.4f, LL=%.4f, ECE=%.4f, n=%d)",
            tournament,
            market_spec,
            ml_metrics.get("auc", 0),
            ml_metrics.get("logloss", 0),
            ml_metrics.get("ece", 0),
            len(y_true),
        )

    return PerformanceReport(
        tournament=tournament,
        market_spec=market_spec,
        n_samples=len(y_true),
        ml_metrics=ml_metrics,
        is_degraded=is_degraded,
        degradation_details=degradation_details,
    )


def update_prometheus_metrics(
    report: PerformanceReport,
) -> None:
    """Обновить Prometheus метрики из PerformanceReport.

    Args:
        report: Отчёт о качестве модели.
    """
    from sports_forecast.monitoring.metrics import (
        MODEL_AUC,
        MODEL_BRIER,
        MODEL_ECE,
        MODEL_LOGLOSS,
    )

    labels: dict[str, Any] = {
        "tournament": report.tournament,
        "market_spec": report.market_spec,
    }

    if "auc" in report.ml_metrics:
        MODEL_AUC.labels(**labels).set(report.ml_metrics["auc"])
    if "logloss" in report.ml_metrics:
        MODEL_LOGLOSS.labels(**labels).set(report.ml_metrics["logloss"])
    if "ece" in report.ml_metrics:
        MODEL_ECE.labels(**labels).set(report.ml_metrics["ece"])
    if "brier" in report.ml_metrics:
        MODEL_BRIER.labels(**labels).set(report.ml_metrics["brier"])

    logger.debug(
        "Prometheus метрики обновлены для %s / %s",
        report.tournament,
        report.market_spec,
    )
