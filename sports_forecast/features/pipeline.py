"""
Feature Pipeline - оркестратор генерации фичей.

Управляет процессом генерации фичей:
1. Читает конфигурацию (YAML)
2. Инициализирует генераторы
3. Применяет генераторы последовательно
4. Управляет форматами данных (wide ↔ long)
5. Логирует процесс и результаты

Пример использования:
    >>> from pathlib import Path
    >>> config = OmegaConf.load("conf/features/advanced.yaml")
    >>> pipeline = FeaturePipeline(config)
    >>> df_with_features, feature_names = pipeline.generate_features(df)
"""

import time
from typing import Any

import pandas as pd
from omegaconf import DictConfig, OmegaConf

from sports_forecast.features.column_utils import get_feature_columns
from sports_forecast.features.generators.count_generator import CountFeatureGenerator
from sports_forecast.features.generators.ewm_generator import EWMFeatureGenerator
from sports_forecast.features.generators.form_generator import FormFeatureGenerator
from sports_forecast.features.long_format import (
    create_player_metrics,
    validate_long_format,
    wide_to_long,
)
from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)


class FeaturePipeline:
    """
    Оркестратор генерации фичей.

    Читает конфиг, создает генераторы, применяет их последовательно.

    Args:
        config: Конфигурация из features/*.yaml
            Обязательные поля:
                - generators: список конфигураций генераторов
            Опциональные поля:
                - requires_long: bool - требуется ли long format (default: True)
                - feature_prefix: str - префикс для фичей (default: "f_")
                - create_metrics: list - метрики для создания (default: ["diff", "total"])
                - long_format_mapping: dict - маппинг для wide_to_long

    Attributes:
        config: Конфигурация pipeline
        generators: Список инициализированных генераторов
    """

    # Маппинг типов генераторов на классы
    GENERATOR_MAP = {
        "form": FormFeatureGenerator,
        "ewm": EWMFeatureGenerator,
        "count": CountFeatureGenerator,
    }

    def __init__(self, config: dict[str, Any] | DictConfig):
        """
        Инициализация pipeline.

        Args:
            config: Конфигурация из YAML
        """
        self.config = config
        self.generators = self._init_generators()

        logger.info(f"FeaturePipeline инициализирован: {len(self.generators)} генераторов")

    def _init_generators(self) -> list:
        """
        Инициализация генераторов из конфига.

        Returns:
            Список инициализированных генераторов

        Raises:
            ValueError: Если конфигурация некорректна
        """
        if "generators" not in self.config:
            raise ValueError("FeaturePipeline: отсутствует поле 'generators' в конфиге")

        generators = []
        gen_configs = self.config["generators"]

        # Поддержка OmegaConf ListConfig
        if hasattr(gen_configs, "__iter__") and not isinstance(gen_configs, (str, dict)):
            # Это list-подобный объект (list, tuple, ListConfig)
            pass
        else:
            raise ValueError("FeaturePipeline: 'generators' должен быть списком")

        for i, gen_config in enumerate(gen_configs):
            # Валидация конфига генератора
            if "type" not in gen_config:
                logger.warning(f"FeaturePipeline: generators[{i}] не содержит 'type', пропускаем")
                continue

            gen_type = gen_config["type"]
            enabled = gen_config.get("enabled", True)

            if not enabled:
                logger.info(f"FeaturePipeline: генератор {gen_type} отключен (enabled=False)")
                continue

            # Получение класса генератора
            generator_class = self.GENERATOR_MAP.get(gen_type)
            if generator_class is None:
                logger.warning(
                    f"FeaturePipeline: неизвестный тип генератора '{gen_type}', "
                    f"доступные типы: {list(self.GENERATOR_MAP.keys())}"
                )
                continue

            # Инициализация генератора
            try:
                # Конвертируем OmegaConf в обычный dict (рекурсивно)
                gen_config_dict = OmegaConf.to_container(gen_config, resolve=True)
                if gen_config_dict is None:
                    gen_config_dict = {}
                generator = generator_class(gen_config_dict)  # type: ignore[abstract]
                generators.append(generator)

                feature_count = len(generator.get_feature_names())
                logger.info(f"FeaturePipeline: ✓ {gen_type} ({feature_count} фичей)")
            except Exception as e:
                logger.error(f"FeaturePipeline: ошибка инициализации {gen_type}: {e}")
                raise

        if len(generators) == 0:
            logger.warning("FeaturePipeline: ни один генератор не был инициализирован!")

        return generators

    def generate_features(
        self, df: pd.DataFrame, format: str = "wide"
    ) -> tuple[pd.DataFrame, list[str]]:
        """
        Генерация всех фичей.

        Args:
            df: Входной датафрейм (wide или long)
            format: Формат входных данных ("wide" или "long")

        Returns:
            Tuple[датафрейм с фичами, список имен фичей с префиксом f_]

        Raises:
            ValueError: Если формат данных некорректен

        Examples:
            >>> pipeline = FeaturePipeline(config)
            >>> df_with_features, feature_names = pipeline.generate_features(df, format="wide")
            >>> len(feature_names)
            1000+
        """
        start_time = time.time()

        logger.info("=" * 70)
        logger.info("НАЧАЛО ГЕНЕРАЦИИ ФИЧЕЙ")
        logger.info("=" * 70)
        logger.info(f"Входной датафрейм: {df.shape[0]} строк × {df.shape[1]} колонок")
        logger.info(f"Формат: {format}")

        # 1. Трансформация в long format (если требуется)
        requires_long = self.config.get("requires_long", True)
        df_long = df.copy()

        if requires_long and format == "wide":
            logger.info("Трансформация: wide → long...")

            # Параметры для трансформации
            context_columns_config = self.config.get("long_format_context_columns", [])

            # Фильтруем только те колонки, которые действительно есть в данных
            context_columns = [col for col in context_columns_config if col in df.columns]

            # Если ничего не указано, автоматически ищем
            if not context_columns:
                possible_context = [
                    "tour_num",
                    "tour_match_num",
                    "weekday",
                    "hour",
                    "time_of_day",
                    "tour_name",
                ]
                context_columns = [col for col in possible_context if col in df.columns]

            # ОБЯЗАТЕЛЬНЫЙ параметр: атрибут для идентификации участника
            player_id_attr = self.config.get("player_id_attr")
            if player_id_attr is None:
                raise ValueError(
                    "Параметр 'player_id_attr' обязателен в конфиге фичей. "
                    "Укажите атрибут для идентификации участника (например, 'short_name_en', 'name', 'team')"
                )

            logger.info(f"  Контекстные колонки: {context_columns if context_columns else 'нет'}")
            logger.info(f"  ID участника: {player_id_attr}")

            df_long = wide_to_long(
                df, context_columns=context_columns, player_id_attr=player_id_attr
            )
            validate_long_format(df_long)

            logger.info(f"  ✓ wide → long: {df.shape[0]} матчей → {df_long.shape[0]} строк")

        # 2. Создание базовых метрик (diff_ps, total_ps)
        create_metrics = self.config.get("create_metrics", ["diff", "total"])
        if create_metrics:
            logger.info(f"Создание базовых метрик: {create_metrics}...")
            df_long = create_player_metrics(df_long, metrics=create_metrics)
            logger.info("  ✓ Базовые метрики созданы")

        # 3. Применение генераторов последовательно
        result_df = df_long.copy()
        all_features = []

        for i, generator in enumerate(self.generators, 1):
            logger.info(f"\n[{i}/{len(self.generators)}] {generator.name}...")

            try:
                result_df = generator(result_df)

                # Собираем имена сгенерированных фичей (с префиксом)
                gen_features = generator.get_prefixed_feature_names()
                all_features.extend(gen_features)

                logger.info(f"  ✓ Сгенерировано {len(gen_features)} фичей")
            except Exception as e:
                logger.error(f"  ✗ Ошибка в {generator.name}: {e}")
                raise

        # 4. Итоговая статистика
        elapsed = time.time() - start_time
        actual_features = get_feature_columns(result_df)

        logger.info("\n" + "=" * 70)
        logger.info("ГЕНЕРАЦИЯ ФИЧЕЙ ЗАВЕРШЕНА")
        logger.info("=" * 70)
        logger.info(f"Время выполнения: {elapsed:.2f} секунд")
        logger.info(f"Генераторов применено: {len(self.generators)}")
        logger.info(f"Фичей сгенерировано: {len(actual_features)}")
        logger.info(
            f"Итоговый датафрейм: {result_df.shape[0]} строк × {result_df.shape[1]} колонок"
        )

        # Проверка на расхождение
        if len(actual_features) != len(all_features):
            logger.warning(
                f"Расхождение: ожидалось {len(all_features)} фичей, создано {len(actual_features)}"
            )

        logger.info("=" * 70)

        return result_df, actual_features

    def get_total_feature_count(self) -> int:
        """
        Получить общее количество фичей, которые будут сгенерированы.

        Returns:
            Общее количество фичей
        """
        total = 0
        for generator in self.generators:
            total += len(generator.get_feature_names())
        return total

    def get_generator_summary(self) -> dict[str, int]:
        """
        Получить сводку по генераторам.

        Returns:
            Словарь {имя_генератора: количество_фичей}
        """
        summary = {}
        for generator in self.generators:
            gen_type = generator.config.get("type", "unknown")
            feature_count = len(generator.get_feature_names())
            summary[gen_type] = feature_count
        return summary

    def __repr__(self) -> str:
        """Строковое представление pipeline."""
        total_features = self.get_total_feature_count()
        return (
            f"FeaturePipeline(generators={len(self.generators)}, total_features={total_features})"
        )
