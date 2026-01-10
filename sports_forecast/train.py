"""
Training Entry Point для архитектуры v2.0 (Market-Algorithm Separation).

Запуск обучения с новой системой конфигов:
- Market + MarketSpec (вместо model)
- Algorithm (вместо model params)
- Recipe (план экспериментов)
- Parent/Nested MLflow runs

Usage:
    # Запуск recipe для total over 6.5 на uel_kz_1
    uv run python -m sports_forecast.train_v3 \\
        tournament=uel_kz_1 \\
        market=total \\
        market_spec=total_over \\
        market_spec.line=6.5 \\
        recipe=total_baseline

    # Быстрый тест (только dummy + logreg)
    uv run python -m sports_forecast.train_v3 \\
        tournament=uel_kz_1 \\
        market=total \\
        market_spec=total_over \\
        market_spec.line=6.5 \\
        recipe.algorithms=[dummy,logreg]
"""

from pathlib import Path

import hydra
import mlflow
from omegaconf import DictConfig, OmegaConf

from sports_forecast.config import (
    ConfigValidationError,
    print_config_summary,
    validate_parent_config,
)
from sports_forecast.training.trainer import ExperimentRunner
from sports_forecast.utils.log_config import configure_logging, get_logger


logger = get_logger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent.resolve()


@hydra.main(version_base="1.3", config_path="../conf", config_name="config")
def main(cfg: DictConfig) -> None:
    """
    Главная функция запуска обучения с архитектурой v2.0.

    Args:
        cfg: Hydra конфигурация

    Examples:
        >>> # Автоматический запуск через Hydra
        >>> # uv run python -m sports_forecast.train_v3 tournament=uel_kz_1 ...
    """
    # Настройка логирования
    log_level = cfg.logging.get("level", "INFO")
    configure_logging(level=log_level)

    logger.info("=" * 80)
    logger.info("🚀 TRAINING PIPELINE v2.0 (Market-Algorithm Architecture)")
    logger.info("=" * 80)

    # Печатаем сводку конфигурации
    print_config_summary(cfg)

    try:
        # Валидация конфигурации
        logger.info("🔍 Валидация конфигурации...")
        validate_parent_config(cfg, PROJECT_ROOT)
        logger.info("✓ Конфигурация валидна!")

    except ConfigValidationError as e:
        logger.error(str(e))
        logger.error("\n❌ ОБУЧЕНИЕ ПРЕРВАНО из-за ошибок конфигурации")
        raise

    # Создаём Parent MLflow Run
    parent_run_name = _get_parent_run_name(cfg)
    logger.info("📊 Создаём Parent MLflow Run: %s", parent_run_name)

    with mlflow.start_run(run_name=parent_run_name) as parent_run:
        # Логируем parent tags
        parent_tags = _get_parent_tags(cfg)
        mlflow.set_tags(parent_tags)

        # Логируем parent config
        config_str = OmegaConf.to_yaml(cfg, resolve=True)
        mlflow.log_text(config_str, "parent_config.yaml")

        logger.info("✓ Parent Run ID: %s", parent_run.info.run_id)
        logger.info("✓ Tags: %s", parent_tags)

        # Запускаем эксперименты согласно recipe
        logger.info("")
        logger.info("🧪 Запуск экспериментов согласно recipe '%s'", cfg.recipe.name)
        logger.info("=" * 80)

        runner = ExperimentRunner(cfg, PROJECT_ROOT, parent_run.info.run_id)
        results = runner.run_all_experiments()

        # Логируем сводку результатов
        logger.info("")
        logger.info("=" * 80)
        logger.info("✅ ОБУЧЕНИЕ ЗАВЕРШЕНО")
        logger.info("=" * 80)
        logger.info("Результаты:")
        for exp_name, success in results.items():
            status = "✓" if success else "✗"
            logger.info("  %s %s", status, exp_name)

        # Подсчитываем успешные
        successful = sum(1 for s in results.values() if s)
        total = len(results)
        logger.info("")
        logger.info("Успешно: %d/%d (%.1f%%)", successful, total, successful / total * 100)

        # Логируем итоговую метрику
        mlflow.log_metric("experiments_total", total)
        mlflow.log_metric("experiments_successful", successful)
        mlflow.log_metric("success_rate", successful / total if total > 0 else 0)

    logger.info("")
    logger.info("🎉 Все готово! Parent Run ID: %s", parent_run.info.run_id)


def _get_parent_run_name(cfg: DictConfig) -> str:
    """
    Сформировать имя Parent Run.

    Args:
        cfg: Конфигурация

    Returns:
        Имя в формате: tournament__market__side_line

    Examples:
        >>> name = _get_parent_run_name(cfg)
        >>> # "uel_kz_1__total__over_6.5"
    """
    tournament = cfg.tournament.name
    market = cfg.market.family
    side = cfg.market_spec.get("side", "")

    # Для total добавляем линию
    if market == "total" and hasattr(cfg.market_spec, "line"):
        line = cfg.market_spec.line
        return f"{tournament}__{market}__{side}_{line}"

    # Для winner просто side
    if side:
        return f"{tournament}__{market}__{side}"

    return f"{tournament}__{market}"


def _get_parent_tags(cfg: DictConfig) -> dict:
    """
    Сформировать теги для Parent Run.

    Args:
        cfg: Конфигурация

    Returns:
        Словарь тегов для MLflow

    Examples:
        >>> tags = _get_parent_tags(cfg)
        >>> # {"tournament": "uel_kz_1", "market_family": "total", ...}
    """
    tags = {
        "tournament": cfg.tournament.name,
        "market_family": cfg.market.family,
        "market_spec": cfg.market_spec.name,
        "recipe": cfg.recipe.name,
        "architecture": "v2.0",
    }

    # Добавляем side если есть
    if hasattr(cfg.market_spec, "side"):
        tags["side"] = cfg.market_spec.side

    # Добавляем line для total/handicap
    if cfg.market.family in ["total", "handicap"] and hasattr(cfg.market_spec, "line"):
        tags["line"] = str(cfg.market_spec.line)

    # Добавляем формат данных
    if hasattr(cfg.market_spec, "data_format"):
        tags["data_format"] = cfg.market_spec.data_format

    return tags


if __name__ == "__main__":
    main()
