"""
Обучение модели CatBoost на processed-датасете.

Поток:
    data/processed/{tournament}/dataset.parquet
      -> выбор feature_columns и target_column из Hydra-конфига
      -> train/valid split
      -> CatBoostClassifier fit
      -> сохранение модели в models/{tournament}/{model_name}.cbm

Запуск:
    uv run python -m sports_forecast.train --config-name train_catboost
"""

from __future__ import annotations

from pathlib import Path

import hydra
import pandas as pd
from catboost import CatBoostClassifier
from omegaconf import DictConfig
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import train_test_split

from sports_forecast.utils.log_config import configure_logging, get_logger


PROJECT_ROOT = Path(__file__).resolve().parents[1]
logger = get_logger(__name__)


def load_dataset(
    processed_root: Path,
    tournament: str,
    dataset_filename: str,
    target_column: str,
    feature_columns: list[str],
) -> tuple[pd.DataFrame, pd.Series] | None:
    dataset_path = processed_root / tournament / dataset_filename
    if not dataset_path.exists():
        logger.error("Файл датасета не найден: %s", dataset_path)
        return None

    logger.info("Читаю датасет: %s", dataset_path)
    df = pd.read_parquet(dataset_path)

    if df is None or df.empty:
        logger.error("Датасет пустой")
        return None

    if target_column not in df.columns:
        logger.error("Таргет '%s' отсутствует. Колонки: %s", target_column, list(df.columns))
        return None

    missing = [c for c in feature_columns if c not in df.columns]
    if missing:
        logger.error("Отсутствуют фичи из конфига: %s. Колонки: %s", missing, list(df.columns))
        return None

    X = df[feature_columns]
    y = df[target_column]

    logger.info("X shape: %s | y shape: %s", X.shape, y.shape)
    logger.info("Target distribution:\n%s", y.value_counts(dropna=False))

    return X, y


@hydra.main(config_path="../conf", config_name="train_catboost", version_base="1.3")
def run(cfg: DictConfig) -> None:
    configure_logging(level=cfg.logging.level)
    logger.info("Train (CatBoost) config: %s", cfg)

    processed_root = PROJECT_ROOT / cfg.paths.processed_dir
    models_root = PROJECT_ROOT / cfg.paths.models_dir
    models_root.mkdir(parents=True, exist_ok=True)

    dataset = load_dataset(
        processed_root=processed_root,
        tournament=cfg.data.tournament,
        dataset_filename=cfg.data.dataset_filename,
        target_column=cfg.training.target_column,
        feature_columns=list(cfg.training.feature_columns),
    )
    if dataset is None:
        logger.error("Не удалось подготовить датасет — выход")
        return

    X, y = dataset

    stratify = y if cfg.training.get("stratify", False) else None
    X_train, X_valid, y_train, y_valid = train_test_split(
        X,
        y,
        test_size=cfg.training.test_size,
        random_state=cfg.training.random_state,
        stratify=stratify,
    )

    logger.info("Split: train=%d, valid=%d", len(X_train), len(X_valid))

    model = CatBoostClassifier(**cfg.model.params)
    model.fit(X_train, y_train, eval_set=(X_valid, y_valid), use_best_model=True)

    # Базовая метрика (AUC) — для вероятностных моделей обычно лучше accuracy
    try:
        proba = model.predict_proba(X_valid)[:, 1]
        auc = roc_auc_score(y_valid, proba)
        logger.info("Valid AUC: %.4f", auc)
    except Exception as e:
        logger.warning("Не удалось посчитать AUC: %s", e)

    tournament_models_dir = models_root / cfg.data.tournament
    tournament_models_dir.mkdir(parents=True, exist_ok=True)

    ext = cfg.model.get("save_format", "cbm")
    model_path = tournament_models_dir / f"{cfg.model.name}.{ext}"

    model.save_model(str(model_path))
    logger.info("Модель сохранена: %s", model_path)


if __name__ == "__main__":
    run()
