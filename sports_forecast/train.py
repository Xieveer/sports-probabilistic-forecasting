"""
Training Entry Point v2.0 — Single-Experiment Architecture.

Каждый вызов ``train.py`` — один эксперимент (algorithm + features + seed).
Группировка в MLflow — через имя эксперимента (tournament + market + spec).
Множественные эксперименты — через ``hydra --multirun``.

Usage::

    # Одиночный запуск
    uv run python -m sports_forecast.train \\
        tournament=uel_kz_1 \\
        market=total \\
        market_spec=total_over \\
        market_spec.line=6.5 \\
        algorithm=catboost \\
        features=basic

    # Sweep через Hydra multirun
    uv run python -m sports_forecast.train --multirun \\
        tournament=uel_kz_1 \\
        market=total \\
        market_spec=total_over \\
        market_spec.line=6.5 \\
        algorithm=catboost,lgbm,logreg \\
        features=basic,advanced
"""

from pathlib import Path

import hydra
import mlflow
from omegaconf import DictConfig

from sports_forecast.config import (
    ConfigValidationError,
    print_config_summary,
    validate_experiment_config,
)
from sports_forecast.config.validation import apply_tournament_default_bookmaker
from sports_forecast.training.trainer import SingleExperimentRunner
from sports_forecast.utils.log_config import configure_logging, get_logger


logger = get_logger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent.resolve()


def _get_mlflow_experiment_name(cfg: DictConfig) -> str:
    """Сформировать имя MLflow эксперимента для группировки runs.

    Формат: ``{tournament}__{market}__{side}_{line}``

    Args:
        cfg: Hydra конфигурация.

    Returns:
        Имя эксперимента для MLflow.
    """
    tournament = cfg.tournament.name
    market = cfg.market.family
    side = cfg.market_spec.get("side", "")

    if market in ("total", "total_withOT", "handicap") and hasattr(cfg.market_spec, "line"):
        line = cfg.market_spec.line
        return f"{tournament}__{market}__{side}_{line}"

    if side:
        return f"{tournament}__{market}__{side}"

    return f"{tournament}__{market}"


@hydra.main(version_base="1.3", config_path="../conf", config_name="config")
def main(cfg: DictConfig) -> None:
    """Главная функция запуска обучения одного эксперимента.

    Args:
        cfg: Hydra конфигурация.
    """
    log_level = cfg.logging.get("level", "INFO")
    configure_logging(level=log_level)
    apply_tournament_default_bookmaker(cfg)

    logger.info("=" * 80)
    logger.info("TRAINING PIPELINE v2.0 (Single-Experiment Architecture)")
    logger.info("=" * 80)

    print_config_summary(cfg)

    try:
        logger.info("Валидация конфигурации...")
        validate_experiment_config(cfg, PROJECT_ROOT)
        logger.info("Конфигурация валидна")

    except ConfigValidationError as e:
        logger.error(str(e))
        logger.error("ОБУЧЕНИЕ ПРЕРВАНО из-за ошибок конфигурации")
        raise

    # Устанавливаем tracking URI из конфига (до set_experiment!)
    tracking_uri = cfg.mlflow.get("tracking_uri", "sqlite:///mlflow.db")
    mlflow.set_tracking_uri(tracking_uri)
    logger.info("MLflow Tracking URI: %s", tracking_uri)

    # Определяем имя MLflow эксперимента для группировки
    mlflow_experiment_name = _get_mlflow_experiment_name(cfg)
    mlflow.set_experiment(mlflow_experiment_name)
    logger.info("MLflow Experiment Name: %s", mlflow_experiment_name)

    # Запускаем один эксперимент
    logger.info("")
    logger.info("Запуск одиночного эксперимента...")
    logger.info("=" * 80)

    runner = SingleExperimentRunner(cfg, PROJECT_ROOT)
    success = runner.run_experiment()

    logger.info("")
    logger.info("=" * 80)
    if success:
        logger.info("ОБУЧЕНИЕ ЗАВЕРШЕНО УСПЕШНО")
    else:
        logger.error("ОБУЧЕНИЕ ЗАВЕРШЕНО С ОШИБКАМИ")
    logger.info("=" * 80)


if __name__ == "__main__":
    main()
