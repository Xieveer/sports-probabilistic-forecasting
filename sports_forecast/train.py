"""
Обучение модели CatBoost на processed-датасете с динамическим вычислением таргета.

Поток:
    1. Загрузка датасета: data/processed/{tournament}/train.parquet
    2. Динамическое вычисление таргета на основе:
       - tournament.target_sources (турнир-специфичные источники)
       - model.target_config (какой таргет использовать для этой модели)
    3. Выбор фичей из model.features
    4. Train/valid split
    5. Обучение CatBoostClassifier
    6. Сохранение модели: models/{tournament}/{model_name}.cbm
    7. Логирование в MLflow

Запуск:
    # Обучить модель is_home_win для турнира uel
    uv run python -m sports_forecast.train tournament=uel model=is_home_win

    # Обучить для турнира lp_by
    uv run python -m sports_forecast.train tournament=lp_by model=is_home_win

Примечание:
    Таргет НЕ хранится в датасете - он вычисляется на лету на основе
    турнир-специфичных колонок (home_points, away_points и т.д.).
    Это позволяет обучать разные модели (is_home_win, is_away_win, total_under_X)
    на одном и том же датасете без дублирования данных.
"""

from __future__ import annotations

from pathlib import Path

import hydra
import mlflow
import mlflow.catboost
import numpy as np
import pandas as pd
from catboost import CatBoostClassifier
from omegaconf import DictConfig, OmegaConf
from sklearn.metrics import accuracy_score, brier_score_loss, log_loss, roc_auc_score

from sports_forecast.utils.log_config import configure_logging, get_logger


PROJECT_ROOT = Path(__file__).resolve().parents[1]
logger = get_logger(__name__)


def compute_expected_calibration_error(
    y_true: np.ndarray, y_proba: np.ndarray, n_bins: int = 10
) -> float:
    """Вычислить Expected Calibration Error (ECE) для оценки калибровки модели.

    ECE измеряет среднее расхождение между предсказанными вероятностями
    и фактической частотой положительных исходов.

    Args:
        y_true: Истинные метки классов (0 или 1).
        y_proba: Предсказанные вероятности класса 1.
        n_bins: Количество бинов для разбиения вероятностей.

    Returns:
        Значение ECE (от 0 до 1, чем ближе к 0, тем лучше калибровка).

    Examples:
        >>> y_true = np.array([0, 0, 1, 1])
        >>> y_proba = np.array([0.1, 0.2, 0.8, 0.9])
        >>> ece = compute_expected_calibration_error(y_true, y_proba)
        >>> print(f"ECE: {ece:.4f}")
        ECE: 0.0000

    Note:
        Идеально откалиброванная модель имеет ECE = 0.
        ECE > 0.1 может указывать на проблемы с калибровкой.
    """
    # Разбиваем вероятности на бины
    bins = np.linspace(0, 1, n_bins + 1)
    bin_indices = np.digitize(y_proba, bins[:-1]) - 1
    bin_indices = np.clip(bin_indices, 0, n_bins - 1)

    ece = 0.0
    for bin_idx in range(n_bins):
        # Находим все предсказания в текущем бине
        in_bin = bin_indices == bin_idx
        if not np.any(in_bin):
            continue

        # Средняя предсказанная вероятность в бине
        mean_predicted = y_proba[in_bin].mean()

        # Фактическая частота положительных исходов в бине
        mean_actual = y_true[in_bin].mean()

        # Размер бина (для взвешивания)
        bin_size = in_bin.sum()

        # Добавляем к ECE взвешенную разницу
        ece += (bin_size / len(y_true)) * np.abs(mean_predicted - mean_actual)

    return float(ece)


def compute_target(df: pd.DataFrame, cfg: DictConfig) -> pd.Series:
    """Вычислить таргет на основе турнир-специфичного и модель-специфичного конфигов.

    Args:
        df: Датафрейм с данными (должен содержать колонки из target_sources).
        cfg: Hydra-конфиг с tournament.target_sources и model.target_config.

    Returns:
        Series с вычисленным таргетом.

    Raises:
        ValueError: Если конфигурация таргета некорректна.

    Example:
        >>> target = compute_target(df, cfg)
        >>> # Для модели is_home_win: вернет 1 если home_points > away_points
    """
    # Получаем ключ источника таргета из модели
    source_key = cfg.model.target_config.source_key
    target_name = cfg.model.target_config.name

    # Получаем спецификацию из турнира
    if not hasattr(cfg.tournament, "target_sources"):
        raise ValueError(f"Турнир {cfg.tournament.name} не содержит target_sources в конфиге")

    if source_key not in cfg.tournament.target_sources:
        available = list(cfg.tournament.target_sources.keys())
        raise ValueError(
            f"Таргет '{source_key}' не найден в tournament.target_sources. Доступные: {available}"
        )

    target_spec = cfg.tournament.target_sources[source_key]

    logger.info(
        "Вычисляю таргет '%s' на основе источника '%s' (турнир: %s)",
        target_name,
        source_key,
        cfg.tournament.name,
    )

    # Проверяем наличие колонок в датафрейме
    home_col = target_spec.home_column
    away_col = target_spec.away_column

    if home_col not in df.columns:
        raise ValueError(
            f"Колонка '{home_col}' не найдена в датафрейме. Доступные: {list(df.columns)}"
        )
    if away_col not in df.columns:
        raise ValueError(
            f"Колонка '{away_col}' не найдена в датафрейме. Доступные: {list(df.columns)}"
        )

    # Вычисляем таргет на основе типа
    target: pd.Series
    if hasattr(target_spec, "comparison"):
        # Бинарная классификация: comparison (greater, less, equal)
        comparison = target_spec.comparison

        if comparison == "greater":
            target = (df[home_col] > df[away_col]).astype(int)
        elif comparison == "less":
            target = (df[home_col] < df[away_col]).astype(int)
        elif comparison == "equal":
            target = (df[home_col] == df[away_col]).astype(int)
        else:
            raise ValueError(f"Неизвестный тип comparison: {comparison}")

        logger.info("Таргет: %s %s %s", home_col, comparison, away_col)

    elif hasattr(target_spec, "aggregation"):
        # Регрессия или threshold: aggregation (sum, diff, etc.)
        aggregation = target_spec.aggregation

        if aggregation == "sum":
            target = df[home_col] + df[away_col]
        elif aggregation == "diff":
            target = df[home_col] - df[away_col]
        else:
            raise ValueError(f"Неизвестный тип aggregation: {aggregation}")

        logger.info("Таргет: %s %s %s", home_col, aggregation, away_col)

    else:
        raise ValueError(
            f"Спецификация таргета '{source_key}' должна содержать 'comparison' или 'aggregation'"
        )

    # Логируем статистику
    if target.dtype in ["int64", "int32", "float64", "float32"]:
        logger.info(
            "Статистика таргета '%s': min=%.2f, max=%.2f, mean=%.2f, null=%d",
            target_name,
            target.min(),
            target.max(),
            target.mean(),
            target.isna().sum(),
        )

        # Для бинарного таргета показываем распределение классов
        if set(target.dropna().unique()).issubset({0, 1}):
            value_counts = target.value_counts()
            total = len(target)
            logger.info(
                "Распределение классов: 0=%d (%.1f%%), 1=%d (%.1f%%)",
                value_counts.get(0, 0),
                value_counts.get(0, 0) / total * 100,
                value_counts.get(1, 0),
                value_counts.get(1, 0) / total * 100,
            )

    return target


def load_dataset(
    processed_root: Path,
    tournament: str,
    dataset_filename: str,
    feature_columns: list[str],
) -> pd.DataFrame | None:
    """Загрузить датасет из processed-слоя.

    Таргет НЕ загружается из датасета, так как он вычисляется динамически
    на основе модель-специфичного конфига.

    Args:
        processed_root: Путь к директории processed.
        tournament: Название турнира.
        dataset_filename: Имя файла датасета (train.parquet).
        feature_columns: Список фичей для модели.

    Returns:
        DataFrame с данными (фичи + мета, без таргета) или None при ошибке.
    """
    dataset_path = processed_root / tournament / dataset_filename
    if not dataset_path.exists():
        logger.error("Файл датасета не найден: %s", dataset_path)
        return None

    logger.info("Читаю датасет: %s", dataset_path)
    df = pd.read_parquet(dataset_path)

    if df is None or df.empty:
        logger.error("Датасет пустой")
        return None

    missing = [c for c in feature_columns if c not in df.columns]
    if missing:
        logger.error("Отсутствуют фичи из конфига: %s. Колонки: %s", missing, list(df.columns))
        return None

    logger.info("Датасет загружен: %d записей, %d колонок", len(df), df.shape[1])
    logger.info("Доступные колонки: %s", list(df.columns))

    return df


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
            # Проверяем, что есть train.parquet
            train_file = item / "train.parquet"
            if train_file.exists():
                tournaments.append(item.name)

    return sorted(tournaments)


def train_single_tournament(tournament_name: str, model_cfg: DictConfig, cfg: DictConfig) -> bool:
    """Обучить модель для одного турнира.

    Args:
        tournament_name: Название турнира.
        model_cfg: Конфиг модели.
        cfg: Полный Hydra-конфиг (будет переопределен tournament).

    Returns:
        True если обучение успешно, False иначе.
    """

    logger.info("=" * 60)
    logger.info("ОБУЧЕНИЕ МОДЕЛИ")
    logger.info("Турнир: %s", tournament_name)
    logger.info("Модель: %s", model_cfg.name)
    logger.info("=" * 60)

    # Переопределяем конфиг для конкретного турнира
    # Используем уже существующий cfg и переопределяем только tournament

    # Загружаем конфиг турнира напрямую
    tournament_config_path = PROJECT_ROOT / "conf" / "tournament" / f"{tournament_name}.yaml"
    tournament_cfg_data = OmegaConf.load(tournament_config_path)

    # Загружаем paths
    paths_config_path = PROJECT_ROOT / "conf" / "paths.yaml"
    paths_cfg = OmegaConf.load(paths_config_path)

    # Создаем полный конфиг из существующего, заменяя tournament
    tournament_cfg = OmegaConf.create(
        {
            "tournament": tournament_cfg_data,
            "model": model_cfg,
            "paths": paths_cfg,
            "data": cfg.data,
            "training": cfg.training,
            "logging": cfg.logging,
        }
    )

    # paths_cfg уже содержит структуру {paths: {...}}, меняем
    OmegaConf.update(tournament_cfg, "paths", paths_cfg.paths)

    # Добавляем mlflow если есть
    if hasattr(cfg, "mlflow"):
        tournament_cfg.mlflow = cfg.mlflow

    processed_root = PROJECT_ROOT / tournament_cfg.paths.processed_dir
    models_root = PROJECT_ROOT / tournament_cfg.paths.models_dir
    models_root.mkdir(parents=True, exist_ok=True)

    # Загружаем датасет (БЕЗ таргета)
    df = load_dataset(
        processed_root=processed_root,
        tournament=tournament_cfg.tournament.name,
        dataset_filename=tournament_cfg.data.dataset_filename,
        feature_columns=list(tournament_cfg.model.features),
    )
    if df is None:
        logger.error("Турнир %s: не удалось подготовить датасет — пропускаю", tournament_name)
        return False

    # Вычисляем таргет динамически
    try:
        y = compute_target(df, tournament_cfg)
    except Exception as e:
        logger.error("Турнир %s: не удалось вычислить таргет - %s", tournament_name, e)
        import traceback

        logger.error("Traceback:\n%s", traceback.format_exc())
        return False

    # Извлекаем фичи
    X = df[list(tournament_cfg.model.features)]

    # ---------- ВРЕМЕННЫЕ РЯДЫ: Сортировка по времени ----------
    time_column = tournament_cfg.training.get("time_column", "datetime")
    if time_column and time_column in df.columns:
        # Сортируем по времени для корректного split
        sort_idx = df[time_column].argsort()
        X = X.iloc[sort_idx].reset_index(drop=True)
        y = y.iloc[sort_idx].reset_index(drop=True)
        logger.info("Данные отсортированы по '%s' для временного ряда", time_column)
    else:
        logger.warning(
            "Колонка времени '%s' не найдена. Split будет без учета временной структуры!",
            time_column,
        )

    # ---------- MLflow: базовая настройка трекинга ----------
    if "mlflow" in tournament_cfg:
        tracking_uri = tournament_cfg.mlflow.get("tracking_uri", None)
        experiment_name = tournament_cfg.mlflow.get("experiment_name", None)
    else:
        tracking_uri = None
        experiment_name = None

    if not tracking_uri:
        tracking_uri = f"file:{PROJECT_ROOT / 'mlruns'}"
    if not experiment_name:
        experiment_name = "sports_forecast"

    mlflow.set_tracking_uri(tracking_uri)
    mlflow.set_experiment(experiment_name)

    run_name = f"{tournament_cfg.tournament.name}_{tournament_cfg.model.name}"

    try:
        with mlflow.start_run(run_name=run_name):
            # ---------- Логируем общую информацию ----------
            mlflow.set_tag("tournament", tournament_cfg.tournament.name)
            mlflow.set_tag("tournament_sport", tournament_cfg.tournament.sport)
            mlflow.set_tag("model_name", tournament_cfg.model.name)
            mlflow.set_tag("model_description", tournament_cfg.model.description)
            mlflow.set_tag("target_source", tournament_cfg.model.target_config.source_key)
            mlflow.set_tag("target_name", tournament_cfg.model.target_config.name)
            mlflow.set_tag("dataset_filename", tournament_cfg.data.dataset_filename)

            # Сохраняем полный Hydra-конфиг как артефакт
            mlflow.log_text(OmegaConf.to_yaml(tournament_cfg), "config.yaml")

            # Размеры датасета
            mlflow.log_param("n_samples", len(X))
            mlflow.log_param("n_features", X.shape[1])

            # Список фичей отдельным артефактом
            feature_columns = list(tournament_cfg.model.features)
            mlflow.log_text("\n".join(feature_columns), "features.txt")

            # Гиперпараметры модели
            if "params" in tournament_cfg.model:
                mlflow.log_params(
                    {f"model__{k}": v for k, v in tournament_cfg.model.params.items()}
                )

        # Параметры обучения
        mlflow.log_param("test_size", tournament_cfg.training.test_size)
        mlflow.log_param("shuffle", tournament_cfg.training.get("shuffle", False))
        mlflow.log_param("time_based_split", True)

        # ВРЕМЕННОЙ SPLIT: валидация на более поздних данных
        # Не используем shuffle и stratify - это временные ряды!
        test_size = tournament_cfg.training.test_size
        split_idx = int(len(X) * (1 - test_size))

        X_train = X.iloc[:split_idx]
        X_valid = X.iloc[split_idx:]
        y_train = y.iloc[:split_idx]
        y_valid = y.iloc[split_idx:]

        logger.info(
            "Временной split: train=%d (первые %.1f%%), valid=%d (последние %.1f%%)",
            len(X_train),
            (1 - test_size) * 100,
            len(X_valid),
            test_size * 100,
        )
        mlflow.log_param("n_train", len(X_train))
        mlflow.log_param("n_valid", len(X_valid))

        model = CatBoostClassifier(**tournament_cfg.model.params)
        logger.info("Начинаю обучение CatBoost...")
        model.fit(X_train, y_train, eval_set=(X_valid, y_valid), use_best_model=True)

        # ---------- Метрики на валидации ----------
        proba = model.predict_proba(X_valid)[:, 1]
        y_pred = (proba >= 0.5).astype(int)  # Бинарные предсказания для accuracy

        logger.info("=" * 60)
        logger.info("МЕТРИКИ НА ВАЛИДАЦИИ")
        logger.info("=" * 60)

        # 1. LogLoss - основная метрика для временных рядов и вероятностных прогнозов
        try:
            logloss = log_loss(y_valid, proba)
            logger.info("LogLoss:  %.4f (основная метрика)", logloss)
            mlflow.log_metric("valid_logloss", logloss)
            mlflow.log_metric("primary_metric", logloss)  # Основная метрика для сравнения моделей
        except Exception as e:
            logger.error("Не удалось посчитать LogLoss: %s", e)
            mlflow.set_tag("logloss_error", str(e))

        # 2. AUC - способность модели различать классы
        try:
            auc = roc_auc_score(y_valid, proba)
            logger.info("AUC:      %.4f (дискриминация)", auc)
            mlflow.log_metric("valid_auc", auc)
        except Exception as e:
            logger.warning("Не удалось посчитать AUC: %s", e)
            mlflow.set_tag("auc_error", str(e))

        # 3. Accuracy - точность бинарных предсказаний
        try:
            accuracy = accuracy_score(y_valid, y_pred)
            logger.info("Accuracy: %.4f (точность предсказаний)", accuracy)
            mlflow.log_metric("valid_accuracy", accuracy)
        except Exception as e:
            logger.warning("Не удалось посчитать Accuracy: %s", e)
            mlflow.set_tag("accuracy_error", str(e))

        # 4. Brier Score - качество вероятностных прогнозов
        try:
            brier_score = brier_score_loss(y_valid, proba)
            logger.info("Brier:    %.4f (калибровка вероятностей)", brier_score)
            mlflow.log_metric("valid_brier_score", brier_score)
        except Exception as e:
            logger.warning("Не удалось посчитать Brier Score: %s", e)
            mlflow.set_tag("brier_error", str(e))

        # 5. Expected Calibration Error (ECE) - калибровка модели
        try:
            y_valid_array = np.array(y_valid)
            ece = compute_expected_calibration_error(y_valid_array, proba)
            logger.info("ECE:      %.4f (калибровка по бинам)", ece)
            mlflow.log_metric("valid_ece", ece)
        except Exception as e:
            logger.warning("Не удалось посчитать ECE: %s", e)
            mlflow.set_tag("ece_error", str(e))

        logger.info("=" * 60)

        # ---------- Сохранение модели ----------
        # Сохраняем модель: models/{tournament}/{model_name}.cbm
        tournament_models_dir = models_root / tournament_cfg.tournament.name
        tournament_models_dir.mkdir(parents=True, exist_ok=True)

        ext = tournament_cfg.model.get("save_format", "cbm")
        model_path = tournament_models_dir / f"{tournament_cfg.model.name}.{ext}"

        model.save_model(str(model_path))
        logger.info("Модель сохранена: %s", model_path)

        # ---------- Логирование модели в MLflow ----------
        mlflow.log_artifact(str(model_path), artifact_path="model_file")

        try:
            mlflow.catboost.log_model(model, artifact_path="model")
        except Exception as e:
            logger.warning("Не удалось залогировать модель через mlflow.catboost: %s", e)
            mlflow.set_tag("mlflow_catboost_log_error", str(e))

        logger.info("=" * 60)
        logger.info("Турнир %s: обучение завершено успешно", tournament_name)
        logger.info("=" * 60)
        return True

    except Exception as e:
        logger.error("Турнир %s: ошибка при обучении - %s", tournament_name, e)
        import traceback

        logger.error("Traceback:\n%s", traceback.format_exc())
        return False
    finally:
        # Гарантируем закрытие MLflow run при мультитурнирном обучении
        if mlflow.active_run() is not None:
            mlflow.end_run()


@hydra.main(config_path="../conf", config_name="config", version_base="1.3")
def run(cfg: DictConfig) -> None:
    """Запустить обучение модели для одного или всех турниров.

    Если cfg.tournament.name == "all", обучает модель для всех доступных турниров.
    Иначе обучает модель только для указанного турнира.

    Args:
        cfg: Hydra-конфиг с настройками обучения.
    """
    configure_logging(level=cfg.logging.level)

    # Определяем список турниров для обучения
    if cfg.tournament.name == "all":
        # Режим: обучить для всех турниров
        # Загружаем paths для определения турниров
        from omegaconf import OmegaConf

        paths_config_path = PROJECT_ROOT / "conf" / "paths.yaml"
        paths_cfg = OmegaConf.load(paths_config_path)

        processed_root = PROJECT_ROOT / paths_cfg.paths.processed_dir
        tournaments = get_available_tournaments(processed_root)

        if not tournaments:
            logger.error(
                "Не найдено ни одного турнира с обработанными данными в %s", processed_root
            )
            return

        logger.info("=" * 60)
        logger.info("МУЛЬТИТУРНИРНОЕ ОБУЧЕНИЕ")
        logger.info("Модель: %s", cfg.model.name)
        logger.info("Найдено турниров: %d", len(tournaments))
        logger.info("Турниры: %s", ", ".join(tournaments))
        logger.info("=" * 60)

        success_count = 0
        failed_tournaments = []

        for tournament_name in tournaments:
            success = train_single_tournament(tournament_name, cfg.model, cfg)
            if success:
                success_count += 1
            else:
                failed_tournaments.append(tournament_name)

        logger.info("=" * 60)
        logger.info("МУЛЬТИТУРНИРНОЕ ОБУЧЕНИЕ ЗАВЕРШЕНО")
        logger.info("Успешно обучено: %d/%d", success_count, len(tournaments))
        if failed_tournaments:
            logger.warning("Турниры с ошибками: %s", ", ".join(failed_tournaments))
        logger.info("=" * 60)

    else:
        # Режим: обучить для одного турнира
        success = train_single_tournament(cfg.tournament.name, cfg.model, cfg)
        if not success:
            logger.error("Обучение не удалось")
            return


if __name__ == "__main__":
    run()
