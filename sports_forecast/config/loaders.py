"""Unified config loaders for Hydra compose.

Centralizes all Hydra compose calls for loading tournament, source,
bookmaker, and paths configs. Replaces duplicated loading logic
scattered across ingest.py and clean.py.

Examples:
    >>> from sports_forecast.config.loaders import (
    ...     load_tournament_config,
    ...     load_paths_config,
    ...     load_source_config,
    ... )
    >>> tcfg = load_tournament_config("uel_kz_1")
    >>> pcfg = load_paths_config()
"""

from __future__ import annotations

from pathlib import Path

from hydra import compose, initialize_config_dir
from omegaconf import DictConfig

from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)

#: Корневая директория проекта
PROJECT_ROOT = Path(__file__).resolve().parents[2]

#: Путь к директории конфигов
CONF_DIR = str((PROJECT_ROOT / "conf").resolve())


def load_tournament_config(tournament_name: str) -> DictConfig:
    """Загрузить конфигурацию турнира через Hydra compose.

    Hydra ``compose()`` помещает конфиг в namespace config-группы
    (``tournament``), поэтому результат разворачивается до плоского
    DictConfig для совместимости с потребителями.

    Args:
        tournament_name: Название турнира (например: ``'uel_kz_1'``, ``'lp_ru'``).

    Returns:
        DictConfig с конфигурацией турнира (плоская, без обёртки ``tournament:``).

    Raises:
        FileNotFoundError: Если конфиг турнира не найден.

    Examples:
        >>> cfg = load_tournament_config('uel_kz_1')
        >>> cfg.name
        'uel_kz_1'
    """
    config_path = PROJECT_ROOT / "conf" / "tournament" / f"{tournament_name}.yaml"
    if not config_path.exists():
        raise FileNotFoundError(f"Конфиг турнира не найден: {config_path}")

    try:
        with initialize_config_dir(config_dir=CONF_DIR, version_base="1.3"):
            cfg = compose(
                config_name=f"tournament/{tournament_name}",
                return_hydra_config=False,
            )
        # Hydra compose оборачивает конфиг под ключ config-группы "tournament".
        # Разворачиваем для совместимости: cfg.tournament → cfg.
        if "tournament" in cfg:
            return cfg.tournament  # type: ignore[no-any-return]
        return cfg  # type: ignore[no-any-return]
    except Exception as e:
        logger.error("Ошибка загрузки конфига турнира %s: %s", tournament_name, e)
        raise


def load_source_config(source_name: str) -> DictConfig:
    """Загрузить конфигурацию источника данных через Hydra compose.

    Args:
        source_name: Название источника (например: ``'uel'``, ``'lp_eu'``).

    Returns:
        DictConfig с конфигурацией источника.

    Raises:
        FileNotFoundError: Если конфиг источника не найден.

    Examples:
        >>> cfg = load_source_config('uel')
        >>> cfg.split_strategy.enabled
        True
    """
    config_path = PROJECT_ROOT / "conf" / "source" / f"{source_name}.yaml"
    if not config_path.exists():
        raise FileNotFoundError(f"Конфиг источника не найден: {config_path}")

    try:
        with initialize_config_dir(config_dir=CONF_DIR, version_base="1.3"):
            cfg = compose(
                config_name=f"source/{source_name}",
                return_hydra_config=False,
            )
        if "source" in cfg:
            return cfg.source  # type: ignore[no-any-return]
        return cfg  # type: ignore[no-any-return]
    except Exception as e:
        logger.error("Ошибка загрузки конфига источника %s: %s", source_name, e)
        raise


def load_bookmaker_config(bookmaker: str) -> DictConfig | None:
    """Загрузить конфигурацию букмекера.

    Args:
        bookmaker: Название букмекера (например: ``'fonbet'``).

    Returns:
        DictConfig с конфигурацией букмекера или None если не найден.
    """
    config_path = PROJECT_ROOT / "conf" / "bookmaker" / f"{bookmaker}.yaml"
    if not config_path.exists():
        logger.warning("Конфиг букмекера %s не найден: %s", bookmaker, config_path)
        return None

    try:
        with initialize_config_dir(config_dir=CONF_DIR, version_base="1.3"):
            return compose(  # type: ignore[no-any-return]
                config_name=f"bookmaker/{bookmaker}",
                return_hydra_config=False,
            )
    except Exception as e:
        logger.error("Ошибка загрузки конфига букмекера %s: %s", bookmaker, e)
        return None


def load_paths_config() -> DictConfig:
    """Загрузить конфигурацию путей через Hydra compose.

    Returns:
        DictConfig с ключом ``paths`` содержащим все пути проекта.

    Examples:
        >>> cfg = load_paths_config()
        >>> cfg.paths.raw_dir
        'data/raw'
    """
    try:
        with initialize_config_dir(config_dir=CONF_DIR, version_base="1.3"):
            return compose(  # type: ignore[no-any-return]
                config_name="paths",
                return_hydra_config=False,
            )
    except Exception as e:
        logger.error("Ошибка загрузки paths config: %s", e)
        raise
