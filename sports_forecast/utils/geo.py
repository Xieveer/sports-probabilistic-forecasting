"""Географические утилиты (расстояния между точками на сфере)."""

from __future__ import annotations

import math


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Большой круг между двумя точками на Земле (WGS84-аппроксимация сферы).

    Args:
        lat1, lon1: Широта/долгота первой точки в градусах.
        lat2, lon2: Широта/долгота второй точки в градусах.

    Returns:
        Расстояние в километрах.
    """
    r_km = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    h = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return float(2 * r_km * math.asin(min(1.0, math.sqrt(h))))
