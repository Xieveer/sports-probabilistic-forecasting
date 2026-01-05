"""
Обучение моделей через новую систему ModelTrainer.

Поддерживает:
- Одиночные модели (dummy, catboost, lgbm, logreg)
- Ансамбли (stacking)
- TSCV с 4 фолдами
- Optuna оптимизацию
- Калибровку
- Shadow/Prod модели
- MLflow логирование

Запуск:
    # Одиночная модель
    uv run python -m sports_forecast.train_v2 model=single/catboost tournament=uel_kz_1

    # С Optuna
    uv run python -m sports_forecast.train_v2 model=single/catboost tournament=uel_kz_1 use_optuna=true

    # Ансамбль
    uv run python -m sports_forecast.train_v2 model=ensemble/stacking_win tournament=uel_kz_1

    # Все турниры
    uv run python -m sports_forecast.train_v2 model=single/catboost tournament=all
"""

from __future__ import annotations

from pathlib import Path

import hydra
from omegaconf import DictConfig

from sports_forecast.training.trainer import ModelTrainer
from sports_forecast.utils.log_config import configure_logging, get_logger

PROJECT_ROOT = Path(__file__).resolve().parents[1]
logger = get_logger(__name__)


@hydra.main(config_path="../conf", config_name="config", version_base="1.3")
def main(cfg: DictConfig) -> None:
    """
    Главная функция обучения через ModelTrainer.

    Args:
        cfg: Hydra конфигурация.
    """
    configure_logging(level=cfg.logging.level)

    logger.info("=" * 60)
    logger.info("SPORTS FORECAST - ОБУЧЕНИЕ МОДЕЛЕЙ V2")
    logger.info("=" * 60)

    # Создаём trainer
    trainer = ModelTrainer(cfg, PROJECT_ROOT)

    # Определяем тип модели
    model_type = cfg.model.get("type", "single")
    model_name = cfg.model.name
    tournament = cfg.tournament.name

    # Параметры
    use_optuna = cfg.get("use_optuna", False)
    use_calibration = cfg.get("use_calibration", True)

    logger.info("Model: %s (%s)", model_name, model_type)
    logger.info("Tournament: %s", tournament)
    logger.info("Use Optuna: %s", use_optuna)
    logger.info("Use Calibration: %s", use_calibration)
    logger.info("=" * 60)

    # Обучение
    if tournament == "all":
        # Мультитурнирное обучение
        if model_type == "ensemble":
            logger.error("Мультитурнирное обучение ансамблей пока не поддерживается")
            return

        results = trainer.train_all_tournaments(
            model_name=model_name,
            use_optuna=use_optuna,
        )

        # Статистика
        success_count = sum(results.values())
        total_count = len(results)

        logger.info("=" * 60)
        logger.info("ИТОГО: %d/%d турниров успешно", success_count, total_count)

        if success_count < total_count:
            failed = [t for t, success in results.items() if not success]
            logger.warning("Неудачные турниры: %s", ", ".join(failed))

        logger.info("=" * 60)

    else:
        # Одиночный турнир
        if model_type == "single":
            success = trainer.train_single(
                model_name=model_name,
                tournament=tournament,
                use_optuna=use_optuna,
                use_calibration=use_calibration,
            )
        elif model_type == "ensemble":
            success = trainer.train_ensemble(
                ensemble_name=model_name,
                tournament=tournament,
            )
        else:
            logger.error("Неизвестный тип модели: %s", model_type)
            return

        if success:
            logger.info("✓ Обучение успешно завершено")
        else:
            logger.error("✗ Обучение завершилось с ошибками")


if __name__ == "__main__":
    main()

