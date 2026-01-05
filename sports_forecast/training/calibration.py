"""
Калибровка моделей для улучшения вероятностных прогнозов.

Использует sklearn.calibration.CalibratedClassifierCV с методами:
- Isotonic Regression (рекомендуется, для небольших выборок)
- Platt Scaling (сигмоид)

Автоматически проверяет ECE и применяет калибровку только при необходимости.

Примеры:
    >>> calibrator = ModelCalibrator(threshold_ece=0.1)
    >>> calibrated_model = calibrator.calibrate_if_needed(
    ...     model, X_cal, y_cal, X_val, y_val
    ... )
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV

from sports_forecast.train import compute_expected_calibration_error
from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)


class ModelCalibrator:
    """
    Калибратор моделей с автоматической проверкой ECE.

    Применяет калибровку только если ECE > threshold.
    Используется Isotonic Regression по умолчанию.

    Args:
        threshold_ece: Порог ECE для применения калибровки (по умолчанию 0.1).
        method: Метод калибровки ('isotonic' или 'sigmoid').
        cv: Cross-validation стратегия (по умолчанию 'prefit' - модель уже обучена).

    Attributes:
        threshold_ece: Порог ECE.
        method: Метод калибровки.
        cv: CV стратегия.

    Examples:
        >>> calibrator = ModelCalibrator(threshold_ece=0.1, method='isotonic')
        >>> calibrated_model = calibrator.calibrate_if_needed(
        ...     model=catboost_model,
        ...     X_cal=X_calibration,
        ...     y_cal=y_calibration,
        ...     X_val=X_validation,
        ...     y_val=y_validation,
        ... )
    """

    def __init__(
        self,
        threshold_ece: float = 0.1,
        method: str = "isotonic",
        cv: str | int = "prefit",
    ):
        """
        Инициализация калибратора.

        Args:
            threshold_ece: Порог ECE для применения калибровки.
            method: Метод калибровки ('isotonic' или 'sigmoid').
            cv: CV стратегия ('prefit' или количество фолдов).

        Raises:
            ValueError: Если method не в ['isotonic', 'sigmoid'].
        """
        if method not in ["isotonic", "sigmoid"]:
            raise ValueError(f"method должен быть 'isotonic' или 'sigmoid', получено: {method}")

        self.threshold_ece = threshold_ece
        self.method = method
        self.cv = cv

        logger.info(
            "Инициализирован ModelCalibrator: threshold_ece=%.2f, method='%s'",
            threshold_ece,
            method,
        )

    def calibrate_if_needed(
        self,
        model: Any,
        X_cal: pd.DataFrame | np.ndarray,
        y_cal: pd.Series | np.ndarray,
        X_val: pd.DataFrame | np.ndarray,
        y_val: pd.Series | np.ndarray,
    ) -> tuple[Any, bool, float, float]:
        """
        Калибровать модель, если ECE > threshold.

        Проверяет ECE на валидационной выборке ПЕРЕД калибровкой.
        Если ECE > threshold, применяет калибровку на калибровочной выборке.
        Проверяет ECE ПОСЛЕ калибровки.

        Args:
            model: Модель с методом predict_proba().
            X_cal: Фичи для калибровки.
            y_cal: Таргет для калибровки.
            X_val: Фичи для валидации (проверка ECE).
            y_val: Таргет для валидации (проверка ECE).

        Returns:
            Tuple:
                - model: Калиброванная модель (или исходная, если калибровка не нужна).
                - is_calibrated: Была ли применена калибровка.
                - ece_before: ECE до калибровки.
                - ece_after: ECE после калибровки (или None, если калибровка не применялась).

        Examples:
            >>> model, calibrated, ece_before, ece_after = calibrator.calibrate_if_needed(
            ...     catboost_model, X_cal, y_cal, X_val, y_val
            ... )
            >>> if calibrated:
            ...     print(f"ECE improved: {ece_before:.4f} -> {ece_after:.4f}")
        """
        # Предсказания на валидации ДО калибровки
        proba_before = model.predict_proba(X_val)[:, 1]
        ece_before = compute_expected_calibration_error(np.array(y_val), proba_before)

        logger.info("ECE до калибровки: %.4f (порог: %.2f)", ece_before, self.threshold_ece)

        # Проверяем, нужна ли калибровка
        if ece_before <= self.threshold_ece:
            logger.info("✓ Калибровка НЕ нужна (ECE <= %.2f)", self.threshold_ece)
            return model, False, ece_before, None

        # Применяем калибровку
        logger.info(
            "⚠ Калибровка нужна (ECE > %.2f). Применяю метод: %s", self.threshold_ece, self.method
        )

        calibrated_model = CalibratedClassifierCV(
            model,
            method=self.method,
            cv=self.cv,
        )

        calibrated_model.fit(X_cal, y_cal)

        # Предсказания на валидации ПОСЛЕ калибровки
        proba_after = calibrated_model.predict_proba(X_val)[:, 1]
        ece_after = compute_expected_calibration_error(np.array(y_val), proba_after)

        logger.info("ECE после калибровки: %.4f", ece_after)

        # Проверяем, что калибровка действительно улучшила ECE
        if ece_after < ece_before:
            logger.info("✓ Калибровка улучшила ECE: %.4f -> %.4f", ece_before, ece_after)
            return calibrated_model, True, ece_before, ece_after
        logger.warning(
            "⚠ Калибровка НЕ улучшила ECE: %.4f -> %.4f. Используем исходную модель.",
            ece_before,
            ece_after,
        )
        return model, False, ece_before, None

    def calibrate(
        self,
        model: Any,
        X_cal: pd.DataFrame | np.ndarray,
        y_cal: pd.Series | np.ndarray,
    ) -> Any:
        """
        Калибровать модель (без проверки ECE).

        Используется когда нужно явно калибровать модель, независимо от ECE.

        Args:
            model: Модель с методом predict_proba().
            X_cal: Фичи для калибровки.
            y_cal: Таргет для калибровки.

        Returns:
            Калиброванная модель.

        Examples:
            >>> calibrated_model = calibrator.calibrate(model, X_cal, y_cal)
        """
        logger.info("Применяю калибровку (метод: %s) БЕЗ проверки ECE", self.method)

        calibrated_model = CalibratedClassifierCV(
            model,
            method=self.method,
            cv=self.cv,
        )

        calibrated_model.fit(X_cal, y_cal)

        logger.info("Калибровка применена")

        return calibrated_model
