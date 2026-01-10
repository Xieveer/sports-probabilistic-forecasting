"""
Time Series Cross-Validation для обучения моделей на временных рядах.

Реализует кастомный TSCV с:
- 4 фолдами по умолчанию
- Поддержкой expanding window (0-25%, 0-50%, 0-75%, 0-100%)
- Метриками для каждого фолда
- Усреднёнными метриками

Примеры:
    >>> tscv = TimeSeriesCrossValidator(n_splits=4)
    >>> for fold_idx, (train_idx, val_idx) in enumerate(tscv.split(X)):
    ...     train_features, val_features = features.iloc[train_idx], features.iloc[val_idx]
    ...     train_target, val_target = y.iloc[train_idx], y.iloc[val_idx]
    ...     # Обучение
"""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, brier_score_loss, log_loss, roc_auc_score
from sklearn.model_selection import TimeSeriesSplit

from sports_forecast.utils.log_config import get_logger

# Используем ECE из train.py
from sports_forecast.utils.metrics import compute_expected_calibration_error


logger = get_logger(__name__)


class TimeSeriesCrossValidator:
    """
    Time Series Cross-Validation с расширяющимся окном.

    Разбивает данные на n_splits фолдов, где каждый следующий фолд
    использует больше данных для обучения:
    - Фолд 1: train(0-25%), val(25-50%)
    - Фолд 2: train(0-50%), val(50-75%)
    - Фолд 3: train(0-75%), val(75-87.5%)
    - Фолд 4: train(0-87.5%), val(87.5-100%)

    Args:
        n_splits: Количество фолдов (по умолчанию 4).
        test_size: Размер тестовой выборки (НЕ используется в TSCV,
                   но сохраняется для совместимости).

    Attributes:
        n_splits: Количество фолдов.
        test_size: Размер тестовой выборки.

    Examples:
        >>> tscv = TimeSeriesCrossValidator(n_splits=4)
        >>> results = tscv.cross_validate(model, features, y)
        >>> print(results["mean_logloss"])  # Средний log loss
    """

    def __init__(self, n_splits: int = 4, test_size: float = 0.1):
        """
        Инициализация TSCV.

        Args:
            n_splits: Количество фолдов.
            test_size: Размер тестовой выборки (для информации).
        """
        if n_splits < 2:
            raise ValueError(f"n_splits должно быть >= 2, получено: {n_splits}")

        self.n_splits = n_splits
        self.test_size = test_size
        self.tscv = TimeSeriesSplit(n_splits=n_splits)

        logger.debug("Инициализирован TimeSeriesCrossValidator: n_splits=%d", n_splits)

    def split(
        self,
        features: pd.DataFrame | np.ndarray,
        target: pd.Series | np.ndarray | None = None,
    ) -> Generator[tuple[np.ndarray, np.ndarray], None, None]:
        """
        Генерирует индексы train/validation для каждого фолда.

        Args:
            features: Данные для разбиения.
            target: Таргет (не используется, для совместимости со sklearn).

        Yields:
            Tuple[train_indices, val_indices]: Индексы для обучения и валидации.

        Examples:
            >>> for train_idx, val_idx in tscv.split(X):
            ...     train_features = features.iloc[train_idx]
            ...     val_features = features.iloc[val_idx]
        """
        logger.debug("Разбиваю данные на %d фолдов (TSCV)", self.n_splits)

        for fold_idx, (train_idx, val_idx) in enumerate(self.tscv.split(features), 1):
            logger.debug(
                "Фолд %d/%d: train=%d записей (%.1f%%), val=%d записей (%.1f%%)",
                fold_idx,
                self.n_splits,
                len(train_idx),
                len(train_idx) / len(features) * 100,
                len(val_idx),
                len(val_idx) / len(features) * 100,
            )
            yield train_idx, val_idx

    def cross_validate(
        self,
        model: Any,
        features: pd.DataFrame,
        target: pd.Series,
        fit_kwargs: dict | None = None,
    ) -> dict[str, Any]:
        """
        Выполнить кросс-валидацию модели и вернуть метрики.

        Args:
            model: Модель с методами fit() и predict_proba().
            features: Фичи для обучения.
            target: Таргет.
            fit_kwargs: Дополнительные параметры для model.fit().

        Returns:
            Словарь с метриками:
                - fold_{i}_logloss: Log loss для каждого фолда
                - fold_{i}_auc: AUC для каждого фолда
                - fold_{i}_accuracy: Accuracy для каждого фолда
                - fold_{i}_brier: Brier score для каждого фолда
                - fold_{i}_ece: ECE для каждого фолда
                - mean_logloss: Средний log loss
                - std_logloss: Стандартное отклонение log loss
                - mean_auc: Средний AUC
                - mean_accuracy: Средний Accuracy
                - mean_brier: Средний Brier score
                - mean_ece: Средний ECE
                - n_folds: Количество фолдов

        Examples:
            >>> results = tscv.cross_validate(catboost_model, train_features, train_target)
            >>> print(f"Mean LogLoss: {results['mean_logloss']:.4f}")
        """
        if fit_kwargs is None:
            fit_kwargs = {}

        logger.info("Запуск TSCV: %d фолдов на %d записях", self.n_splits, len(features))

        # Сохраняем метрики для каждого фолда
        fold_metrics: dict[str, list[float]] = {
            "logloss": [],
            "auc": [],
            "accuracy": [],
            "brier": [],
            "ece": [],
        }  # type: ignore[assignment]

        # Проходим по фолдам
        for fold_idx, (train_idx, val_idx) in enumerate(self.split(features, target), 1):
            logger.info("--- Фолд %d/%d ---", fold_idx, self.n_splits)

            # Разбиваем данные
            train_features = (
                features.iloc[train_idx]
                if isinstance(features, pd.DataFrame)
                else features[train_idx]
            )
            val_features = (
                features.iloc[val_idx] if isinstance(features, pd.DataFrame) else features[val_idx]
            )
            train_target = (
                target.iloc[train_idx] if isinstance(target, pd.Series) else target[train_idx]
            )
            val_target = target.iloc[val_idx] if isinstance(target, pd.Series) else target[val_idx]

            # Обучаем модель
            model.fit(train_features, train_target, **fit_kwargs)

            # Предсказания
            proba = model.predict_proba(val_features)[:, 1]
            y_pred = (proba >= 0.5).astype(int)

            # Метрики
            try:
                logloss = float(log_loss(val_target, proba))
                fold_metrics["logloss"].append(logloss)
                logger.info("  LogLoss:  %.4f", logloss)
            except Exception as e:
                logger.warning("  LogLoss:  Ошибка - %s", e)

            try:
                auc = float(roc_auc_score(val_target, proba))
                fold_metrics["auc"].append(auc)
                logger.info("  AUC:      %.4f", auc)
            except Exception as e:
                logger.warning("  AUC:      Ошибка - %s", e)

            try:
                accuracy = float(accuracy_score(val_target, y_pred))
                fold_metrics["accuracy"].append(accuracy)
                logger.info("  Accuracy: %.4f", accuracy)
            except Exception as e:
                logger.warning("  Accuracy: Ошибка - %s", e)

            try:
                brier = brier_score_loss(val_target, proba)
                fold_metrics["brier"].append(brier)
                logger.info("  Brier:    %.4f", brier)
            except Exception as e:
                logger.warning("  Brier:    Ошибка - %s", e)

            try:
                ece = compute_expected_calibration_error(np.array(val_target), proba)
                fold_metrics["ece"].append(ece)
                logger.info("  ECE:      %.4f", ece)
            except Exception as e:
                logger.warning("  ECE:      Ошибка - %s", e)

        # Усреднённые метрики
        results = {
            "n_folds": self.n_splits,
        }

        for metric_name, values in fold_metrics.items():
            if values:
                # Метрики по фолдам
                for fold_idx, value in enumerate(values, 1):
                    results[f"fold_{fold_idx}_{metric_name}"] = value  # type: ignore[assignment]

                # Усреднённые метрики
                results[f"mean_{metric_name}"] = float(np.mean(values))  # type: ignore[assignment]
                results[f"std_{metric_name}"] = float(np.std(values))  # type: ignore[assignment]

        logger.info("=" * 60)
        logger.info("TSCV ЗАВЕРШЕНА")
        logger.info(
            "Mean LogLoss: %.4f ± %.4f",
            results.get("mean_logloss", 0),
            results.get("std_logloss", 0),
        )
        logger.info(
            "Mean AUC:     %.4f ± %.4f", results.get("mean_auc", 0), results.get("std_auc", 0)
        )
        logger.info(
            "Mean Acc:     %.4f ± %.4f",
            results.get("mean_accuracy", 0),
            results.get("std_accuracy", 0),
        )
        logger.info("=" * 60)

        return results

    def get_n_splits(self) -> int:
        """
        Получить количество фолдов.

        Returns:
            Количество фолдов.
        """
        return self.n_splits
