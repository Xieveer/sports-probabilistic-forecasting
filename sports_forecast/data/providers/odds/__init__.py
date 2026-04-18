"""Провайдеры букмекерских линий вне ingest-пайплайна (The Odds API).

Колонки после merge в ``source.csv`` не подаются в :class:`~sports_forecast.features.pipeline.FeaturePipeline`.
"""

from sports_forecast.data.providers.odds.client import OddsApiClient, OddsApiQuotaSnapshot


__all__ = ["OddsApiClient", "OddsApiQuotaSnapshot"]
