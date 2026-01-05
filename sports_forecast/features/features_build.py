"""
Модуль генерации фичей (processed-слой) с поддержкой Feature Generation System.

Назначение:
    Преобразовать промежуточные данные (interim) в датасеты для обучения,
    используя Feature Generation System или старую логику (для совместимости).

Слой данных:
    Вход:  data/interim/{tournament}/matches_interim.parquet
    Выход:
        NEW SYSTEM (features/*.yaml с generators):
        - data/processed/{tournament}/train_wide.parquet (для моделей тотала)
        - data/processed/{tournament}/train_long.parquet (для моделей победителя)
        - data/processed/{tournament}/inference_wide.parquet
        - data/processed/{tournament}/inference_long.parquet

        OLD SYSTEM (features/basic_old.yaml):
        - data/processed/{tournament}/train.parquet
        - data/processed/{tournament}/inference.parquet

Использование нового Feature Pipeline:
    Если в конфиге features есть секция 'generators', используется FeaturePipeline.
    Иначе используется старая логика (basic_old.yaml).

Пример:
    # С новым Feature Pipeline
    uv run python -m sports_forecast.features.features_build

Конфигурация:
    - ``conf/features/basic.yaml`` или ``conf/features/advanced.yaml``
    - ``conf/paths.yaml``
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from omegaconf import DictConfig, OmegaConf

from sports_forecast.features.long_format import long_to_wide
from sports_forecast.features.pipeline import FeaturePipeline
from sports_forecast.utils.log_config import configure_logging, get_logger

PROJECT_ROOT = Path(__file__).resolve().parents[2]
logger = get_logger(__name__)


def use_feature_pipeline(cfg: DictConfig) -> bool:
    """
    Определить какую систему генерации фичей использовать.

    Args:
        cfg: Hydra конфиг

    Returns:
        True если использовать FeaturePipeline, False если старую логику
    """
    # Проверяем наличие секции generators в features
    if hasattr(cfg, "features") and hasattr(cfg.features, "generators"):
        return True
    return False


def process_tournament_new(
    tournament_name: str,
    interim_root: Path,
    processed_root: Path,
    features_cfg: DictConfig,
) -> None:
    """
    Обработка турнира с использованием НОВОГО Feature Generation System.

    Сохраняет ДВА формата:
        - train_wide.parquet / inference_wide.parquet (для тоталов)
        - train_long.parquet / inference_long.parquet (для победителей)

    Args:
        tournament_name: Имя турнира
        interim_root: Корневая директория interim данных
        processed_root: Корневая директория processed данных
        features_cfg: Конфигурация фичей
    """
    logger.info("=" * 70)
    logger.info("ТУРНИР: %s (Feature Generation System)", tournament_name)
    logger.info("=" * 70)

    # 1. Загрузка данных
    input_path = interim_root / tournament_name / "matches_interim.parquet"
    if not input_path.exists():
        logger.warning("Файл %s не найден, пропускаю турнир %s", input_path, tournament_name)
        return

    df = pd.read_parquet(input_path)
    logger.info("Загружено: %s (%d строк, %d колонок)", input_path, len(df), len(df.columns))

    # 2. Создание Feature Pipeline
    logger.info("\nИнициализация Feature Pipeline...")
    pipeline = FeaturePipeline(dict(features_cfg))
    logger.info("  ✓ Pipeline готов: %s", pipeline)

    # Показываем сводку
    summary = pipeline.get_generator_summary()
    logger.info("  Генераторы:")
    for gen_type, count in summary.items():
        logger.info("    - %s: %d фичей", gen_type, count)

    # 3. Генерация фичей (в long format)
    logger.info("\nГенерация фичей...")
    df_long, feature_names = pipeline.generate_features(df, format="wide")
    logger.info("  ✓ Сгенерировано %d фичей", len(feature_names))

    # 4. Создание wide format
    logger.info("\nСоздание wide format...")
    df_wide = long_to_wide(df_long, aggregate_features=True)
    logger.info("  ✓ Wide format: %d строк (матчей)", len(df_wide))

    # 5. Разделение на train и inference
    if "status" not in df_long.columns:
        logger.warning("Колонка 'status' отсутствует, сохраняю все данные как train")
        train_long = df_long
        train_wide = df_wide
        inference_long = pd.DataFrame()
        inference_wide = pd.DataFrame()
    else:
        # Long format
        train_long = df_long[df_long["status"] == "finished"].copy()
        inference_long = df_long[df_long["status"] == "upcoming"].copy()

        # Wide format (по id)
        train_ids = train_long["id"].unique()
        inference_ids = inference_long["id"].unique()

        train_wide = df_wide[df_wide["id"].isin(train_ids)].copy()
        inference_wide = df_wide[df_wide["id"].isin(inference_ids)].copy()

        logger.info(
            "  Train: %d строк (long), %d матчей (wide)",
            len(train_long),
            len(train_wide),
        )
        logger.info(
            "  Inference: %d строк (long), %d матчей (wide)",
            len(inference_long),
            len(inference_wide),
        )

    # 6. Сохранение
    output_dir = processed_root / tournament_name
    output_dir.mkdir(parents=True, exist_ok=True)

    # Train
    train_long_path = output_dir / "train_long.parquet"
    train_wide_path = output_dir / "train_wide.parquet"

    train_long.to_parquet(train_long_path, index=False, engine="pyarrow", compression="snappy")
    train_wide.to_parquet(train_wide_path, index=False, engine="pyarrow", compression="snappy")

    logger.info(
        "✓ Train сохранен:\n    - %s (%d строк, %.2f MB)\n    - %s (%d строк, %.2f MB)",
        train_long_path,
        len(train_long),
        train_long_path.stat().st_size / (1024 * 1024),
        train_wide_path,
        len(train_wide),
        train_wide_path.stat().st_size / (1024 * 1024),
    )

    # Inference
    if len(inference_long) > 0:
        inference_long_path = output_dir / "inference_long.parquet"
        inference_wide_path = output_dir / "inference_wide.parquet"

        inference_long.to_parquet(
            inference_long_path, index=False, engine="pyarrow", compression="snappy"
        )
        inference_wide.to_parquet(
            inference_wide_path, index=False, engine="pyarrow", compression="snappy"
        )

        logger.info(
            "✓ Inference сохранен:\n    - %s (%d строк)\n    - %s (%d строк)",
            inference_long_path,
            len(inference_long),
            inference_wide_path,
            len(inference_wide),
        )

    logger.info("=" * 70)


def process_tournament_old(
    tournament_name: str,
    interim_root: Path,
    processed_root: Path,
    features_cfg: DictConfig,
    paths_cfg: DictConfig,
) -> None:
    """
    Обработка турнира со СТАРОЙ логикой (для совместимости).

    DEPRECATED: Используйте новый Feature Generation System.

    Args:
        tournament_name: Имя турнира
        interim_root: Корневая директория interim данных
        processed_root: Корневая директория processed данных
        features_cfg: Конфигурация фичей (basic_old.yaml)
        paths_cfg: Конфигурация путей
    """
    logger.warning("Используется СТАРАЯ система генерации фичей для турнира %s", tournament_name)
    logger.warning("Рекомендуется мигрировать на новый Feature Generation System")

    # Импортируем старую логику
    from sports_forecast.features.features_build_old import (
        process_tournament as process_tournament_legacy,
    )

    process_tournament_legacy(tournament_name, interim_root, processed_root, features_cfg)


def process_all_tournaments(cfg: DictConfig) -> None:
    """
    Обработка всех турниров.

    Args:
        cfg: Полный Hydra конфиг
    """
    # Загрузка paths конфига
    paths_config_path = PROJECT_ROOT / "conf" / "paths.yaml"
    paths_cfg = OmegaConf.load(paths_config_path)

    interim_root = PROJECT_ROOT / paths_cfg.paths.interim_dir
    processed_root = PROJECT_ROOT / paths_cfg.paths.processed_dir

    # Определение системы фичей
    use_new_system = use_feature_pipeline(cfg)

    if use_new_system:
        logger.info("🚀 Используется Feature Generation System")
        logger.info("   Конфиг: %s", cfg.features.get("_target_", "N/A"))
    else:
        logger.info("⚠️  Используется старая система фичей (basic_old.yaml)")

    # Поиск турниров
    if not interim_root.exists():
        logger.error("Директория %s не существует", interim_root)
        return

    tournament_dirs = [d for d in interim_root.iterdir() if d.is_dir()]
    if not tournament_dirs:
        logger.warning("Не найдено турниров в %s", interim_root)
        return

    logger.info("Найдено турниров: %d", len(tournament_dirs))
    logger.info("Турниры: %s", [d.name for d in tournament_dirs])

    # Обработка каждого турнира
    for tournament_dir in sorted(tournament_dirs):
        tournament_name = tournament_dir.name

        try:
            if use_new_system:
                process_tournament_new(
                    tournament_name,
                    interim_root,
                    processed_root,
                    cfg.features,
                )
            else:
                process_tournament_old(
                    tournament_name,
                    interim_root,
                    processed_root,
                    cfg.features,
                    paths_cfg,
                )
        except Exception as e:
            logger.error("Ошибка обработки турнира %s: %s", tournament_name, e, exc_info=True)
            continue


@configure_logging
def run(cfg: DictConfig) -> None:
    """
    Entry point для генерации фичей.

    Args:
        cfg: Hydra конфигурация

    Examples:
        # Базовый набор фичей
        python -m sports_forecast.features.features_build features=basic

        # Продвинутый набор фичей  
        python -m sports_forecast.features.features_build features=advanced

        # Старая система
        python -m sports_forecast.features.features_build features=basic_old
    """
    logger.info("=" * 70)
    logger.info("FEATURE GENERATION")
    logger.info("=" * 70)

    # Загрузка конфига фичей
    features_file = cfg.get("features_file", "conf/features/basic.yaml")
    logger.info("Конфиг фичей: %s", features_file)

    if not hasattr(cfg, "features"):
        # Загружаем конфиг фичей явно
        features_path = PROJECT_ROOT / features_file
        if not features_path.exists():
            logger.error("Файл конфигурации фичей не найден: %s", features_path)
            return

        features_cfg = OmegaConf.load(features_path)
        cfg.features = features_cfg
        logger.info("Конфиг фичей загружен из %s", features_path)

    process_all_tournaments(cfg)

    logger.info("=" * 70)
    logger.info("✅ ГЕНЕРАЦИЯ ФИЧЕЙ ЗАВЕРШЕНА")
    logger.info("=" * 70)


if __name__ == "__main__":
    import hydra

    @hydra.main(version_base=None, config_path="../../conf", config_name="config")
    def main(cfg: DictConfig) -> None:
        run(cfg)

    main()
