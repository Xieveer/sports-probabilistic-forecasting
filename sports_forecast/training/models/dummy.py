"""
Dummy модель для baseline.

Предсказывает на основе распределения классов в обучающей выборке.
Используется как baseline для сравнения с более сложными моделями.

Примеры:
    >>> dummy = DummyModel(name="dummy", config=cfg)
    >>> dummy.fit(X_train, y_train)
    >>> proba = dummy.predict_proba(X_test)
"""

from __future__ import annotations

from typing import Any

import pandas as pd
from omegaconf import DictConfig
from sklearn.dummy import DummyClassifier

from sports_forecast.training.base import BaseSingleModel
from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)


class DummyModel(BaseSingleModel):
    """
    Dummy модель для baseline.

    Использует sklearn.dummy.DummyClassifier со стратегией "prior":
    предсказывает вероятности на основе распределения классов в train.

    Args:
        name: Название модели (по умолчанию "dummy").
        config: Конфигурация модели из Hydra.
        params: Гиперпараметры (strategy, random_state).

    Attributes:
        model_: DummyClassifier.

    Examples:
        >>> dummy = DummyModel(name="dummy", config=cfg)
        >>> dummy.fit(X_train, y_train)
        >>> proba = dummy.predict_proba(X_test)
        >>> # Вероятности = [class_0_freq, class_1_freq] для всех записей
    """

    def __init__(
        self,
        name: str = "dummy",
        config: DictConfig | dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ):
        """
        Инициализация Dummy модели.

        Args:
            name: Название модели.
            config: Конфигурация модели.
            params: Гиперпараметры (strategy="prior", random_state=777).
        """
        # Параметры по умолчанию для DummyClassifier
        default_params = {
            "strategy": "prior",  # Предсказывает на основе частот классов
            "random_state": 777,
        }

        if params is None and config is not None and hasattr(config, "params"):
            params = dict(config.params)
        elif params is None:
            params = default_params
        else:
            # Объединяем с defaults
            params = {**default_params, **params}

        super().__init__(name=name, config=config or {}, params=params)

        logger.info(
            "Инициализирован DummyModel (baseline) с strategy='%s'", self.params.get("strategy")
        )

    def _create_model(self) -> DummyClassifier:
        """
        Создать экземпляр DummyClassifier.

        Returns:
            Экземпляр DummyClassifier.
        """
        return DummyClassifier(**self.params)

    def _fit_implementation(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        **fit_kwargs,
    ) -> None:
        """
        Обучить DummyClassifier.

        Args:
            X: Фичи (не используются для dummy).
            y: Таргет.
            **fit_kwargs: Дополнительные параметры (игнорируются).
        """
        # DummyClassifier игнорирует X, но требует его для совместимости с sklearn API
        self.model_.fit(X, y)

        # Логируем распределение классов
        class_prior = self.model_.class_prior_
        logger.info("DummyModel обучен на распределении классов:")
        for class_idx, prior in enumerate(class_prior):
            logger.info("  Класс %d: %.4f (%.1f%%)", class_idx, prior, prior * 100)
