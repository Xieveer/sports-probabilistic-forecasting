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
from sports_forecast.features.generators.roster_generator import NhlRosterFeatureGenerator
from sports_forecast.features.generators.schedule_generator import NhlScheduleFeatureGenerator
from sports_forecast.features.generators.standings_generator import NhlStandingsFeatureGenerator
from sports_forecast.features.generators.streak_generator import StreakFeatureGenerator
from sports_forecast.features.generators.time_generator import TimeFeatureGenerator
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
                - generators: dict генераторов {name: config} или list конфигураций
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
        "streak": StreakFeatureGenerator,
        "ewm": EWMFeatureGenerator,
        "count": CountFeatureGenerator,
        "time": TimeFeatureGenerator,
        "nhl_schedule": NhlScheduleFeatureGenerator,
        "nhl_standings": NhlStandingsFeatureGenerator,
        "nhl_roster": NhlRosterFeatureGenerator,
    }

    # Типы, которые запускаются на WIDE данных ДО wide→long
    PRE_GENERATOR_TYPES = {
        "time",
        "nhl_schedule",
        "nhl_standings",
        "nhl_roster",
    }

    def __init__(self, config: dict[str, Any] | DictConfig):
        """
        Инициализация pipeline.

        Args:
            config: Конфигурация из YAML
        """
        self.config = config
        self.pre_generators: list = []
        self.generators: list = []
        self._init_generators()

        logger.info(
            "FeaturePipeline инициализирован: %d пре-генераторов, %d генераторов",
            len(self.pre_generators),
            len(self.generators),
        )

    def _init_generators(self) -> None:
        """
        Инициализация генераторов из конфига.

        Поддерживает два формата конфига generators:
            - **dict** (рекомендуемый): ``{name: {type: ..., ...}, ...}``
              Ключ словаря используется как fallback для type.
            - **list** (legacy): ``[{type: ..., ...}, ...]``

        Генераторы типов из ``PRE_GENERATOR_TYPES`` помещаются в
        ``self.pre_generators`` (запускаются на wide ДО wide→long),
        остальные — в ``self.generators``.

        Raises:
            ValueError: Если конфигурация некорректна.
        """
        if "generators" not in self.config:
            raise ValueError("FeaturePipeline: отсутствует поле 'generators' в конфиге")

        gen_configs = self.config["generators"]

        # Нормализация: dict → list of (key, config) pairs
        items: list[tuple[str, Any]] = []

        if isinstance(gen_configs, dict):
            # Новый формат: dict {gen_name: gen_config}
            for gen_key, gen_cfg in gen_configs.items():
                items.append((gen_key, gen_cfg))
        elif hasattr(gen_configs, "items"):
            # OmegaConf DictConfig
            for gen_key, gen_cfg in gen_configs.items():
                items.append((gen_key, gen_cfg))
        elif hasattr(gen_configs, "__iter__") and not isinstance(gen_configs, str):
            # Legacy формат: list [{type: ...}, ...]
            for i, gen_cfg in enumerate(gen_configs):
                gen_key = (
                    gen_cfg.get("type", f"generator_{i}")
                    if hasattr(gen_cfg, "get")
                    else f"generator_{i}"
                )
                items.append((gen_key, gen_cfg))
        else:
            raise ValueError("FeaturePipeline: 'generators' должен быть dict или list")

        for gen_key, gen_config in items:
            # Определяем тип генератора: явный type или ключ словаря
            if hasattr(gen_config, "get") or isinstance(gen_config, dict):
                gen_type = gen_config.get("type", gen_key)
            else:
                logger.warning(
                    "FeaturePipeline: generators['%s'] имеет невалидный формат, пропускаем",
                    gen_key,
                )
                continue

            enabled = gen_config.get("enabled", True) if hasattr(gen_config, "get") else True

            if not enabled:
                logger.info("FeaturePipeline: генератор %s отключен (enabled=False)", gen_type)
                continue

            # Получение класса генератора
            generator_class = self.GENERATOR_MAP.get(gen_type)
            if generator_class is None:
                logger.warning(
                    "FeaturePipeline: неизвестный тип генератора '%s', доступные типы: %s",
                    gen_type,
                    list(self.GENERATOR_MAP.keys()),
                )
                continue

            # Инициализация генератора
            try:
                # Конвертируем OmegaConf в обычный dict (рекурсивно)
                if hasattr(gen_config, "_metadata"):
                    # OmegaConf объект
                    gen_config_dict = OmegaConf.to_container(gen_config, resolve=True)
                elif isinstance(gen_config, dict):
                    gen_config_dict = gen_config
                else:
                    gen_config_dict = dict(gen_config)

                if gen_config_dict is None:
                    gen_config_dict = {}

                # Гарантируем наличие type в конфиге генератора
                gen_config_dict["type"] = gen_type

                generator = generator_class(gen_config_dict)  # type: ignore[abstract]

                # Разделяем pre-generators и основные
                if gen_type in self.PRE_GENERATOR_TYPES:
                    self.pre_generators.append(generator)
                    logger.info(
                        "FeaturePipeline: pre-generator %s (%d фичей)",
                        gen_type,
                        len(generator.get_feature_names()),
                    )
                else:
                    self.generators.append(generator)
                    logger.info(
                        "FeaturePipeline: generator %s (%d фичей)",
                        gen_type,
                        len(generator.get_feature_names()),
                    )
            except Exception as e:
                logger.error("FeaturePipeline: ошибка инициализации %s: %s", gen_type, e)
                raise

        total = len(self.pre_generators) + len(self.generators)
        if total == 0:
            logger.warning("FeaturePipeline: ни один генератор не был инициализирован!")

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
        logger.info("Входной датафрейм: %d строк × %d колонок", df.shape[0], df.shape[1])
        logger.info("Формат: %s", format)

        # 0. Pre-generators (на WIDE данных, ДО wide→long)
        df_wide = df.copy()
        pre_gen_columns: list[str] = []

        if self.pre_generators:
            logger.info("Пре-генераторы (%d)...", len(self.pre_generators))
            for pg in self.pre_generators:
                df_wide = pg(df_wide)
                # Только колонки, реально появившиеся в wide (пропущенный пре-ген не даёт контекст).
                if hasattr(pg, "get_context_column_names"):
                    for col in pg.get_context_column_names():
                        if col in df_wide.columns and col not in pre_gen_columns:
                            pre_gen_columns.append(col)
            logger.info("  Пре-генераторы → контекст wide→long: %s", pre_gen_columns)

        # 1. Трансформация в long format (если требуется)
        requires_long = self.config.get("requires_long", True)
        df_long = df_wide

        if requires_long and format == "wide":
            logger.info("Трансформация: wide → long...")

            # Параметры для трансформации
            context_columns_config = list(self.config.get("long_format_context_columns", []))

            # Добавляем колонки от пре-генераторов
            for col in pre_gen_columns:
                if col not in context_columns_config:
                    context_columns_config.append(col)

            # Фильтруем только те колонки, которые действительно есть в данных
            context_columns = [col for col in context_columns_config if col in df_wide.columns]

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
                context_columns = [col for col in possible_context if col in df_wide.columns]

            logger.info("  Контекстные колонки: %s", context_columns if context_columns else "нет")

            df_long = wide_to_long(df_wide, context_columns=context_columns)
            validate_long_format(df_long)

            logger.info("  wide → long: %d матчей → %d строк", df_wide.shape[0], df_long.shape[0])

        # 2. Создание базовых метрик (diff_ps, total_ps)
        create_metrics = self.config.get("create_metrics", ["diff", "total"])
        if create_metrics:
            logger.info("Создание базовых метрик: %s...", create_metrics)
            df_long = create_player_metrics(df_long, metrics=create_metrics)
            logger.info("  ✓ Базовые метрики созданы")

        # 3. Применение генераторов последовательно
        result_df = df_long.copy()
        all_features = []

        for i, generator in enumerate(self.generators, 1):
            logger.info("[%d/%d] %s...", i, len(self.generators), generator.name)

            try:
                result_df = generator(result_df)

                # Собираем имена реально сгенерированных фичей (с префиксом)
                gen_features = generator.get_prefixed_actual_feature_names(result_df)
                all_features.extend(gen_features)

                logger.info("  Сгенерировано %d фичей", len(gen_features))
            except Exception as e:
                logger.error("  Ошибка в %s: %s", generator.name, e)
                raise

        # 4. Продвигаем pre-generator колонки в фичи (f_ копии)
        #    weekday → f_weekday, hour → f_hour, и т.д.
        #    Оригиналы остаются (нужны как ключи группировки для EWM/Count).
        for pg in self.pre_generators:
            for col_name in pg.get_feature_names():
                f_col = f"f_{col_name}"
                if col_name in result_df.columns and f_col not in result_df.columns:
                    result_df[f_col] = result_df[col_name]
                    all_features.append(f_col)
                    logger.debug("Pre-gen → feature: %s → %s", col_name, f_col)

        # 5. Итоговая статистика
        elapsed = time.time() - start_time
        actual_features = get_feature_columns(result_df)
        total_expected = self.get_total_feature_count()
        total_actual = len(actual_features)
        total_skipped_contexts = sum(
            getattr(g, "_last_run_skipped_contexts", 0) for g in self.generators
        )
        features_not_created = total_expected - total_actual

        logger.info("\n" + "=" * 70)
        logger.info("ГЕНЕРАЦИЯ ФИЧЕЙ ЗАВЕРШЕНА")
        logger.info("=" * 70)
        logger.info("Время выполнения: %.2f секунд", elapsed)
        logger.info("Генераторов применено: %d", len(self.generators))
        logger.info("Фичей сгенерировано: %d", len(actual_features))
        logger.info(
            "Итоговая сводка: контекстов пропущено %d, фичей не создано %d",
            total_skipped_contexts,
            features_not_created,
        )
        logger.info(
            f"Итоговый датафрейм: {result_df.shape[0]} строк × {result_df.shape[1]} колонок"
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
        for generator in self.pre_generators + self.generators:
            total += len(generator.get_feature_names())
        return total

    def get_generator_summary(self) -> dict[str, int]:
        """
        Получить сводку по генераторам.

        Returns:
            Словарь {имя_генератора: количество_фичей}
        """
        summary = {}
        for generator in self.pre_generators + self.generators:
            gen_type = generator.config.get("type", "unknown")
            feature_count = len(generator.get_feature_names())
            summary[gen_type] = feature_count
        return summary

    def __repr__(self) -> str:
        """Строковое представление pipeline."""
        total_features = self.get_total_feature_count()
        return (
            f"FeaturePipeline("
            f"pre_generators={len(self.pre_generators)}, "
            f"generators={len(self.generators)}, "
            f"total_features={total_features})"
        )
