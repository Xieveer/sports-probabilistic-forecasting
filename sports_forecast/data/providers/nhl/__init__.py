"""Пакет загрузки данных NHL с ``api-web.nhle.com`` (тип провайдера ``nhl_web_api`` для ingest)."""

from __future__ import annotations

from sports_forecast.data.providers.nhl.provider import NhlWebApiSourceProvider


__all__ = ["NhlWebApiSourceProvider"]
