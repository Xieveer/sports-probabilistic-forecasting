"""
Инференс модели CatBoost на inference-датасете с поддержкой мультитурнирного режима.

Поток:
    1. Загрузка датасета: data/processed/{tournament}/inference.parquet
    2. Загрузка модели: models/{tournament}/{model_name}.cbm
    3. Извлечение фичей из model.features
    4. Вычисление predict_proba
    5. Сохранение: data/predictions/{tournament}/predictions.parquet

Запуск:
    # Инференс для турнира uel с моделью is_home_win
    uv run python -m sports_forecast.predict tournament=uel model=is_home_win

    # Инференс для всех турниров
    uv run python -m sports_forecast.predict tournament=all model=is_home_win

    # Инференс для турнира lp_by
    uv run python -m sports_forecast.predict tournament=lp_by model=is_home_win

Примечание:
    Таргет НЕ используется в инференсе - только фичи из модели.
"""

from __future__ import annotations

from pathlib import Path

import hydra
import pandas as pd
from catboost import CatBoostClassifier
from omegaconf import DictConfig, OmegaConf

from sports_forecast.utils.log_config import configure_logging, get_logger


PROJECT_ROOT = Path(__file__).resolve().parents[1]
logger = get_logger(__name__)


def load_inference_dataset(
    processed_root: Path,
    tournament: str,
    filename: str,
    feature_columns: list[str],
) -> pd.DataFrame | None:
    """Загрузить inference-датасет.

    Args:
        processed_root: Путь к директории processed.
        tournament: Название турнира.
        filename: Имя файла датасета (inference.parquet).
        feature_columns: Список фичей для проверки.

    Returns:
        DataFrame с данными или None при ошибке.
    """
    dataset_path = processed_root / tournament / filename

    if not dataset_path.exists():
        logger.error("Inference-датасет не найден: %s", dataset_path)
        return None

    logger.info("Читаю inference-датасет: %s", dataset_path)
    df = pd.read_parquet(dataset_path)

    if df is None or df.empty:
        logger.warning("Inference-датасет пустой")
        return None

    missing = [c for c in feature_columns if c not in df.columns]
    if missing:
        logger.error("Отсутствуют фичи: %s. Колонки: %s", missing, list(df.columns))
        return None

    logger.info("Inference shape: %s", df.shape)
    return df


def load_model(
    models_root: Path, tournament: str, model_name: str, load_format: str = "cbm"
) -> CatBoostClassifier:
    """Загрузить обученную модель.

    Args:
        models_root: Путь к директории models.
        tournament: Название турнира.
        model_name: Имя модели.
        load_format: Формат файла модели.

    Returns:
        Загруженная модель CatBoost.

    Raises:
        FileNotFoundError: Если модель не найдена.
    """
    model_path = models_root / tournament / f"{model_name}.{load_format}"
    if not model_path.exists():
        raise FileNotFoundError(f"Файл модели не найден: {model_path}")

    logger.info("Загружаю модель CatBoost: %s", model_path)
    model = CatBoostClassifier()
    model.load_model(str(model_path))
    return model


def get_available_tournaments(processed_root: Path) -> list[str]:
    """Получить список доступных турниров из processed директории.

    Args:
        processed_root: Путь к директории data/processed.

    Returns:
        Список названий турниров (имена поддиректорий).
    """
    if not processed_root.exists():
        return []

    tournaments = []
    for item in processed_root.iterdir():
        if item.is_dir():
            # Проверяем, что есть inference.parquet
            inf_file = item / "inference.parquet"
            if inf_file.exists():
                tournaments.append(item.name)

    return sorted(tournaments)


def predict_single_tournament(
    tournament_name: str, model_cfg: DictConfig, paths_cfg: DictConfig
) -> bool:
    """Сделать предсказания для одного турнира.

    Args:
        tournament_name: Название турнира.
        model_cfg: Конфиг модели.
        cfg: Полный Hydra-конфиг (будет переопределен tournament).

    Returns:
        True если инференс успешен, False иначе.
    """

    logger.info("=" * 60)
    logger.info("ИНФЕРЕНС МОДЕЛИ")
    logger.info("Турнир: %s", tournament_name)
    logger.info("Модель: %s", model_cfg.name)
    logger.info("=" * 60)

    # Переопределяем конфиг для конкретного турнира
    from omegaconf import OmegaConf

    # Загружаем конфиг турнира напрямую
    tournament_config_path = PROJECT_ROOT / "conf" / "tournament" / f"{tournament_name}.yaml"
    tournament_cfg_data = OmegaConf.load(tournament_config_path)

    # Создаем полный конфиг из существующего, заменяя tournament
    tournament_cfg = OmegaConf.create(
        {
            "tournament": tournament_cfg_data,
            "model": model_cfg,
            "paths": paths_cfg.paths,  # paths_cfg.paths, так как OmegaConf.load возвращает весь файл
        }
    )

    processed_root = PROJECT_ROOT / tournament_cfg.paths.processed_dir
    predictions_root = PROJECT_ROOT / tournament_cfg.paths.predictions_dir
    models_root = PROJECT_ROOT / tournament_cfg.paths.models_dir

    predictions_root.mkdir(parents=True, exist_ok=True)

    try:
        # Загружаем датасет
        df = load_inference_dataset(
            processed_root=processed_root,
            tournament=tournament_cfg.tournament.name,
            filename="inference.parquet",  # Стандартное имя файла inference
            feature_columns=list(tournament_cfg.model.features),
        )
        if df is None or df.empty:
            logger.error("Турнир %s: нет данных для инференса — пропускаю", tournament_name)
            return False

        # Загружаем модель
        model = load_model(
            models_root=models_root,
            tournament=tournament_cfg.tournament.name,
            model_name=tournament_cfg.model.name,
            load_format=tournament_cfg.model.get("save_format", "cbm"),
        )

        # Извлекаем фичи
        feature_columns = list(tournament_cfg.model.features)
        X = df[feature_columns]

        logger.info("Фичи для инференса: %s", feature_columns)
        logger.info("X shape: %s", X.shape)

        # Предсказания
        logger.info("Считаю predict_proba...")
        proba = model.predict_proba(X)[:, 1]

        proba_col = f"proba_{tournament_cfg.model.name}"

        df_out = df.copy()
        df_out[proba_col] = proba

        # Сохраняем
        out_dir = predictions_root / tournament_cfg.tournament.name
        out_dir.mkdir(parents=True, exist_ok=True)

        out_path = out_dir / "predictions.parquet"
        logger.info(
            "Записываю предсказания (%d строк, %d колонок) → %s",
            len(df_out),
            df_out.shape[1],
            out_path,
        )
        df_out.to_parquet(out_path, index=False)

        logger.info("=" * 60)
        logger.info("Турнир %s: инференс завершен успешно", tournament_name)
        logger.info("=" * 60)
        return True

    except Exception as e:
        logger.error("Турнир %s: ошибка при инференсе - %s", tournament_name, e)
        import traceback

        logger.error("Traceback:\n%s", traceback.format_exc())
        return False


@hydra.main(config_path="../conf", config_name="config", version_base="1.3")
def run(cfg: DictConfig) -> None:
    """Запустить инференс модели для одного или всех турниров.

    Если cfg.tournament.name == "all", делает предсказания для всех доступных турниров.
    Иначе делает предсказания только для указанного турнира.

    Args:
        cfg: Hydra-конфиг с настройками инференса.
    """
    configure_logging(level=cfg.logging.level)

    # Загружаем paths конфиг
    paths_config_path = PROJECT_ROOT / "conf" / "paths.yaml"
    paths_cfg = OmegaConf.load(paths_config_path)

    # Определяем список турниров для инференса
    if cfg.tournament.name == "all":
        # Режим: инференс для всех турниров
        processed_root = PROJECT_ROOT / paths_cfg.paths.processed_dir
        tournaments = get_available_tournaments(processed_root)

        if not tournaments:
            logger.error("Не найдено ни одного турнира с inference данными в %s", processed_root)
            return

        logger.info("=" * 60)
        logger.info("МУЛЬТИТУРНИРНЫЙ ИНФЕРЕНС")
        logger.info("Модель: %s", cfg.model.name)
        logger.info("Найдено турниров: %d", len(tournaments))
        logger.info("Турниры: %s", ", ".join(tournaments))
        logger.info("=" * 60)

        success_count = 0
        failed_tournaments = []

        for tournament_name in tournaments:
            success = predict_single_tournament(tournament_name, cfg.model, paths_cfg)
            if success:
                success_count += 1
            else:
                failed_tournaments.append(tournament_name)

        logger.info("=" * 60)
        logger.info("МУЛЬТИТУРНИРНЫЙ ИНФЕРЕНС ЗАВЕРШЕН")
        logger.info("Успешно обработано: %d/%d", success_count, len(tournaments))
        if failed_tournaments:
            logger.warning("Турниры с ошибками: %s", ", ".join(failed_tournaments))
        logger.info("=" * 60)

    else:
        # Режим: инференс для одного турнира
        success = predict_single_tournament(cfg.tournament.name, cfg.model, paths_cfg)
        if not success:
            logger.error("Инференс не удался")
            return


if __name__ == "__main__":
    run()
