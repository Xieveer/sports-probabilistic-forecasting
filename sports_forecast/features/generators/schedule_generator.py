"""Плотность расписания, отдых и travel (NHL): пре-генератор на wide-данных."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Any

import pandas as pd

from sports_forecast.features.data.nhl_arena_geography import NHL_ARENA_GEO, ArenaGeo
from sports_forecast.features.generators.base import BaseFeatureGenerator
from sports_forecast.utils.geo import haversine_km
from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)


def _parse_arena_geo(node: Any) -> ArenaGeo | None:
    if not isinstance(node, dict):
        return None
    try:
        lat = float(node["lat"])
        lon = float(node["lon"])
        tz = int(node.get("utc_offset_std", node.get("utc_offset", 0)))
    except (KeyError, TypeError, ValueError):
        return None
    return ArenaGeo(lat, lon, tz)


class NhlScheduleFeatureGenerator(BaseFeatureGenerator):
    """Фичи расписания для команд home/away до текущего матча.

    Требует колонки ``home_team``, ``away_team``, ``datetime`` и маркер NHL
    (по умолчанию ``home_sog_ft`` — отсутствует у турниров не-NHL → генератор пропускается).

    **Travel / rest (R22.5):** при ``travel.enabled: true`` добавляются км между
    площадкой предыдущей игры команды и текущей (арена = ``home_team`` матча) и
    упрощённый сдвиг часового пояса (``utc_offset_std`` из справочника арен, без DST).

    Конфиг:
        type: nhl_schedule
        required_columns: [...]
        datetime_column: datetime
        travel:
          enabled: false | true
          arena_coords_override:  # опционально для тестов / кастомных координат
            NYR: {lat: 40.75, lon: -73.99, utc_offset_std: -5}
    """

    BASE_FEATURE_KEYS = [
        "home_days_since_last_game",
        "away_days_since_last_game",
        "home_games_in_last_7d",
        "away_games_in_last_7d",
        "home_games_in_last_14d",
        "away_games_in_last_14d",
        "home_is_back_to_back",
        "away_is_back_to_back",
        "rest_advantage",
    ]

    TRAVEL_FEATURE_KEYS = [
        "home_km_since_last_game",
        "away_km_since_last_game",
        "home_tz_shift_since_last",
        "away_tz_shift_since_last",
    ]

    def __init__(self, config: dict[str, Any]) -> None:
        config = dict(config)
        config["add_prefix"] = False
        super().__init__(config)
        self._datetime_column: str = str(config.get("datetime_column", "datetime"))
        self._required: list[str] = list(
            config.get(
                "required_columns",
                ["home_team", "away_team", self._datetime_column, "home_sog_ft"],
            )
        )
        travel_cfg_raw = config.get("travel")
        travel_cfg: dict[str, Any] = (
            dict(travel_cfg_raw) if isinstance(travel_cfg_raw, dict) else {}
        )
        self._travel_enabled: bool = bool(travel_cfg.get("enabled", False))
        override = travel_cfg.get("arena_coords_override")
        self._arena: dict[str, ArenaGeo]
        if isinstance(override, dict) and override:
            built: dict[str, ArenaGeo] = {}
            for k, v in override.items():
                kk = str(k).strip().upper()
                g = _parse_arena_geo(v)
                if kk and g:
                    built[kk] = g
            self._arena = built
        else:
            self._arena = NHL_ARENA_GEO

    def validate_config(self) -> None:
        super().validate_config()

    def get_feature_names(self) -> list[str]:
        names = list(self.BASE_FEATURE_KEYS)
        if self._travel_enabled:
            names.extend(self.TRAVEL_FEATURE_KEYS)
        return names

    def _missing(self, df: pd.DataFrame) -> list[str]:
        return [c for c in self._required if c not in df.columns]

    def get_actual_feature_names(self, df: pd.DataFrame) -> list[str]:
        if self._missing(df):
            return []
        return self.get_feature_names()

    def get_context_column_names(self) -> list[str]:
        return self.get_feature_names()

    def _geo(self, venue_home_team: str | None) -> ArenaGeo | None:
        if not venue_home_team:
            return None
        key = str(venue_home_team).strip().upper()
        return self._arena.get(key)

    def generate(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        miss = self._missing(df)
        if miss:
            logger.warning("%s: пропуск (нет колонок %s)", self.name, miss)
            return df

        dt_series = pd.to_datetime(df[self._datetime_column], errors="coerce", utc=True)
        df["_sched_dt"] = dt_series.dt.date

        order = df["_sched_dt"].notna() & df["home_team"].notna() & df["away_team"].notna()
        idx_sorted = df.index[order].tolist()
        idx_sorted.sort(key=lambda i: (df.at[i, "_sched_dt"], str(df.at[i, self._datetime_column])))

        last_game: dict[str, date | None] = {}
        game_dates: dict[str, list[date]] = defaultdict(list)
        last_venue_home_team: dict[str, str | None] = {}

        out: dict[str, dict[int, Any]] = {k: {} for k in self.get_feature_names()}

        for i in idx_sorted:
            cur: date = df.at[i, "_sched_dt"]  # type: ignore[assignment]
            ht = str(df.at[i, "home_team"]).strip()
            at = str(df.at[i, "away_team"]).strip()
            venue_home = ht

            def days_since(team: str, _cur: date = cur) -> float | None:
                lg = last_game.get(team)
                if lg is None:
                    return None
                return float((_cur - lg).days)

            def count_window(team: str, days: int, _cur: date = cur) -> float:
                lo = _cur - timedelta(days=days)
                return float(sum(1 for d in game_dates[team] if lo < d < _cur))

            hd = days_since(ht)
            ad = days_since(at)
            out["home_days_since_last_game"][i] = hd
            out["away_days_since_last_game"][i] = ad
            out["home_games_in_last_7d"][i] = count_window(ht, 7)
            out["away_games_in_last_7d"][i] = count_window(at, 7)
            out["home_games_in_last_14d"][i] = count_window(ht, 14)
            out["away_games_in_last_14d"][i] = count_window(at, 14)
            hb2b = 1.0 if hd is not None and hd <= 1.0 else 0.0
            ab2b = 1.0 if ad is not None and ad <= 1.0 else 0.0
            out["home_is_back_to_back"][i] = hb2b
            out["away_is_back_to_back"][i] = ab2b
            if hd is not None and ad is not None:
                out["rest_advantage"][i] = float(hd - ad)
            else:
                out["rest_advantage"][i] = None

            if self._travel_enabled:
                prev_vh = last_venue_home_team.get(ht)
                prev_va = last_venue_home_team.get(at)
                cur_g = self._geo(venue_home)
                prev_gh = self._geo(prev_vh) if prev_vh else None
                prev_ga = self._geo(prev_va) if prev_va else None

                if prev_gh is not None and cur_g is not None:
                    out["home_km_since_last_game"][i] = haversine_km(
                        prev_gh.lat, prev_gh.lon, cur_g.lat, cur_g.lon
                    )
                else:
                    out["home_km_since_last_game"][i] = None

                if prev_ga is not None and cur_g is not None:
                    out["away_km_since_last_game"][i] = haversine_km(
                        prev_ga.lat, prev_ga.lon, cur_g.lat, cur_g.lon
                    )
                else:
                    out["away_km_since_last_game"][i] = None

                if prev_gh is not None and cur_g is not None:
                    out["home_tz_shift_since_last"][i] = float(
                        cur_g.utc_offset_std - prev_gh.utc_offset_std
                    )
                else:
                    out["home_tz_shift_since_last"][i] = None

                if prev_ga is not None and cur_g is not None:
                    out["away_tz_shift_since_last"][i] = float(
                        cur_g.utc_offset_std - prev_ga.utc_offset_std
                    )
                else:
                    out["away_tz_shift_since_last"][i] = None

            game_dates[ht].append(cur)
            game_dates[at].append(cur)
            last_game[ht] = cur
            last_game[at] = cur
            last_venue_home_team[ht] = venue_home
            last_venue_home_team[at] = venue_home

        for fname in self.get_feature_names():
            df[fname] = df.index.map(lambda ix, fn=fname: out[fn].get(ix))  # type: ignore[misc]

        df.drop(columns=["_sched_dt"], inplace=True)
        return df
