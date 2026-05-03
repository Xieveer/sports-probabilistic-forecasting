"""Тесты ``sports_forecast.utils.geo``."""

from __future__ import annotations

from sports_forecast.utils.geo import haversine_km


def test_haversine_nyc_la_approximate() -> None:
    # NYC / LA центры — ожидаем ~3940 км
    d = haversine_km(40.7128, -74.0060, 34.0522, -118.2437)
    assert 3800 < d < 4200
