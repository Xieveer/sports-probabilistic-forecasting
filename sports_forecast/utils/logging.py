from __future__ import annotations

import logging
import sys
from logging import Logger
from pathlib import Path


_LOG_CONFIGURED = False


def configure_logging(
    level: str = "INFO",
    log_dir: Path | None = None,
    log_to_stdout: bool = True,
) -> None:
    """
    Глобальная настройка логов для всего проекта.

    Вызывается:
    - автоматически при первом get_logger(...)
    - или явно из entry-point (например, в train.py), чтобы:
      - поднять уровень до DEBUG
      - включить лог-файл.
    """
    global _LOG_CONFIGURED
    if _LOG_CONFIGURED:
        return

    handlers: list[logging.Handler] = []

    if log_to_stdout:
        stream_handler = logging.StreamHandler(sys.stdout)
        handlers.append(stream_handler)

    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_dir / "sports_forecast.log", encoding="utf-8")
        handlers.append(file_handler)

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    for handler in handlers:
        handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    for handler in handlers:
        root_logger.addHandler(handler)

    # если передали что-то кривое, по умолчанию будет INFO
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    _LOG_CONFIGURED = True


def get_logger(name: str) -> Logger:
    """
    Вернуть логгер с гарантированно настроенной глобальной конфигурацией.
    Если configure_logging(...) ещё не вызывался, включится дефолт:
    - уровень INFO
    - вывод в stdout
    """
    if not _LOG_CONFIGURED:
        configure_logging()
    return logging.getLogger(name)
