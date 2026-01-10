"""
Метрики качества моделей.

Содержит функции для вычисления различных метрик:
- Expected Calibration Error (ECE)
- Другие метрики калибровки
"""

from __future__ import annotations

import numpy as np


def compute_expected_calibration_error(
    y_true: np.ndarray, y_pred_proba: np.ndarray, n_bins: int = 10
) -> float:
    """
    Вычислить Expected Calibration Error (ECE).

    ECE измеряет разницу между предсказанной вероятностью и фактической
    частотой положительного класса в бинах.

    Args:
        y_true: Истинные метки (0 или 1)
        y_pred_proba: Предсказанные вероятности [0, 1]
        n_bins: Количество бинов для разбиения (по умолчанию 10)

    Returns:
        ECE score [0, 1], где 0 = идеальная калибровка

    Examples:
        >>> y_true = np.array([0, 0, 1, 1])
        >>> y_pred = np.array([0.1, 0.2, 0.8, 0.9])
        >>> ece = compute_expected_calibration_error(y_true, y_pred)
        >>> # ece ≈ 0.0 (хорошая калибровка)
    """
    # Создаем bins от 0 до 1
    bins = np.linspace(0.0, 1.0, n_bins + 1)

    # Digitize - определяем в какой bin попадает каждое предсказание
    bin_indices = np.digitize(y_pred_proba, bins, right=True)

    ece = 0.0

    for bin_idx in range(1, n_bins + 1):
        # Маска для текущего бина
        mask = bin_indices == bin_idx

        if not mask.any():
            continue

        # Количество сэмплов в бине
        n_samples_in_bin = mask.sum()

        # Средняя предсказанная вероятность в бине
        avg_predicted_prob = y_pred_proba[mask].mean()

        # Фактическая частота положительного класса в бине
        actual_frequency = y_true[mask].mean()

        # Взвешенная разница
        bin_ece = (n_samples_in_bin / len(y_true)) * np.abs(avg_predicted_prob - actual_frequency)
        ece += bin_ece

    return float(ece)
