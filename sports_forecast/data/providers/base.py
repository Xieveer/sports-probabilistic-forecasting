"""Абстрактный контракт поставщика сырых данных (source adapter)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class SourceProviderError(Exception):
    """Базовая ошибка провайдера данных.

    Любой сбой на этапе ``fetch`` (кроме отсутствия локального файла у file-провайдера)
    или конфигурации провайдера должен прокидываться как подкласс этого типа, чтобы
    ingest мог логировать и пропускать турнир единообразно.
    """


class SourceDataNotFoundError(SourceProviderError, FileNotFoundError):
    """Локальный источник отсутствует (например, нет ``source.csv``).

    Наследование от :class:`FileNotFoundError` сохраняет семантику «файл не найден»
    для вызывающего кода, совместимого с проверками ``FileNotFoundError``.
    """


class SourceFetchError(SourceProviderError):
    """Не удалось получить данные с внешнего источника (HTTP, сеть, неверный ответ)."""


class SourceProvider(ABC):
    """Абстрактный поставщик файла матчей для ingest.

    Контракт: :meth:`fetch` возвращает путь к CSV или Parquet, который далее
    читается в ``ingest`` так же, как раньше читался ``data/source/<name>/source.csv``.

    Ошибки:
        - :class:`SourceDataNotFoundError` — ожидаемое отсутствие данных (файл).
        - :class:`SourceFetchError` и другие :class:`SourceProviderError` — сбои
          загрузки или неверная конфигурация провайдера.

    Доступность:
        :meth:`is_available` позволяет отсечь заведомо нерабочие конфигурации
        до вызова ``fetch`` (опционально).
    """

    @abstractmethod
    def fetch(self, source_name: str) -> Path:
        """Подготовить и вернуть путь к файлу данных для ``source_name``.

        Args:
            source_name: Имя каталога источника под ``data/source`` (как имя турнира в ingest).

        Returns:
            Существующий путь к CSV/Parquet, готовый для чтения pandas.

        Raises:
            SourceDataNotFoundError: Данные по заданному имени недоступны на диске.
            SourceFetchError: Сбой сетевой/внешней загрузки (для нелокальных провайдеров).
            SourceProviderError: Прочие ошибки провайдера или конфигурации.
        """

    def is_available(self) -> bool:
        """Проверка, что провайдер может быть использован в текущем окружении."""
        return True
