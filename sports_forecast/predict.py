"""
Инференс модели CatBoost на processed-датасете.

Поток:
    data/processed/{tournament}/inference.parquet
      -> выбор feature_columns из Hydra-конфига
      -> загрузка модели CatBoost
      -> predict_proba
      -> сохранение предсказаний в data/predictions/{tournament}/predictions.parquet

Запуск:
    uv run python -m sports_forecast.predict --config-name predict_catboost
"""

from __future__ import annotations

from pathlib import Path

import hydra
import pandas as pd
from catboost import CatBoostClassifier
from omegaconf import DictConfig

from sports_forecast.utils.log_config import configure_logging, get_logger


PROJECT_ROOT = Path(__file__).resolve().parents[1]
logger = get_logger(__name__)


def load_inference_dataset(
    processed_root: Path,
    cfg: DictConfig,
) -> pd.DataFrame | None:
    tournament = cfg.data.tournament
    filename = cfg.data.inference_filename
    dataset_path = processed_root / tournament / filename

    if not dataset_path.exists():
        logger.error("Inference-датасет не найден: %s", dataset_path)
        return None

    logger.info("Читаю inference-датасет: %s", dataset_path)
    df = pd.read_parquet(dataset_path)

    if df is None or df.empty:
        logger.warning("Inference-датасет пустой")
        return None

    logger.info("Inference shape: %s", df.shape)
    return df


def load_model(models_root: Path, cfg: DictConfig) -> CatBoostClassifier:
    tournament = cfg.data.tournament
    model_name = cfg.model.name
    ext = cfg.model.get("load_format", "cbm")

    model_path = models_root / tournament / f"{model_name}.{ext}"
    if not model_path.exists():
        raise FileNotFoundError(f"Файл модели не найден: {model_path}")

    logger.info("Загружаю модель CatBoost: %s", model_path)
    model = CatBoostClassifier()
    model.load_model(str(model_path))
    return model


@hydra.main(config_path="../conf", config_name="predict_catboost", version_base="1.3")
def run(cfg: DictConfig) -> None:
    configure_logging(level=cfg.logging.level)
    logger.info("Predict (CatBoost) config: %s", cfg)

    processed_root = PROJECT_ROOT / cfg.paths.processed_dir
    predictions_root = PROJECT_ROOT / cfg.paths.predictions_dir
    models_root = PROJECT_ROOT / cfg.paths.models_dir

    predictions_root.mkdir(parents=True, exist_ok=True)

    df = load_inference_dataset(processed_root, cfg)
    if df is None or df.empty:
        logger.error("Нет данных для инференса — выхожу")
        return

    feature_columns = list(cfg.inference.feature_columns)
    missing = [c for c in feature_columns if c not in df.columns]
    if missing:
        logger.error("В inference-датасете нет фич: %s. Колонки: %s", missing, list(df.columns))
        return

    X = df[feature_columns]

    logger.info("Фичи для инференса: %s", feature_columns)
    logger.info("X shape: %s", X.shape)

    model = load_model(models_root, cfg)

    logger.info("Считаю predict_proba...")
    proba = model.predict_proba(X)[:, 1]

    proba_col = cfg.inference.get("proba_column", "proba_home_win")

    df_out = df.copy()
    df_out[proba_col] = proba

    tournament = cfg.data.tournament
    out_dir = predictions_root / tournament
    out_dir.mkdir(parents=True, exist_ok=True)

    out_path = out_dir / "predictions.parquet"
    logger.info(
        "Записываю предсказания (%d строк, %d колонок) → %s",
        len(df_out),
        df_out.shape[1],
        out_path,
    )
    df_out.to_parquet(out_path, index=False)


if __name__ == "__main__":
    run()
