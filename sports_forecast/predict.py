"""
Инференс обученной модели на inference-датасете.

Поддерживает мультитурнирный режим и любые модели,
реализующие интерфейс ``BaseModel`` (CatBoost, LightGBM, LogReg и т.д.).

Поток:
    1. Загрузка датасета: ``data/processed/{tournament}/inference_{format}.parquet``
    2. Загрузка модели через ``ModelFactory`` + ``BaseModel.load()``
    3. Загрузка списка фичей из артефакта ``features.txt``
    4. Вычисление ``predict_proba``
    5. Сохранение: ``data/predictions/{tournament}/{market_spec}/predictions.parquet``

Запуск::

    # Инференс для одного турнира
    uv run python -m sports_forecast.predict \\
        tournament=uel_kz_1 \\
        market=total \\
        market_spec=total_over \\
        market_spec.line=6.5 \\
        algorithm=catboost \\
        features=basic

Примечание:
    Таргет НЕ используется в инференсе — только фичи из модели.
"""

from __future__ import annotations

from pathlib import Path

import hydra
import pandas as pd
from omegaconf import DictConfig

from sports_forecast.training.base import BaseModel
from sports_forecast.training.model_factory import ModelFactory
from sports_forecast.utils.log_config import configure_logging, get_logger


PROJECT_ROOT = Path(__file__).resolve().parents[1]
logger = get_logger(__name__)


def load_inference_dataset(
    processed_root: Path,
    tournament: str,
    filename: str,
    feature_columns: list[str] | None = None,
) -> pd.DataFrame | None:
    """Загрузить inference-датасет.

    Args:
        processed_root: Путь к директории processed.
        tournament: Название турнира.
        filename: Имя файла датасета.
        feature_columns: Список фичей для проверки (опционально).

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

    if feature_columns:
        missing = [c for c in feature_columns if c not in df.columns]
        if missing:
            logger.error("Отсутствуют фичи: %s. Колонки: %s", missing, list(df.columns))
            return None

    logger.info("Inference shape: %s", df.shape)
    return df


def load_model_from_path(algorithm_cfg: DictConfig, model_path: Path) -> BaseModel:
    """Загрузить модель с диска, используя ModelFactory.

    Args:
        algorithm_cfg: Конфигурация алгоритма модели.
        model_path: Путь к файлу модели.

    Returns:
        Загруженный экземпляр BaseModel.

    Raises:
        FileNotFoundError: Если файл модели не найден.
    """
    if not model_path.exists():
        raise FileNotFoundError(f"Файл модели не найден: {model_path}")

    logger.info("Загружаю модель: %s", model_path)
    model = ModelFactory.create_model(algorithm_cfg)
    model.load(model_path)
    return model


def load_feature_names(model_dir: Path) -> list[str] | None:
    """Загрузить список фичей из артефакта features.txt.

    Args:
        model_dir: Директория модели.

    Returns:
        Список имён фичей или None если файл не найден.
    """
    features_path = model_dir / "features.txt"
    if not features_path.exists():
        logger.warning(
            "features.txt не найден в %s, будут использованы все числовые колонки",
            model_dir,
        )
        return None

    feature_names = features_path.read_text().strip().split("\n")
    logger.info("Загружено %d фичей из %s", len(feature_names), features_path)
    return feature_names


def get_model_dir(cfg: DictConfig, project_root: Path) -> Path:
    """Получить директорию модели из конфигурации.

    Args:
        cfg: Hydra конфигурация.
        project_root: Корневая директория проекта.

    Returns:
        Путь к директории модели.
    """
    tournament_name = str(cfg.tournament.name)
    market_spec_name = str(cfg.market_spec.name)
    algorithm_name = str(cfg.algorithm.name)
    featureset_name = str(cfg.features.name)
    models_dir = Path(str(cfg.paths.models_dir))

    return (
        project_root
        / models_dir
        / tournament_name
        / market_spec_name
        / f"{algorithm_name}_{featureset_name}"
    )


def find_model_file(model_dir: Path, version: str = "prod") -> Path | None:
    """Найти файл модели в директории.

    Поддерживает форматы: ``.cbm``, ``.pkl``, ``.lgbm``.

    Args:
        model_dir: Директория модели.
        version: Версия модели (``"prod"`` или ``"shadow"``).

    Returns:
        Путь к файлу модели или None если не найден.
    """
    extensions = [".cbm", ".pkl", ".txt", ".lgbm"]

    for ext in extensions:
        # Ищем файлы вида {name}_{version}{ext}
        candidates = list(model_dir.glob(f"*_{version}{ext}"))
        if candidates:
            return candidates[0]

    # Пробуем без версии
    for ext in extensions:
        candidates = list(model_dir.glob(f"*{ext}"))
        if candidates:
            return candidates[0]

    return None


def get_available_tournaments(processed_root: Path) -> list[str]:
    """Получить список доступных турниров из processed директории.

    Args:
        processed_root: Путь к директории data/processed.

    Returns:
        Список названий турниров.
    """
    if not processed_root.exists():
        return []

    return sorted(
        item.name
        for item in processed_root.iterdir()
        if item.is_dir() and any(item.glob("inference_*.parquet"))
    )


def predict_single(cfg: DictConfig, version: str = "prod") -> bool:
    """Сделать предсказания для одного эксперимента.

    Args:
        cfg: Полный Hydra конфиг.
        version: Версия модели (``"prod"`` или ``"shadow"``).

    Returns:
        True если инференс успешен, False иначе.
    """
    tournament_name = cfg.tournament.name
    algorithm_name = cfg.algorithm.name
    featureset_name = cfg.features.name
    market_spec_name = cfg.market_spec.name
    data_format = cfg.market_spec.data_format

    logger.info("=" * 60)
    logger.info("ИНФЕРЕНС МОДЕЛИ")
    logger.info("  Турнир: %s", tournament_name)
    logger.info("  Алгоритм: %s", algorithm_name)
    logger.info("  Фичи: %s", featureset_name)
    logger.info("  MarketSpec: %s", market_spec_name)
    logger.info("  Версия: %s", version)
    logger.info("=" * 60)

    try:
        # 1. Определяем пути
        processed_root = PROJECT_ROOT / cfg.paths.processed_dir
        predictions_root = PROJECT_ROOT / cfg.paths.predictions_dir
        model_dir = get_model_dir(cfg, PROJECT_ROOT)

        # 2. Находим файл модели
        model_file = find_model_file(model_dir, version=version)
        if model_file is None:
            logger.error("Модель не найдена в %s (version=%s)", model_dir, version)
            return False

        # 3. Загружаем модель
        model = load_model_from_path(cfg.algorithm, model_file)

        # 4. Загружаем список фичей
        feature_names = load_feature_names(model_dir)

        # 5. Загружаем inference-датасет
        inference_filename = f"inference_{data_format}.parquet"
        df = load_inference_dataset(
            processed_root=processed_root,
            tournament=tournament_name,
            filename=inference_filename,
            feature_columns=feature_names,
        )
        if df is None or df.empty:
            logger.error("Турнир %s: нет данных для инференса", tournament_name)
            return False

        # 6. Извлекаем фичи
        if feature_names:
            features = df[feature_names]
        else:
            # Fallback: все числовые колонки
            features = df.select_dtypes(include="number")
            logger.warning("Используются все %d числовых колонок", features.shape[1])

        logger.info("Features shape: %s", features.shape)

        # 7. Предсказания
        logger.info("Считаю predict_proba...")
        proba = model.predict_proba(features)

        # Для бинарной классификации — вероятность класса 1
        proba_values = proba[:, 1] if proba.shape[1] == 2 else proba.max(axis=1)

        proba_col = f"proba_{market_spec_name}"
        df_out = df.copy()
        df_out[proba_col] = proba_values

        # 8. Сохраняем
        out_dir = predictions_root / tournament_name / market_spec_name
        out_dir.mkdir(parents=True, exist_ok=True)

        out_path = out_dir / f"predictions_{version}.parquet"
        df_out.to_parquet(out_path, index=False)
        logger.info("Предсказания сохранены (%d строк) → %s", len(df_out), out_path)

        logger.info("Турнир %s: инференс завершен успешно", tournament_name)
        return True

    except Exception:
        logger.exception("Турнир %s: ошибка при инференсе", tournament_name)
        return False


@hydra.main(config_path="../conf", config_name="config", version_base="1.3")
def run(cfg: DictConfig) -> None:
    """Запустить инференс модели.

    Args:
        cfg: Hydra-конфиг с настройками инференса.
    """
    configure_logging(level=cfg.logging.level)

    logger.info("=" * 80)
    logger.info("PREDICTION PIPELINE v2.0")
    logger.info("=" * 80)

    version = cfg.get("model_version", "prod")

    success = predict_single(cfg, version=version)
    if success:
        logger.info("Инференс завершен успешно")
    else:
        logger.error("Инференс завершен с ошибками")


if __name__ == "__main__":
    run()
