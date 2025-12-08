"""Модуль настройки логирования для проекта Sports Probabilistic Forecasting.

Этот модуль предоставляет централизованную систему логирования с поддержкой:

* Вывода в консоль (stdout)
* Записи в файлы
* Настраиваемых уровней логирования
* Единого формата сообщений

Основные компоненты:

* :func:`configure_logging` - глобальная настройка системы логирования
* :func:`get_logger` - получение настроенного логгера для модуля

Attributes:
    _LOG_CONFIGURED (bool): Флаг инициализации системы логирования.
        Предотвращает повторную настройку.

Example:
    Базовое использование в модуле::

        from sports_forecast.utils.logging import get_logger

        logger = get_logger(__name__)
        logger.info("Начало обработки данных")
        logger.warning("Найдены пропущенные значения")

    Настройка логирования в entry point::

        from pathlib import Path
        from sports_forecast.utils.logging import configure_logging

        # Включить DEBUG режим с записью в файл
        configure_logging(
            level="DEBUG",
            log_dir=Path("logs"),
            log_to_stdout=True
        )

    Только консольный вывод (по умолчанию)::

        from sports_forecast.utils.logging import get_logger

        # configure_logging() вызовется автоматически
        logger = get_logger(__name__)
        logger.info("Сообщение в консоль")

Note:
    Система логирования инициализируется автоматически при первом вызове
    :func:`get_logger`. Для изменения настроек по умолчанию вызовите
    :func:`configure_logging` явно перед использованием логгеров.

See Also:
    * :mod:`logging` - стандартная библиотека Python для логирования
    * `Python Logging HOWTO <https://docs.python.org/3/howto/logging.html>`_
"""

from __future__ import annotations

import logging
import sys
from logging import Logger
from pathlib import Path


#: Флаг инициализации системы логирования
_LOG_CONFIGURED = False


def configure_logging(
    level: str = "INFO",
    log_dir: Path | None = None,
    log_to_stdout: bool = True,
) -> None:
    """Глобальная настройка логов для всего проекта.

    Настраивает корневой логгер Python с единым форматом сообщений
    и указанными обработчиками (handlers). Вызывается автоматически
    при первом :func:`get_logger` или явно из entry-point.

    Формат сообщений::

        2025-01-08 14:30:45 | INFO     | sports_forecast.data | Загружено 380 записей

    Args:
        level: Уровень логирования. Допустимые значения:

            * ``"DEBUG"`` - детальная отладочная информация
            * ``"INFO"`` - общая информация о работе (по умолчанию)
            * ``"WARNING"`` - предупреждения о потенциальных проблемах
            * ``"ERROR"`` - ошибки, не прерывающие работу
            * ``"CRITICAL"`` - критические ошибки

        log_dir: Директория для сохранения лог-файлов.

            * Если ``None`` - логи только в консоль
            * Если указан путь - создается файл ``sports_forecast.log``
            * Директория создается автоматически, если не существует

        log_to_stdout: Выводить ли логи в консоль (stdout).

            * ``True`` - вывод в консоль включен (по умолчанию)
            * ``False`` - только в файл (если указан ``log_dir``)

    Returns:
        None

    Raises:
        OSError: Если не удается создать директорию для логов или файл.

    Examples:
        Базовая настройка (INFO в консоль)::

            >>> from sports_forecast.utils.logging import configure_logging
            >>> configure_logging()

        DEBUG режим с записью в файл::

            >>> from pathlib import Path
            >>> configure_logging(
            ...     level="DEBUG",
            ...     log_dir=Path("logs"),
            ...     log_to_stdout=True
            ... )

        Только файловое логирование::

            >>> configure_logging(
            ...     level="INFO",
            ...     log_dir=Path("logs"),
            ...     log_to_stdout=False
            ... )

        Настройка из entry point (train.py)::

            >>> # train.py
            >>> from pathlib import Path
            >>> from sports_forecast.utils.logging import configure_logging, get_logger
            >>>
            >>> # Настроить логирование перед импортом других модулей
            >>> configure_logging(level="DEBUG", log_dir=Path("logs"))
            >>>
            >>> logger = get_logger(__name__)
            >>> logger.info("Начало обучения модели")

    Note:
        * Функция защищена от повторного вызова флагом ``_LOG_CONFIGURED``
        * При некорректном значении ``level`` используется ``INFO``
        * Все логгеры в проекте наследуют эти настройки
        * Файл логов создается в кодировке UTF-8

    Warning:
        Вызов :func:`configure_logging` после создания логгеров не изменит
        их настройки. Вызывайте эту функцию в начале программы.

    See Also:
        * :func:`get_logger` - получение настроенного логгера
        * :mod:`logging` - документация стандартной библиотеки
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
    """Получить логгер с гарантированно настроенной конфигурацией.

    Возвращает экземпляр :class:`logging.Logger` для указанного модуля.
    Если система логирования еще не инициализирована, автоматически
    вызывается :func:`configure_logging` с настройками по умолчанию.

    Args:
        name: Имя логгера, обычно ``__name__`` модуля.
            Используется для идентификации источника сообщений.

    Returns:
        Logger: Настроенный экземпляр логгера.

    Examples:
        Стандартное использование в модуле::

            >>> from sports_forecast.utils.logging import get_logger
            >>>
            >>> logger = get_logger(__name__)
            >>> logger.info("Модуль инициализирован")
            2025-01-08 14:30:45 | INFO     | sports_forecast.data.ingest | Модуль инициализирован

        Логирование с разными уровнями::

            >>> logger = get_logger(__name__)
            >>> logger.debug("Детальная информация для отладки")
            >>> logger.info("Общая информация о работе")
            >>> logger.warning("Предупреждение о потенциальной проблеме")
            >>> logger.error("Произошла ошибка")
            >>> logger.critical("Критическая ошибка!")

        Логирование с форматированием::

            >>> logger = get_logger(__name__)
            >>> tournament = "premier_league_2023"
            >>> count = 380
            >>> logger.info("Турнир %s: загружено %d записей", tournament, count)
            2025-01-08 14:30:45 | INFO     | ... | Турнир premier_league_2023: загружено 380 записей

        Использование в разных модулях::

            >>> # sports_forecast/data/ingest.py
            >>> logger = get_logger(__name__)  # __name__ = 'sports_forecast.data.ingest'
            >>> logger.info("Загрузка данных")
            >>>
            >>> # sports_forecast/features/clean.py
            >>> logger = get_logger(__name__)  # __name__ = 'sports_forecast.features.clean'
            >>> logger.info("Очистка данных")

    Note:
        * При первом вызове автоматически инициализируется система логирования
        * Настройки по умолчанию: уровень INFO, вывод в stdout
        * Для изменения настроек вызовите :func:`configure_logging` явно
        * Рекомендуется использовать ``__name__`` в качестве имени логгера

    See Also:
        * :func:`configure_logging` - настройка системы логирования
        * :class:`logging.Logger` - документация класса Logger
    """
    if not _LOG_CONFIGURED:
        configure_logging()
    return logging.getLogger(name)
