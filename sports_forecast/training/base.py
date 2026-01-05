"""
Базовые классы для системы обучения моделей.

Иерархия:
    BaseModel (abstract)
    ├─ BaseSingleModel (для одиночных моделей)
    └─ BaseEnsembleModel (для ансамблей)

Примеры:
    >>> class CatBoostModel(BaseSingleModel):
    ...     def _create_model(self):
    ...         return CatBoostClassifier(**self.params)
    ...
    ...     def _fit_implementation(self, X, y, **fit_kwargs):
    ...         self.model_.fit(X, y, **fit_kwargs)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from omegaconf import DictConfig

from sports_forecast.utils.log_config import get_logger

logger = get_logger(__name__)


class BaseModel(ABC):
    """
    Абстрактный базовый класс для всех моделей.

    Определяет общий интерфейс для:
    - Одиночных моделей (CatBoost, LightGBM, LogReg)
    - Ансамблей (Voting, Stacking, Weighted)

    Args:
        name: Название модели (для логирования и сохранения).
        config: Конфигурация модели из Hydra.

    Attributes:
        name: Название модели.
        config: Конфигурация модели.
        model_: Обученная модель (после fit()).
        is_fitted_: Флаг обученности модели.
        is_calibrated_: Флаг калибровки модели.

    Examples:
        >>> model = CatBoostModel(name="catboost", config=cfg)
        >>> model.fit(X_train, y_train)
        >>> proba = model.predict_proba(X_test)
    """

    def __init__(self, name: str, config: DictConfig | dict[str, Any]):
        """
        Инициализация базовой модели.

        Args:
            name: Название модели.
            config: Конфигурация модели.
        """
        self.name = name
        self.config = config
        self.model_: Any = None
        self.is_fitted_ = False
        self.is_calibrated_ = False

    @abstractmethod
    def fit(self, X: pd.DataFrame, y: pd.Series, **kwargs) -> BaseModel:
        """
        Обучить модель на данных.

        Args:
            X: Фичи для обучения.
            y: Таргет.
            **kwargs: Дополнительные параметры для fit().

        Returns:
            self: Для chaining.

        Raises:
            NotImplementedError: Должен быть реализован в наследниках.
        """
        raise NotImplementedError

    @abstractmethod
    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        """
        Предсказать вероятности классов.

        Args:
            X: Фичи для предсказания.

        Returns:
            Массив вероятностей shape (n_samples, n_classes).

        Raises:
            NotImplementedError: Должен быть реализован в наследниках.
            ValueError: Если модель не обучена.
        """
        raise NotImplementedError

    @abstractmethod
    def save(self, path: Path, version: str = "prod") -> None:
        """
        Сохранить модель на диск.

        Args:
            path: Путь для сохранения (без расширения).
            version: Версия модели ('shadow' или 'prod').

        Raises:
            NotImplementedError: Должен быть реализован в наследниках.
        """
        raise NotImplementedError

    @abstractmethod
    def load(self, path: Path) -> BaseModel:
        """
        Загрузить модель с диска.

        Args:
            path: Путь к файлу модели.

        Returns:
            self: Для chaining.

        Raises:
            NotImplementedError: Должен быть реализован в наследниках.
        """
        raise NotImplementedError

    def get_name(self) -> str:
        """
        Получить название модели.

        Returns:
            Название модели.
        """
        return self.name

    def is_fitted(self) -> bool:
        """
        Проверить, обучена ли модель.

        Returns:
            True если модель обучена, False иначе.
        """
        return self.is_fitted_


class BaseSingleModel(BaseModel):
    """
    Базовый класс для одиночных моделей (CatBoost, LightGBM, LogReg, etc.).

    Предоставляет общую логику для:
    - Инициализации модели
    - Обучения через TSCV
    - Калибровки
    - Сохранения/загрузки

    Наследники должны реализовать:
    - _create_model(): Создание модели с параметрами
    - _fit_implementation(): Обучение модели
    - _get_feature_importance() (опционально): Важность фичей

    Args:
        name: Название модели.
        config: Конфигурация модели из Hydra.
        params: Гиперпараметры модели (можно переопределить из config).

    Examples:
        >>> class CatBoostModel(BaseSingleModel):
        ...     def _create_model(self):
        ...         return CatBoostClassifier(**self.params)
        ...
        ...     def _fit_implementation(self, X, y, **fit_kwargs):
        ...         self.model_.fit(X, y, **fit_kwargs)
    """

    def __init__(
        self,
        name: str,
        config: DictConfig | dict[str, Any],
        params: dict[str, Any] | None = None,
    ):
        """
        Инициализация одиночной модели.

        Args:
            name: Название модели.
            config: Конфигурация модели.
            params: Гиперпараметры (если None, берутся из config.params).
        """
        super().__init__(name, config)

        # Гиперпараметры
        if params is not None:
            self.params = params
        elif hasattr(config, "params"):
            self.params = dict(config.params)
        else:
            self.params = {}

        # Категориальные фичи (для CatBoost, LightGBM)
        self.cat_features_: list[str] = []

        logger.debug("Инициализирована модель '%s' с параметрами: %s", name, self.params)

    @abstractmethod
    def _create_model(self) -> Any:
        """
        Создать экземпляр модели с параметрами.

        Returns:
            Экземпляр модели (CatBoostClassifier, LGBMClassifier, etc.).

        Raises:
            NotImplementedError: Должен быть реализован в наследниках.

        Examples:
            >>> def _create_model(self):
            ...     return CatBoostClassifier(**self.params)
        """
        raise NotImplementedError

    @abstractmethod
    def _fit_implementation(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        **fit_kwargs,
    ) -> None:
        """
        Реализация обучения модели.

        Вызывается из fit() после подготовки данных.

        Args:
            X: Фичи для обучения.
            y: Таргет.
            **fit_kwargs: Дополнительные параметры (eval_set, cat_features, etc.).

        Raises:
            NotImplementedError: Должен быть реализован в наследниках.

        Examples:
            >>> def _fit_implementation(self, X, y, **fit_kwargs):
            ...     self.model_.fit(X, y, **fit_kwargs)
        """
        raise NotImplementedError

    def fit(self, X: pd.DataFrame, y: pd.Series, **kwargs) -> BaseSingleModel:
        """
        Обучить модель на данных.

        Args:
            X: Фичи для обучения.
            y: Таргет.
            **kwargs: Дополнительные параметры для fit()
                (eval_set, cat_features, early_stopping_rounds, etc.).

        Returns:
            self: Для chaining.

        Examples:
            >>> model.fit(X_train, y_train, eval_set=(X_val, y_val))
        """
        logger.info("Обучаю модель '%s' на %d записях с %d фичами", self.name, len(X), X.shape[1])

        # Создаём модель если ещё не создана
        if self.model_ is None:
            self.model_ = self._create_model()
            logger.debug("Создан экземпляр модели: %s", type(self.model_).__name__)

        # Определяем категориальные фичи (для CatBoost, LightGBM)
        if "cat_features" not in kwargs:
            self.cat_features_ = [col for col in X.columns if X[col].dtype == "object"]
            if self.cat_features_:
                kwargs["cat_features"] = self.cat_features_
                logger.debug("Найдены категориальные фичи: %s", self.cat_features_)

        # Обучение
        self._fit_implementation(X, y, **kwargs)

        self.is_fitted_ = True
        logger.info("Модель '%s' успешно обучена", self.name)

        return self

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        """
        Предсказать вероятности классов.

        Args:
            X: Фичи для предсказания.

        Returns:
            Массив вероятностей shape (n_samples, n_classes).
            Для бинарной классификации возвращается (n_samples, 2).

        Raises:
            ValueError: Если модель не обучена.

        Examples:
            >>> proba = model.predict_proba(X_test)
            >>> proba[:, 1]  # Вероятность класса 1
        """
        if not self.is_fitted_:
            raise ValueError(f"Модель '{self.name}' не обучена. Вызовите fit() перед predict_proba()")

        proba = self.model_.predict_proba(X)

        # Для sklearn моделей может вернуться только один столбец для бинарной классификации
        if proba.ndim == 1:
            proba = np.column_stack([1 - proba, proba])

        return proba

    def save(self, path: Path, version: str = "prod") -> None:
        """
        Сохранить модель на диск.

        Args:
            path: Путь для сохранения (без расширения).
            version: Версия модели ('shadow' или 'prod').

        Raises:
            ValueError: Если модель не обучена.

        Examples:
            >>> model.save(Path("models/uel_kz_1/is_win"), version="shadow")
            >>> # Сохранено в: models/uel_kz_1/is_win_shadow.cbm
        """
        if not self.is_fitted_:
            raise ValueError(f"Модель '{self.name}' не обучена. Сохранять нечего.")

        # Добавляем версию к имени файла
        if version not in ["shadow", "prod"]:
            raise ValueError(f"Версия должна быть 'shadow' или 'prod', получено: {version}")

        save_path = path.parent / f"{path.name}_{version}{path.suffix}"
        save_path.parent.mkdir(parents=True, exist_ok=True)

        # Сохранение (зависит от типа модели)
        if hasattr(self.model_, "save_model"):
            # CatBoost, LightGBM
            self.model_.save_model(str(save_path))
        else:
            # sklearn models - используем joblib
            import joblib

            joblib.dump(self.model_, save_path)

        logger.info("Модель '%s' (%s) сохранена: %s", self.name, version, save_path)

    def load(self, path: Path) -> BaseSingleModel:
        """
        Загрузить модель с диска.

        Args:
            path: Путь к файлу модели.

        Returns:
            self: Для chaining.

        Raises:
            FileNotFoundError: Если файл не найден.

        Examples:
            >>> model.load(Path("models/uel_kz_1/is_win_shadow.cbm"))
        """
        if not path.exists():
            raise FileNotFoundError(f"Файл модели не найден: {path}")

        # Создаём модель если ещё не создана
        if self.model_ is None:
            self.model_ = self._create_model()

        # Загрузка (зависит от типа модели)
        if hasattr(self.model_, "load_model"):
            # CatBoost, LightGBM
            self.model_.load_model(str(path))
        else:
            # sklearn models
            import joblib

            self.model_ = joblib.load(path)

        self.is_fitted_ = True
        logger.info("Модель '%s' загружена из: %s", self.name, path)

        return self

    def get_feature_importance(self) -> pd.DataFrame | None:
        """
        Получить важность фичей (если модель поддерживает).

        Returns:
            DataFrame с колонками ['feature', 'importance']
            или None если модель не поддерживает.

        Examples:
            >>> importance = model.get_feature_importance()
            >>> if importance is not None:
            ...     print(importance.head())
        """
        if not self.is_fitted_:
            logger.warning("Модель '%s' не обучена, важность фичей недоступна", self.name)
            return None

        if hasattr(self.model_, "feature_importances_"):
            # CatBoost, LightGBM, RandomForest
            return pd.DataFrame(
                {
                    "feature": self.model_.feature_names_ if hasattr(self.model_, "feature_names_") else range(len(self.model_.feature_importances_)),
                    "importance": self.model_.feature_importances_,
                }
            ).sort_values("importance", ascending=False)

        if hasattr(self.model_, "coef_"):
            # LogisticRegression
            return pd.DataFrame(
                {
                    "feature": range(len(self.model_.coef_[0])),
                    "importance": np.abs(self.model_.coef_[0]),
                }
            ).sort_values("importance", ascending=False)

        logger.debug("Модель '%s' не поддерживает feature_importance", self.name)
        return None

