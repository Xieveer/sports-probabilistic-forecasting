"""Контрактные тесты метрик калибровки."""

from __future__ import annotations

import numpy as np

from sports_forecast.utils.metrics import compute_calibration_table


def test_calibration_table_keeps_bin_midpoint_and_sample_count() -> None:
    """Таблица калибровки содержит середину бина и число его наблюдений."""
    table = compute_calibration_table(
        np.array([0.0, 1.0]),
        np.array([0.2, 0.8]),
        n_bins=2,
    )

    assert table == [
        {
            "bin_mid": 0.25,
            "avg_pred": 0.2,
            "actual_freq": 0.0,
            "n_samples": 1.0,
            "weight": 0.5,
        },
        {
            "bin_mid": 0.75,
            "avg_pred": 0.8,
            "actual_freq": 1.0,
            "n_samples": 1.0,
            "weight": 0.5,
        },
    ]
