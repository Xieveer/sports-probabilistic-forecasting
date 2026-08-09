"""
Калибровка моделей для улучшения вероятностных прогнозов.

Реализует post-hoc калибровку (Isotonic / Sigmoid) непосредственно
на предсказанных вероятностях — без зависимости от sklearn-интерфейса
``get_params()`` / ``clone()``.

Автоматически проверяет ECE и применяет калибровку только при необходимости.

Примеры:
    >>> calibrator = ModelCalibrator(threshold_ece=0.1)
    >>> calibrated_model, applied, ece_before, ece_after = calibrator.calibrate_if_needed(
    ...     model, cal_features, cal_target, val_features, val_target
    ... )
"""

from __future__ import annotations

from typing import Any, cast

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression as SklearnLR

from sports_forecast.utils.log_config import get_logger
from sports_forecast.utils.metrics import compute_expected_calibration_error


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
        ...     cal_features=X_calibration,
        ...     cal_target=y_calibration,
        ...     val_features=X_validation,
        ...     val_target=y_validation,
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

    def _fit_calibration_map(
        self,
        raw_proba: np.ndarray,
        targets: np.ndarray,
    ) -> IsotonicRegression | SklearnLR:
        """Обучить маппинг вероятностей (Isotonic или Sigmoid).

        Args:
            raw_proba: Некалиброванные вероятности класса 1.
            targets: Бинарные метки (0/1).

        Returns:
            Обученный маппинг (IsotonicRegression или LogisticRegression).
        """
        if self.method == "isotonic":
            mapper = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
            mapper.fit(raw_proba, targets)
        else:
            # Sigmoid (Platt scaling)
            mapper = SklearnLR(C=1e10, solver="lbfgs", max_iter=1000)
            mapper.fit(raw_proba.reshape(-1, 1), targets)
        return mapper

    def _apply_calibration_map(
        self,
        mapper: IsotonicRegression | SklearnLR,
        raw_proba: np.ndarray,
    ) -> np.ndarray:
        """Применить маппинг к вероятностям.

        Args:
            mapper: Обученный маппинг.
            raw_proba: Некалиброванные вероятности.

        Returns:
            Калиброванные вероятности.
        """
        if isinstance(mapper, IsotonicRegression):
            return cast(np.ndarray, np.asarray(mapper.predict(raw_proba)))
        # Sigmoid
        return cast(np.ndarray, np.asarray(mapper.predict_proba(raw_proba.reshape(-1, 1))[:, 1]))

    def calibrate_if_needed(
        self,
        model: Any,
        cal_features: pd.DataFrame | np.ndarray,
        cal_target: pd.Series | np.ndarray,
        val_features: pd.DataFrame | np.ndarray,
        val_target: pd.Series | np.ndarray,
    ) -> tuple[Any, bool, float, float]:
        """Калибровать модель, если ECE > threshold.

        Процесс:
            1. Получить вероятности модели на cal и val.
            2. Посчитать ECE на val (before).
            3. Если ECE > threshold — обучить калибровочный маппинг на cal.
            4. Применить маппинг к val и проверить ECE (after).
            5. Если стало лучше — сохранить маппинг в модель.

        Работает с **любыми** моделями, у которых есть
        ``predict_proba()`` — без sklearn ``get_params()`` / ``clone()``.

        Args:
            model: Модель с ``predict_proba()``.
            cal_features: Фичи для калибровки.
            cal_target: Таргет для калибровки.
            val_features: Фичи для валидации (проверка ECE).
            val_target: Таргет для валидации (проверка ECE).

        Returns:
            Tuple:
                - model: Модель (с маппингом или без).
                - is_calibrated: Была ли применена калибровка.
                - ece_before: ECE до калибровки.
                - ece_after: ECE после калибровки (или ece_before).

        Examples:
            >>> model, calibrated, ece_before, ece_after = calibrator.calibrate_if_needed(
            ...     catboost_model, cal_features, cal_target, val_features, val_target
            ... )
        """
        # Вероятности на калибровочном и валидационном наборах
        cal_proba = model.predict_proba(cal_features)[:, 1]
        val_proba = model.predict_proba(val_features)[:, 1]

        ece_before = compute_expected_calibration_error(
            np.array(val_target),
            val_proba,
        )
        logger.info("ECE до калибровки: %.4f (порог: %.2f)", ece_before, self.threshold_ece)

        if ece_before <= self.threshold_ece:
            logger.info("✓ Калибровка НЕ нужна (ECE <= %.2f)", self.threshold_ece)
            return model, False, ece_before, ece_before

        # Обучаем маппинг на калибровочном наборе
        logger.info(
            "⚠ Калибровка нужна (ECE > %.2f). Применяю метод: %s",
            self.threshold_ece,
            self.method,
        )
        mapper = self._fit_calibration_map(cal_proba, np.array(cal_target))

        # Проверяем на валидации
        val_proba_after = self._apply_calibration_map(mapper, val_proba)
        ece_after = compute_expected_calibration_error(
            np.array(val_target),
            val_proba_after,
        )
        logger.info("ECE после калибровки: %.4f", ece_after)

        if ece_after < ece_before:
            logger.info(
                "✓ Калибровка улучшила ECE: %.4f → %.4f",
                ece_before,
                ece_after,
            )
            model.calibration_mapper_ = mapper
            model.calibration_method_ = self.method
            model.is_calibrated_ = True
            return model, True, ece_before, ece_after

        logger.warning(
            "⚠ Калибровка НЕ улучшила ECE: %.4f → %.4f. Используем исходную модель.",
            ece_before,
            ece_after,
        )
        return model, False, ece_before, ece_before

    def calibrate(
        self,
        model: Any,
        cal_features: pd.DataFrame | np.ndarray,
        cal_target: pd.Series | np.ndarray,
    ) -> Any:
        """Калибровать модель (без проверки ECE).

        Args:
            model: Модель с ``predict_proba()``.
            cal_features: Фичи для калибровки.
            cal_target: Таргет для калибровки.

        Returns:
            Модель с калибровочным маппингом.

        Examples:
            >>> calibrated = calibrator.calibrate(model, cal_features, cal_target)
        """
        logger.info("Применяю калибровку (метод: %s) БЕЗ проверки ECE", self.method)

        cal_proba = model.predict_proba(cal_features)[:, 1]
        mapper = self._fit_calibration_map(cal_proba, np.array(cal_target))

        model.calibration_mapper_ = mapper
        model.calibration_method_ = self.method
        model.is_calibrated_ = True

        logger.info("Калибровка применена")
        return model
