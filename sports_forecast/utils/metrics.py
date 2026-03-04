"""
Метрики качества моделей.

Содержит функции для вычисления различных метрик:
- Expected Calibration Error (ECE)
- Maximum Calibration Error (MCE)
- Calibration bin data для reliability diagram
"""

from __future__ import annotations

import numpy as np


def _calibration_bin_data(
    y_true: np.ndarray,
    y_pred_proba: np.ndarray,
    n_bins: int = 10,
) -> list[tuple[int, float, float]]:
    """Вычислить данные по бинам для калибровки.

    Args:
        y_true: Истинные метки (0 или 1).
        y_pred_proba: Предсказанные вероятности [0, 1].
        n_bins: Количество бинов.

    Returns:
        Список кортежей ``(n_samples, avg_pred, actual_freq)`` для непустых бинов.
    """
    bins = np.linspace(0.0, 1.0, n_bins + 1)
    bin_indices = np.digitize(y_pred_proba, bins, right=True)

    result: list[tuple[int, float, float]] = []
    for bin_idx in range(1, n_bins + 1):
        mask = bin_indices == bin_idx
        if not mask.any():
            continue
        n_samples = int(mask.sum())
        avg_pred = float(y_pred_proba[mask].mean())
        actual_freq = float(y_true[mask].mean())
        result.append((n_samples, avg_pred, actual_freq))
    return result


def compute_expected_calibration_error(
    y_true: np.ndarray, y_pred_proba: np.ndarray, n_bins: int = 10
) -> float:
    """Вычислить Expected Calibration Error (ECE).

    ECE — взвешенное среднее абсолютных разностей между предсказанной
    вероятностью и фактической частотой положительного класса в бинах.

    Args:
        y_true: Истинные метки (0 или 1).
        y_pred_proba: Предсказанные вероятности [0, 1].
        n_bins: Количество бинов для разбиения (по умолчанию 10).

    Returns:
        ECE score [0, 1], где 0 = идеальная калибровка.

    Examples:
        >>> y_true = np.array([0, 0, 1, 1])
        >>> y_pred = np.array([0.1, 0.2, 0.8, 0.9])
        >>> ece = compute_expected_calibration_error(y_true, y_pred)
        >>> # ece ≈ 0.0 (хорошая калибровка)
    """
    n_total = len(y_true)
    if n_total == 0:
        return 0.0

    bin_data = _calibration_bin_data(y_true, y_pred_proba, n_bins)
    ece = sum(
        (n_samples / n_total) * abs(avg_pred - actual_freq)
        for n_samples, avg_pred, actual_freq in bin_data
    )
    return float(ece)


def compute_max_calibration_error(
    y_true: np.ndarray, y_pred_proba: np.ndarray, n_bins: int = 10
) -> float:
    """Вычислить Maximum Calibration Error (MCE).

    MCE — максимальная абсолютная разность между предсказанной
    вероятностью и фактической частотой по всем бинам.
    Показывает «худший» бин калибровки.

    Args:
        y_true: Истинные метки (0 или 1).
        y_pred_proba: Предсказанные вероятности [0, 1].
        n_bins: Количество бинов для разбиения (по умолчанию 10).

    Returns:
        MCE score [0, 1], где 0 = идеальная калибровка.

    Examples:
        >>> y_true = np.array([0, 0, 1, 1])
        >>> y_pred = np.array([0.1, 0.2, 0.8, 0.9])
        >>> mce = compute_max_calibration_error(y_true, y_pred)
    """
    bin_data = _calibration_bin_data(y_true, y_pred_proba, n_bins)
    if not bin_data:
        return 0.0

    mce = max(abs(avg_pred - actual_freq) for _, avg_pred, actual_freq in bin_data)
    return float(mce)


def compute_calibration_table(
    y_true: np.ndarray, y_pred_proba: np.ndarray, n_bins: int = 10
) -> list[dict[str, float]]:
    """Построить reliability diagram данные (таблица для артефакта).

    Args:
        y_true: Истинные метки (0 или 1).
        y_pred_proba: Предсказанные вероятности [0, 1].
        n_bins: Количество бинов.

    Returns:
        Список словарей с полями ``bin_mid``, ``avg_pred``,
        ``actual_freq``, ``n_samples``, ``weight``.
    """
    n_total = len(y_true)
    if n_total == 0:
        return []

    bins = np.linspace(0.0, 1.0, n_bins + 1)
    bin_data = _calibration_bin_data(y_true, y_pred_proba, n_bins)

    table: list[dict[str, float]] = []
    for n_samples, avg_pred, actual_freq in bin_data:
        # Определяем mid по avg_pred (приблизительно)
        bin_idx = int(np.digitize([avg_pred], bins, right=True)[0])
        bin_mid = float((bins[max(0, bin_idx - 1)] + bins[min(bin_idx, n_bins)]) / 2)
        table.append(
            {
                "bin_mid": bin_mid,
                "avg_pred": avg_pred,
                "actual_freq": actual_freq,
                "n_samples": float(n_samples),
                "weight": n_samples / n_total,
            }
        )
    return table
