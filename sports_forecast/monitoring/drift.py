"""Data & Prediction Drift Detection.

Обнаружение drift-а в данных и предсказаниях модели.

Методы:
    - PSI (Population Stability Index): для числовых и категориальных фичей.
    - KS-statistic: для числовых фичей.
    - Prediction drift: PSI для распределения предсказанных вероятностей.

Пороги (по PSI):
    - < 0.10: нет drift (stable)
    - 0.10 - 0.25: умеренный drift (moderate)
    - > 0.25: значительный drift (significant)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, cast

import numpy as np
import pandas as pd

from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)

# PSI пороги
PSI_THRESHOLD_MODERATE = 0.10
PSI_THRESHOLD_SIGNIFICANT = 0.25


@dataclass
class DriftResult:
    """Результат проверки drift-а.

    Attributes:
        feature_drift: PSI для каждой фичи.
        prediction_drift: PSI для предсказаний.
        drifted_features: Фичи с PSI > threshold.
        overall_status: ``"stable"``, ``"moderate"``, ``"significant"``.
    """

    feature_drift: dict[str, float]
    prediction_drift: float
    drifted_features: list[str]
    overall_status: str
    metadata: dict[str, object] = field(default_factory=dict)


def compute_psi(
    expected: Any,
    actual: Any,
    n_bins: int = 10,
    eps: float = 1e-4,
) -> float:
    """Вычислить Population Stability Index (PSI).

    PSI = Σ (actual_pct - expected_pct) * ln(actual_pct / expected_pct)

    Args:
        expected: Распределение (reference/train).
        actual: Распределение (production/new data).
        n_bins: Количество бинов для дискретизации.
        eps: Малое число для избежания деления на ноль.

    Returns:
        PSI значение (чем больше, тем сильнее drift).
    """
    # Бинируем по квантилям reference распределения
    breakpoints = np.linspace(0, 100, n_bins + 1)
    bins = np.percentile(expected, breakpoints)
    bins = np.unique(bins)

    if len(bins) < 2:
        return 0.0

    expected_histogram = cast(tuple[np.ndarray, np.ndarray], np.histogram(expected, bins=bins))
    actual_histogram = cast(tuple[np.ndarray, np.ndarray], np.histogram(actual, bins=bins))
    expected_counts = expected_histogram[0]
    actual_counts = actual_histogram[0]

    # Доля в каждом бине
    expected_pct = (expected_counts + eps) / (len(expected) + eps * len(bins))
    actual_pct = (actual_counts + eps) / (len(actual) + eps * len(bins))

    return float(np.sum((actual_pct - expected_pct) * np.log(actual_pct / expected_pct)))


def compute_ks_statistic(
    expected: Any,
    actual: Any,
) -> float:
    """Вычислить Kolmogorov-Smirnov статистику.

    Args:
        expected: Reference распределение.
        actual: Production распределение.

    Returns:
        KS-статистика [0, 1].
    """
    from scipy.stats import ks_2samp

    stat, _ = ks_2samp(expected, actual)
    return float(stat)


def detect_drift(
    reference_df: pd.DataFrame,
    production_df: pd.DataFrame,
    feature_columns: list[str],
    reference_predictions: np.ndarray | None = None,
    production_predictions: np.ndarray | None = None,
    psi_threshold: float = PSI_THRESHOLD_MODERATE,
    n_bins: int = 10,
) -> DriftResult:
    """Обнаружить drift в данных и предсказаниях.

    Args:
        reference_df: Reference данные (train set).
        production_df: Production данные (новые данные).
        feature_columns: Список фичей для проверки.
        reference_predictions: Предсказания на reference данных.
        production_predictions: Предсказания на production данных.
        psi_threshold: Порог PSI для определения drift.
        n_bins: Количество бинов для PSI.

    Returns:
        DriftResult с информацией о drift-е.

    Examples:
        >>> result = detect_drift(train_df, new_df, feature_cols)
        >>> if result.overall_status == "significant":
        ...     trigger_retraining()
    """
    feature_drift: dict[str, float] = {}
    drifted_features: list[str] = []

    for col in feature_columns:
        if col not in reference_df.columns or col not in production_df.columns:
            continue

        ref_vals = np.asarray(reference_df[col].dropna().values, dtype=float)
        prod_vals = np.asarray(production_df[col].dropna().values, dtype=float)

        if len(ref_vals) < 10 or len(prod_vals) < 10:
            continue

        psi = compute_psi(ref_vals, prod_vals, n_bins=n_bins)
        feature_drift[col] = round(psi, 4)

        if psi > psi_threshold:
            drifted_features.append(col)

    # Prediction drift
    prediction_drift = 0.0
    if (
        reference_predictions is not None
        and production_predictions is not None
        and len(reference_predictions) >= 10
        and len(production_predictions) >= 10
    ):
        prediction_drift = compute_psi(
            reference_predictions,
            production_predictions,
            n_bins=n_bins,
        )

    # Определяем overall status
    max_psi = max(feature_drift.values()) if feature_drift else 0.0
    max_psi = max(max_psi, prediction_drift)

    if max_psi > PSI_THRESHOLD_SIGNIFICANT:
        overall_status = "significant"
    elif max_psi > PSI_THRESHOLD_MODERATE:
        overall_status = "moderate"
    else:
        overall_status = "stable"

    n_drifted = len(drifted_features)
    n_total = len(feature_drift)

    logger.info(
        "Drift detection: %s (max PSI=%.4f, %d/%d features drifted, pred_drift=%.4f)",
        overall_status,
        max_psi,
        n_drifted,
        n_total,
        prediction_drift,
    )

    if drifted_features:
        top_drifted = sorted(
            [(f, feature_drift[f]) for f in drifted_features],
            key=lambda x: x[1],
            reverse=True,
        )[:5]
        for feat, psi_val in top_drifted:
            logger.warning("  Drift: %s (PSI=%.4f)", feat, psi_val)

    return DriftResult(
        feature_drift=feature_drift,
        prediction_drift=round(prediction_drift, 4),
        drifted_features=sorted(drifted_features),
        overall_status=overall_status,
        metadata={
            "n_reference": len(reference_df),
            "n_production": len(production_df),
            "n_features_checked": n_total,
            "psi_threshold": psi_threshold,
        },
    )
