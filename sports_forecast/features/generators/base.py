"""
Базовый класс для всех генераторов фичей.

Определяет интерфейс для создания генераторов и общую логику.
"""

from abc import ABC, abstractmethod
from typing import Any

import pandas as pd

from sports_forecast.features.column_utils import add_feature_prefix
from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)


class BaseFeatureGenerator(ABC):
    """
    Абстрактный базовый класс для всех генераторов фичей.

    Каждый генератор должен:
    1. Читать конфигурацию из YAML
    2. Генерировать фичи на основе конфига
    3. Возвращать список сгенерированных имен фичей
    4. Автоматически добавлять префикс f_ к именам фичей
    5. Быть вызываемым (callable): generator(df) → df_with_features

    Пример наследования:
        class EWMFeatureGenerator(BaseFeatureGenerator):
            def generate(self, df: pd.DataFrame) -> pd.DataFrame:
                # Логика генерации EWM фичей
                df = df.copy()
                # ...
                return df

            def get_feature_names(self) -> List[str]:
                return ["pl_global_ewm_10", "pl_global_ewm_20"]

        # Использование:
        generator = EWMFeatureGenerator(config)
        df_with_features = generator(df)  # Вызов как функции!

    Args:
        config: Конфигурация генератора из YAML
            Обязательные поля:
                - type: str - тип генератора ('ewm', 'count', 'form')
            Опциональные поля:
                - enabled: bool - включен ли генератор (default: True)
                - add_prefix: bool - добавлять ли f_ к именам (default: True)

    Attributes:
        config: Конфигурация генератора
        enabled: Включен ли генератор
        add_prefix: Добавлять ли f_ префикс к именам фичей
        name: Имя класса генератора
    """

    def __init__(self, config: dict[str, Any]):
        """
        Инициализация генератора.

        Args:
            config: Конфигурация из YAML
        """
        self.config = config
        self.enabled = config.get("enabled", True)
        self.add_prefix = config.get("add_prefix", True)
        self.name = self.__class__.__name__

        # Валидация конфигурации
        self.validate_config()

        if not self.enabled:
            logger.info("%s: отключен (enabled=False)", self.name)

    @abstractmethod
    def generate(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Генерация фичей.

        Принимает датафрейм, добавляет в него новые колонки-фичи,
        возвращает обновленный датафрейм.

        Args:
            df: Входной датафрейм (wide или long в зависимости от генератора)

        Returns:
            Датафрейм с добавленными фичами

        Raises:
            NotImplementedError: Если метод не реализован в дочернем классе

        Notes:
            - Метод ОБЯЗАТЕЛЬНО должен быть реализован в дочернем классе
            - Метод должен работать с копией датафрейма (df.copy())
            - Имена фичей должны быть без префикса f_ (префикс добавится автоматически)
        """
        raise NotImplementedError(
            f"{self.name}.generate() должен быть реализован в дочернем классе"
        )

    @abstractmethod
    def get_feature_names(self) -> list[str]:
        """
        Возвращает список имен сгенерированных фичей.

        Returns:
            Список имен фичей БЕЗ префикса f_ (префикс добавится автоматически)

        Raises:
            NotImplementedError: Если метод не реализован в дочернем классе

        Notes:
            - Метод ОБЯЗАТЕЛЬНО должен быть реализован в дочернем классе
            - Имена возвращаются БЕЗ префикса f_
            - Порядок имен должен соответствовать порядку генерации

        Examples:
            >>> generator = EWMFeatureGenerator(config)
            >>> generator.get_feature_names()
            ['pl_global_ewm_10', 'opp_global_ewm_10', 'all_global_ewm_10_diff']
        """
        raise NotImplementedError(
            f"{self.name}.get_feature_names() должен быть реализован в дочернем классе"
        )

    def validate_config(self) -> None:
        """
        Валидация конфигурации генератора.

        Проверяет наличие обязательных полей и корректность значений.
        Может быть переопределен в дочерних классах для специфичных проверок.

        Raises:
            ValueError: Если конфигурация некорректна
        """
        if "type" not in self.config:
            raise ValueError(f"{self.name}: отсутствует обязательное поле 'type'")

    def get_expected_feature_names(self) -> list[str]:
        """
        Возвращает список всех имён фичей, которые генератор может создать по конфигу.

        Не учитывает пропуск контекстов из-за отсутствующих колонок в данных.
        Для обратной совместимости по умолчанию делегирует в get_feature_names().

        Returns:
            Список имён фичей без префикса f_
        """
        return self.get_feature_names()

    def get_actual_feature_names(self, _df: pd.DataFrame) -> list[str]:
        """
        Возвращает список имён фичей, которые будут реально сгенерированы для df.

        Учитывает пропуск контекстов из-за отсутствующих колонок. Генераторы,
        которые не пропускают контексты (form, time), по умолчанию возвращают
        get_expected_feature_names(). EWM и Count переопределяют метод.

        Args:
            _df: Датафрейм, для которого планируется генерация (до вызова generate).
                В базовой реализации не используется.

        Returns:
            Список имён фичей без префикса f_
        """
        return self.get_expected_feature_names()

    def get_prefixed_feature_names(self) -> list[str]:
        """
        Возвращает список имен фичей С префиксом f_.

        Returns:
            Список имен фичей с префиксом f_

        Examples:
            >>> generator = EWMFeatureGenerator(config)
            >>> generator.get_prefixed_feature_names()
            ['f_pl_global_ewm_10', 'f_opp_global_ewm_10', 'f_all_global_ewm_10_diff']
        """
        names = self.get_feature_names()
        if self.add_prefix:
            return [add_feature_prefix(name) for name in names]
        return names

    def get_prefixed_actual_feature_names(self, df: pd.DataFrame) -> list[str]:
        """
        Возвращает список имён фичей с префиксом f_, реально создаваемых для df.

        Args:
            df: Датафрейм после применения генератора (или с теми же колонками).

        Returns:
            Список имён фичей с префиксом f_
        """
        names = self.get_actual_feature_names(df)
        if self.add_prefix:
            return [add_feature_prefix(name) for name in names]
        return names

    def __call__(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Применить генератор к датафрейму (callable interface).

        Позволяет использовать генератор как функцию: generator(df).
        Обертка вокруг generate(), которая:
        1. Проверяет что генератор включен
        2. Вызывает generate()
        3. Автоматически добавляет префикс f_ к сгенерированным колонкам
        4. Логирует информацию о генерации

        Args:
            df: Входной датафрейм

        Returns:
            Датафрейм с добавленными фичами (с префиксом f_)

        Notes:
            Используется __call__ вместо apply/transform для избежания:
            - Конфликтов с pandas.DataFrame.apply()
            - Ложных ожиданий от sklearn (нет наследования от BaseEstimator)

        Examples:
            >>> generator = EWMFeatureGenerator(config)
            >>> df_with_features = generator(df)  # Вызов как функции
        """
        if not self.enabled:
            logger.info("%s: пропущен (disabled)", self.name)
            return df

        logger.info("%s: начало генерации фичей...", self.name)

        # Генерация фичей (без префикса)
        result = self.generate(df)

        # Добавление префикса f_ к новым колонкам
        if self.add_prefix:
            feature_names = self.get_feature_names()
            rename_map = {name: add_feature_prefix(name) for name in feature_names}

            # Переименовываем только те колонки, которые действительно есть
            existing_renames = {
                old: new for old, new in rename_map.items() if old in result.columns
            }

            if existing_renames:
                result = result.rename(columns=existing_renames)
                logger.debug(
                    "%s: добавлен префикс f_ к %d колонкам", self.name, len(existing_renames)
                )

        features_count = len(self.get_actual_feature_names(result))
        logger.info("%s: сгенерировано %d фичей", self.name, features_count)

        return result

    def __repr__(self) -> str:
        """Строковое представление генератора."""
        status = "enabled" if self.enabled else "disabled"
        return f"{self.name}(type={self.config.get('type')}, status={status})"
