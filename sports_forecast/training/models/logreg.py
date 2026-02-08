"""
Logistic Regression модель с поддержкой L1/L2 регуляризации.

Простая линейная модель, отлично калиброванная по умолчанию.
Используется как:
- Baseline для сравнения
- Мета-модель в стэкинге

Важно:
    LogReg требует предобработки данных:
    - StandardScaler для числовых фичей
    - OneHotEncoder для категориальных фичей

Примеры:
    >>> logreg = LogRegModel(name="logreg", config=cfg)
    >>> logreg.fit(X_train, y_train)
    >>> proba = logreg.predict_proba(X_test)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
from omegaconf import DictConfig
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from sports_forecast.training.base import BaseSingleModel
from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)


class LogRegModel(BaseSingleModel):
    """
    Logistic Regression модель для бинарной классификации.

    Использует sklearn.linear_model.LogisticRegression с:
    - L1/L2 регуляризацией
    - Solver 'saga' (поддерживает и L1, и L2)
    - Отличной калибровкой по умолчанию

    Args:
        name: Название модели (по умолчанию "logreg").
        config: Конфигурация модели из Hydra.
        params: Гиперпараметры LogisticRegression.

    Attributes:
        model_: LogisticRegression.

    Examples:
        >>> logreg = LogRegModel(name="logreg", config=cfg.model)
        >>> logreg.fit(X_train, y_train)
        >>> proba = logreg.predict_proba(X_test)

    Notes:
        LogisticRegression хорошо откалиброван по умолчанию.
        ECE обычно < 0.1, калибровка не требуется.
    """

    def __init__(
        self,
        name: str = "logreg",
        config: DictConfig | dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ):
        """
        Инициализация Logistic Regression модели.

        Args:
            name: Название модели.
            config: Конфигурация модели.
            params: Гиперпараметры LogisticRegression.
        """
        # Параметры по умолчанию для LogisticRegression
        default_params = {
            "penalty": "l2",
            "C": 1.0,
            "solver": "saga",  # Поддерживает и L1, и L2
            "max_iter": 1000,
            "random_state": 777,
            "verbose": 0,
            "n_jobs": -1,  # Используем все ядра
        }

        if params is None and config is not None and hasattr(config, "params"):
            params = dict(config.params)
        elif params is None:
            params = default_params
        else:
            params = {**default_params, **params}

        super().__init__(name=name, config=config or {}, params=params)

        # Храним имена числовых и категориальных фичей
        self.numeric_features_: list[str] = []
        self.categorical_features_: list[str] = []

        logger.info("Инициализирован LogRegModel с параметрами: %s", self.params)

    def _create_model(self) -> LogisticRegression:
        """
        Создать экземпляр LogisticRegression.

        Returns:
            Экземпляр LogisticRegression с параметрами из self.params.
        """
        return LogisticRegression(**self.params)

    def _preprocess_data(
        self,
        features: pd.DataFrame,
        target: pd.Series | None = None,
        fit: bool = True,
    ) -> tuple[pd.DataFrame, pd.Series | None]:
        """
        Предобработка данных для LogisticRegression.

        Применяет:
        - StandardScaler для числовых фичей
        - OneHotEncoder для категориальных фичей

        Args:
            features: Фичи.
            target: Таргет (для fit=True).
            fit: Если True, обучаем preprocessor. Если False, только трансформируем.

        Returns:
            Кортеж (features_transformed, target).

        Examples:
            >>> features_transformed, y = model._preprocess_data(X_train, y_train, fit=True)
        """
        if fit:
            # Определяем типы фичей
            self.numeric_features_ = [
                col for col in features.columns if features[col].dtype != "object"
            ]
            self.categorical_features_ = [
                col for col in features.columns if features[col].dtype == "object"
            ]

            logger.debug(
                "LogReg preprocessing: %d числовых, %d категориальных фичей",
                len(self.numeric_features_),
                len(self.categorical_features_),
            )

            # Создаём preprocessor
            transformers = []

            if self.numeric_features_:
                # Pipeline для числовых фичей: Imputer → Scaler
                numeric_pipeline = Pipeline(
                    [
                        ("imputer", SimpleImputer(strategy="mean")),
                        ("scaler", StandardScaler()),
                    ]
                )
                transformers.append(("num", numeric_pipeline, self.numeric_features_))

            if self.categorical_features_:
                # Pipeline для категориальных фичей: Imputer → OneHot
                categorical_pipeline = Pipeline(
                    [
                        ("imputer", SimpleImputer(strategy="constant", fill_value="missing")),
                        ("onehot", OneHotEncoder(handle_unknown="ignore", sparse_output=False)),
                    ]
                )
                transformers.append(("cat", categorical_pipeline, self.categorical_features_))

            if not transformers:
                # Нет фичей для обработки (странно, но обработаем)
                logger.warning("LogReg: не найдено фичей для предобработки!")
                return features, target

            self.preprocessor_ = ColumnTransformer(
                transformers=transformers,
                remainder="drop",  # Остальные колонки удаляем
            )

            # Обучаем preprocessor
            features_transformed = self.preprocessor_.fit_transform(features)

            logger.debug(
                "LogReg: данные предобработаны, shape: %s -> %s",
                features.shape,
                features_transformed.shape,
            )

        else:
            # Только трансформируем
            if self.preprocessor_ is None:
                raise ValueError("Preprocessor не обучен. Вызовите fit() сначала.")

            features_transformed = self.preprocessor_.transform(features)

        # Преобразуем обратно в DataFrame (для совместимости)
        # Для LogisticRegression это необязательно, но для других моделей может быть полезно
        if hasattr(self.preprocessor_, "get_feature_names_out"):
            feature_names = self.preprocessor_.get_feature_names_out()
            features_transformed = pd.DataFrame(
                features_transformed,
                columns=feature_names,
                index=features.index,
            )
        else:
            # Fallback (для старых версий sklearn)
            features_transformed = pd.DataFrame(
                features_transformed,
                index=features.index,
            )

        return features_transformed, target

    def _fit_implementation(
        self,
        features: pd.DataFrame,
        target: pd.Series,
        **fit_kwargs,
    ) -> None:
        """
        Обучить Logistic Regression модель.

        Args:
            features: Фичи для обучения.
            target: Таргет.
            **fit_kwargs: Дополнительные параметры (игнорируются для LogReg).

        Examples:
            >>> model._fit_implementation(X_train, y_train)
        """
        # LogReg не поддерживает eval_set, поэтому игнорируем fit_kwargs
        logger.info("Начинаю обучение LogisticRegression...")
        self.model_.fit(features, target)

        logger.info("LogisticRegression обучена: %d итераций", self.model_.n_iter_[0])

    def save(self, path: Path, version: str = "prod") -> None:
        """
        Сохранить LogisticRegression модель.

        Args:
            path: Путь для сохранения (без расширения).
            version: Версия модели ('shadow' или 'prod').

        Examples:
            >>> model.save(Path("models/uel_kz_1/is_win"), version="shadow")
            >>> # Сохранено в: models/uel_kz_1/is_win_shadow.pkl
        """
        if not self.is_fitted_:
            raise ValueError(f"Модель '{self.name}' не обучена. Сохранять нечего.")

        if version not in ["shadow", "prod"]:
            raise ValueError(f"Версия должна быть 'shadow' или 'prod', получено: {version}")

        # sklearn модели используем joblib для сохранения
        import joblib

        # path — это директория модели (models/tournament/spec/alg_feat/)
        path.mkdir(parents=True, exist_ok=True)
        save_path = path / f"{path.name}_{version}.pkl"

        joblib.dump(self.model_, save_path)

        # Сохраняем preprocessor отдельно (если есть)
        if self.preprocessor_ is not None:
            preprocessor_path = path / f"{path.name}_{version}_preprocessor.pkl"
            joblib.dump(self.preprocessor_, preprocessor_path)
            logger.debug("Preprocessor сохранён: %s", preprocessor_path)

        logger.info(
            "LogisticRegression модель '%s' (%s) сохранена: %s", self.name, version, save_path
        )

    def load(self, path: Path) -> LogRegModel:
        """
        Загрузить LogisticRegression модель.

        Args:
            path: Путь к файлу модели (.pkl).

        Returns:
            self: Для chaining.

        Examples:
            >>> model.load(Path("models/uel_kz_1/is_win_shadow.pkl"))
        """
        if not path.exists():
            raise FileNotFoundError(f"Файл модели не найден: {path}")

        import joblib

        self.model_ = joblib.load(path)
        self.is_fitted_ = True

        # Загружаем preprocessor (если есть)
        preprocessor_path = path.parent / f"{path.stem}_preprocessor.pkl"
        if preprocessor_path.exists():
            self.preprocessor_ = joblib.load(preprocessor_path)
            logger.debug("Preprocessor загружен из: %s", preprocessor_path)

        logger.info("LogisticRegression модель '%s' загружена из: %s", self.name, path)
        return self

    def get_feature_importance(self) -> pd.DataFrame:
        """
        Получить важность фичей из LogisticRegression (коэффициенты).

        Returns:
            DataFrame с колонками ['feature', 'importance'],
            отсортированный по убыванию важности (по модулю коэффициентов).

        Raises:
            ValueError: Если модель не обучена.

        Examples:
            >>> importance = model.get_feature_importance()
            >>> print(importance.head(10))  # Топ-10 фичей по важности
        """
        if not self.is_fitted_:
            raise ValueError(f"Модель '{self.name}' не обучена. Важность фичей недоступна.")

        # Коэффициенты (берём по модулю для важности)
        coeffs = self.model_.coef_[0]
        feature_names = self.model_.feature_names_in_

        return (
            pd.DataFrame(
                {
                    "feature": feature_names,
                    "importance": coeffs,  # Можно взять abs(coeffs) для модуля
                }
            )
            .sort_values("importance", ascending=False, key=abs)
            .reset_index(drop=True)
        )
