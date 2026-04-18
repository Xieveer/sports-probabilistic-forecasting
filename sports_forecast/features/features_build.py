"""
Модуль генерации фичей (processed-слой) через Feature Generation System.

Назначение:
    Преобразовать промежуточные данные (interim) в датасеты для обучения
    с использованием FeaturePipeline (генераторы: form, EWM, count).

Слой данных:
    Вход:  data/interim/{tournament}/matches_interim.parquet
    Выход:
        - data/processed/{tournament}/train_wide.parquet (для моделей тотала)
        - data/processed/{tournament}/train_long.parquet (для моделей победителя)
        - data/processed/{tournament}/inference_wide.parquet
        - data/processed/{tournament}/inference_long.parquet

Пример:
    uv run python -m sports_forecast.features.features_build

Конфигурация:
    - ``conf/features/basic.yaml`` или ``conf/features/advanced.yaml``
    - ``conf/paths.yaml``
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from omegaconf import DictConfig

from sports_forecast.features.long_format import long_to_wide
from sports_forecast.features.pipeline import FeaturePipeline
from sports_forecast.features.rolling_contexts import materialize_features_config
from sports_forecast.utils.log_config import configure_logging, get_logger


PROJECT_ROOT = Path(__file__).resolve().parents[2]
logger = get_logger(__name__)


def process_tournament_new(
    tournament_name: str,
    interim_root: Path,
    processed_root: Path,
    features_cfg: DictConfig,
    tournament_cfg: DictConfig | None = None,
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
        tournament_cfg: Конфиг турнира (sport → rolling_context_names для rolling library)
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

    # Политика The Odds API: линии в interim для офлайн-анализа, но не во входе FeaturePipeline
    odds_drop = [c for c in df.columns if str(c).startswith("pinnacle_")]
    if odds_drop:
        df = df.drop(columns=odds_drop)
        logger.info(
            "Исключены %d колонок pinnacle_* из генерации фичей (политика odds → не в модель)",
            len(odds_drop),
        )

    # 2. Создание Feature Pipeline
    logger.info("\nИнициализация Feature Pipeline...")
    features_dict = materialize_features_config(features_cfg, tournament_cfg=tournament_cfg)
    pipeline = FeaturePipeline(features_dict)
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

    # 5.5. Quality Gate: валидация processed-данных
    from sports_forecast.validation.gates import validate_processed

    validate_processed(
        train_long, data_format="long", tournament=tournament_name, raise_on_error=False
    )
    if len(train_wide) > 0:
        validate_processed(
            train_wide, data_format="wide", tournament=tournament_name, raise_on_error=False
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


def run(cfg: DictConfig) -> None:
    """Entry point для генерации фичей для одного турнира.

    Турнир задаётся через Hydra CLI (``tournament=uel_kz_1``).
    Features конфиг резолвит ``form_params``
    из конфига турнира, поэтому каждый запуск — один турнир.

    Для обработки нескольких турниров используйте Hydra multirun::

        python -m sports_forecast.features.features_build --multirun \\
            tournament=uel_kz_1,uel_kz_2,lp_ru,lp_eu

    Args:
        cfg: Hydra конфигурация (``cfg.tournament``, ``cfg.features``).

    Examples:
        Один турнир::

            python -m sports_forecast.features.features_build tournament=lp_ru

        Все турниры::

            python -m sports_forecast.features.features_build --multirun \\
                tournament=uel_kz_1,uel_kz_2,uel_cz,lp_ru,lp_eu,lp_eu_a18,lp_by
    """
    logger.info("=" * 70)
    logger.info("FEATURE GENERATION")
    logger.info("=" * 70)

    if not hasattr(cfg, "features") or not hasattr(cfg.features, "generators"):
        logger.error(
            "features.generators не задан в конфиге! "
            "Используйте: features=basic или features=advanced"
        )
        return

    if not hasattr(cfg, "tournament") or not hasattr(cfg.tournament, "name"):
        logger.error("tournament не задан! Укажите: tournament=uel_kz_1")
        return

    tournament_name = cfg.tournament.name
    logger.info("Конфиг фичей: %s", cfg.features.get("name", "N/A"))
    logger.info("Турнир: %s", tournament_name)

    # paths уже скомпонованы через features_pipeline.yaml defaults
    interim_root = PROJECT_ROOT / cfg.paths.interim_dir
    processed_root = PROJECT_ROOT / cfg.paths.processed_dir

    try:
        process_tournament_new(
            tournament_name,
            interim_root,
            processed_root,
            cfg.features,
            tournament_cfg=cfg.tournament,
        )
    except Exception as e:
        logger.error("Ошибка обработки турнира %s: %s", tournament_name, e, exc_info=True)

    logger.info("=" * 70)
    logger.info("✅ ГЕНЕРАЦИЯ ФИЧЕЙ ЗАВЕРШЕНА")
    logger.info("=" * 70)


if __name__ == "__main__":
    import hydra

    @hydra.main(
        version_base="1.3",
        config_path="../../conf",
        config_name="features_pipeline",
    )
    def main(cfg: DictConfig) -> None:
        configure_logging(cfg.get("logging", {}).get("level", "INFO"))
        run(cfg)

    main()
