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

    # sklearn compatibility: указываем, что это classifier
    _estimator_type = "classifier"

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

        # Preprocessor для моделей, требующих предобработки (LogReg, Neural Networks)
        self.preprocessor_: Any = None

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

    def _preprocess_data(
        self,
        X: pd.DataFrame,
        y: pd.Series | None = None,
        fit: bool = True,
    ) -> tuple[pd.DataFrame, pd.Series | None]:
        """
        Предобработка данных перед обучением/предсказанием.

        По умолчанию ничего не делает (CatBoost, Dummy).
        Переопределяется в наследниках для моделей, требующих
        предобработки (LogReg, Neural Networks).

        Args:
            X: Фичи.
            y: Таргет (для fit=True).
            fit: Если True, обучаем preprocessor. Если False, только трансформируем.

        Returns:
            Кортеж (X_transformed, y).

        Examples:
            >>> # CatBoostModel - ничего не делает
            >>> def _preprocess_data(self, X, y=None, fit=True):
            ...     return X, y
            >>>
            >>> # LogRegModel - StandardScaler + OneHotEncoder
            >>> def _preprocess_data(self, X, y=None, fit=True):
            ...     if fit:
            ...         self.preprocessor_.fit(X)
            ...     X_transformed = self.preprocessor_.transform(X)
            ...     return X_transformed, y
        """
        return X, y

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

        # Определяем категориальные фичи (для CatBoost)
        # Для LightGBM это делается в _preprocess_data()
        if "cat_features" not in kwargs and "categorical_feature" not in kwargs:
            cat_cols = [col for col in X.columns if X[col].dtype == "object"]
            if cat_cols:
                self.cat_features_ = cat_cols
                # CatBoost использует 'cat_features', LightGBM - 'categorical_feature'
                # Определяем тип модели по классу
                if hasattr(self, "model_") and self.model_ is not None:
                    model_type = type(self.model_).__name__
                    if "CatBoost" in model_type:
                        kwargs["cat_features"] = self.cat_features_
                    elif "LGBM" in model_type:
                        kwargs["categorical_feature"] = self.cat_features_
                logger.debug("Найдены категориальные фичи: %s", self.cat_features_)

        # Предобработка данных (переопределяется в наследниках)
        X_processed, y_processed = self._preprocess_data(X, y, fit=True)

        # Обучение
        self._fit_implementation(X_processed, y_processed, **kwargs)

        self.is_fitted_ = True
        
        # Сохраняем classes_ для sklearn совместимости (для калибровки)
        if hasattr(self.model_, "classes_"):
            self.classes_ = self.model_.classes_
        
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
            raise ValueError(
                f"Модель '{self.name}' не обучена. Вызовите fit() перед predict_proba()"
            )

        # Предобработка данных (если нужна)
        X_processed, _ = self._preprocess_data(X, y=None, fit=False)

        # ВАЖНО: НЕ используем calibrated_model_ здесь чтобы избежать рекурсии!
        # CalibratedClassifierCV сам вызовет этот метод predict_proba
        proba = self.model_.predict_proba(X_processed)

        # Для sklearn моделей может вернуться только один столбец для бинарной классификации
        if proba.ndim == 1:
            proba = np.column_stack([1 - proba, proba])

        return np.asarray(proba)

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

        # Сохраняем preprocessor отдельно (если есть)
        if self.preprocessor_ is not None:
            import joblib

            preprocessor_path = path.parent / f"{path.name}_{version}_preprocessor.pkl"
            joblib.dump(self.preprocessor_, preprocessor_path)
            logger.debug("Preprocessor сохранён: %s", preprocessor_path)

        # Сохраняем calibrated_model отдельно (если есть)
        if hasattr(self, "calibrated_model_") and self.calibrated_model_ is not None:
            import joblib

            calibrated_path = path.parent / f"{path.name}_{version}_calibrated.pkl"
            joblib.dump(self.calibrated_model_, calibrated_path)
            logger.debug("Calibrated model сохранён: %s", calibrated_path)

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

        # Загружаем preprocessor (если есть)
        preprocessor_path = path.parent / f"{path.stem}_preprocessor.pkl"
        if preprocessor_path.exists():
            import joblib

            self.preprocessor_ = joblib.load(preprocessor_path)
            logger.debug("Preprocessor загружен из: %s", preprocessor_path)

        # Загружаем calibrated_model (если есть)
        calibrated_path = path.parent / f"{path.stem}_calibrated.pkl"
        if calibrated_path.exists():
            import joblib

            self.calibrated_model_ = joblib.load(calibrated_path)
            self.is_calibrated_ = True
            logger.debug("Calibrated model загружен из: %s", calibrated_path)

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
                    "feature": self.model_.feature_names_
                    if hasattr(self.model_, "feature_names_")
                    else range(len(self.model_.feature_importances_)),
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
