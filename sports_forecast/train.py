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
import mlflow
import mlflow.catboost
import pandas as pd
from catboost import CatBoostClassifier
from omegaconf import DictConfig, OmegaConf
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

    # ---------- MLflow: базовая настройка трекинга ----------
    # Пытаемся взять настройки из конфигурации (группа mlflow),
    # иначе используем локальный каталог mlruns в корне проекта.
    if "mlflow" in cfg:
        tracking_uri = cfg.mlflow.get("tracking_uri", None)
        experiment_name = cfg.mlflow.get("experiment_name", None)
    else:
        tracking_uri = None
        experiment_name = None

    if not tracking_uri:
        tracking_uri = f"file:{PROJECT_ROOT / 'mlruns'}"
    if not experiment_name:
        experiment_name = "sports_forecast"

    mlflow.set_tracking_uri(tracking_uri)
    mlflow.set_experiment(experiment_name)

    run_name = f"{cfg.data.tournament}_{cfg.model.name}"

    with mlflow.start_run(run_name=run_name):
        # ---------- Логируем общую информацию о данных и конфиге ----------
        mlflow.set_tag("tournament", cfg.data.tournament)
        mlflow.set_tag("model_name", cfg.model.name)
        mlflow.set_tag("dataset_filename", cfg.data.dataset_filename)

        # Сохраняем полный Hydra-конфиг как артефакт
        mlflow.log_text(OmegaConf.to_yaml(cfg), "config.yaml")

        # Размеры датасета
        mlflow.log_param("n_samples", len(X))
        mlflow.log_param("n_features", X.shape[1])
        mlflow.log_param("target_column", cfg.training.target_column)

        # Список фичей отдельным артефактом
        feature_columns = list(cfg.training.feature_columns)
        mlflow.log_text("\n".join(feature_columns), "features.txt")

        # Гиперпараметры модели (как есть из конфига)
        if "params" in cfg.model:
            mlflow.log_params({f"model__{k}": v for k, v in cfg.model.params.items()})

        # Параметры обучения (test_size, random_state, stratify)
        mlflow.log_param("test_size", cfg.training.test_size)
        mlflow.log_param("random_state", cfg.training.random_state)
        mlflow.log_param("stratify", bool(cfg.training.get("stratify", False)))

        stratify = y if cfg.training.get("stratify", False) else None
        X_train, X_valid, y_train, y_valid = train_test_split(
            X,
            y,
            test_size=cfg.training.test_size,
            random_state=cfg.training.random_state,
            stratify=stratify,
        )

        logger.info("Split: train=%d, valid=%d", len(X_train), len(X_valid))
        mlflow.log_param("n_train", len(X_train))
        mlflow.log_param("n_valid", len(X_valid))

        model = CatBoostClassifier(**cfg.model.params)
        model.fit(X_train, y_train, eval_set=(X_valid, y_valid), use_best_model=True)

        # Базовая метрика (AUC) — логируем в MLflow
        try:
            proba = model.predict_proba(X_valid)[:, 1]
            auc = roc_auc_score(y_valid, proba)
            logger.info("Valid AUC: %.4f", auc)
            mlflow.log_metric("valid_auc", auc)
        except Exception as e:
            logger.warning("Не удалось посчитать AUC: %s", e)
            mlflow.set_tag("auc_error", str(e))

        tournament_models_dir = models_root / cfg.data.tournament
        tournament_models_dir.mkdir(parents=True, exist_ok=True)

        ext = cfg.model.get("save_format", "cbm")
        model_path = tournament_models_dir / f"{cfg.model.name}.{ext}"

        model.save_model(str(model_path))
        logger.info("Модель сохранена: %s", model_path)

        # ---------- Логирование модели в MLflow ----------
        # 1) логируем файл модели как артефакт
        mlflow.log_artifact(str(model_path), artifact_path="model_file")

        # 2) логируем модель через CatBoost flavor (удобно для дальнейшего загрузки через MLflow)
        try:
            mlflow.catboost.log_model(
                model,
                artifact_path="model",
            )
        except Exception as e:
            logger.warning("Не удалось залогировать модель через mlflow.catboost: %s", e)
            mlflow.set_tag("mlflow_catboost_log_error", str(e))


if __name__ == "__main__":
    run()
