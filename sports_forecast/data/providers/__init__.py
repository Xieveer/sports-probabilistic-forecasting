"""Провайдеры исходных данных для ingest-слоя.

Каждый :class:`SourceProvider` доставляет файл CSV/Parquet (путь), который
дальше читает :mod:`sports_forecast.data.ingest` без изменения downstream-контракта.
"""

from sports_forecast.data.providers.base import (
    SourceDataNotFoundError,
    SourceFetchError,
    SourceProvider,
    SourceProviderError,
)
from sports_forecast.data.providers.file_provider import FileSourceProvider
from sports_forecast.data.providers.http_provider import HttpApiSourceProvider
from sports_forecast.data.providers.nhl.provider import NhlWebApiSourceProvider
from sports_forecast.data.providers.registry import (
    ProviderRegistry,
    UnknownProviderTypeError,
    get_provider,
)
from sports_forecast.data.providers.smart_tables.provider import SmartTablesSourceProvider


__all__ = [
    "FileSourceProvider",
    "HttpApiSourceProvider",
    "NhlWebApiSourceProvider",
    "SmartTablesSourceProvider",
    "ProviderRegistry",
    "SourceDataNotFoundError",
    "SourceFetchError",
    "SourceProvider",
    "SourceProviderError",
    "UnknownProviderTypeError",
    "get_provider",
]
