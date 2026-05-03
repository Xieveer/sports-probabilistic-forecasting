"""Приблизительные координаты домашних арен NHL и UTC offset (стандартное время, без DST).

Используется пре-генератором расписания для travel/rest фич (R22.5). Координаты —
центр города/арены для оценки межгородских переездов, не сантиметровая точность.

``utc_offset_std`` — смещение от UTC в часах зимой (US/Canada standard), упрощённо
для оценки смены пояса между площадками; летнее время не моделируется.
"""

from __future__ import annotations

from typing import NamedTuple


class ArenaGeo(NamedTuple):
    """lat, lon в градусах; utc_offset_std — часы относительно UTC (зима)."""

    lat: float
    lon: float
    utc_offset_std: int


# Ключи — трёхбуквенные аббревиатуры как в NHL Web API / ``home_team``.
NHL_ARENA_GEO: dict[str, ArenaGeo] = {
    "ANA": ArenaGeo(33.8078, -117.8765, -8),  # Anaheim
    "ARI": ArenaGeo(33.4457, -111.9601, -7),  # Tempe (legacy Coyotes)
    "BOS": ArenaGeo(42.3662, -71.0621, -5),
    "BUF": ArenaGeo(42.8750, -78.8760, -5),
    "CAR": ArenaGeo(35.8033, -78.7219, -5),
    "CBJ": ArenaGeo(39.9693, -83.0061, -5),
    "CGY": ArenaGeo(51.0425, -114.0719, -7),
    "CHI": ArenaGeo(41.8806, -87.6742, -6),
    "COL": ArenaGeo(39.7487, -105.0076, -7),
    "DAL": ArenaGeo(32.7905, -96.8103, -6),
    "DET": ArenaGeo(42.3410, -83.0550, -5),
    "EDM": ArenaGeo(53.5469, -113.4978, -7),
    "FLA": ArenaGeo(26.1583, -80.3251, -5),
    "LAK": ArenaGeo(34.0430, -118.2673, -8),
    "MIN": ArenaGeo(44.9447, -93.1011, -6),
    "MTL": ArenaGeo(45.4961, -73.5693, -5),
    "NJD": ArenaGeo(40.7336, -74.1710, -5),
    "NSH": ArenaGeo(36.1591, -86.7785, -6),
    "NYI": ArenaGeo(40.7225, -73.5904, -5),  # UBS Arena
    "NYR": ArenaGeo(40.7505, -73.9934, -5),
    "OTT": ArenaGeo(45.2969, -75.9272, -5),
    "PHI": ArenaGeo(39.9012, -75.1720, -5),
    "PIT": ArenaGeo(40.4395, -79.9893, -5),
    "SEA": ArenaGeo(47.6220, -122.3540, -8),
    "SJS": ArenaGeo(37.3328, -121.9012, -8),
    "STL": ArenaGeo(38.6266, -90.2026, -6),
    "TBL": ArenaGeo(27.9425, -82.4519, -5),
    "TOR": ArenaGeo(43.6435, -79.3791, -5),
    "UTA": ArenaGeo(40.7690, -111.9011, -7),  # Salt Lake City area
    "VAN": ArenaGeo(49.2778, -123.1088, -8),
    "VGK": ArenaGeo(36.1028, -115.1782, -8),
    "WPG": ArenaGeo(49.8928, -97.1436, -6),
    "WSH": ArenaGeo(38.8982, -77.0209, -5),
}
