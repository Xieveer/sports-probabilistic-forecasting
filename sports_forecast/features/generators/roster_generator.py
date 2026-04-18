"""Составы (NHL JSON в ячейках): пре-генератор на wide-данных."""

from __future__ import annotations

import json
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from sports_forecast.features.generators.base import BaseFeatureGenerator
from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)


def _parse_roster_blob(raw: Any) -> dict[str, Any]:
    if raw is None or (isinstance(raw, float) and np.isnan(raw)):
        return {}
    s = str(raw).strip()
    if not s or s == "{}":
        return {}
    try:
        out = json.loads(s)
    except json.JSONDecodeError:
        return {}
    return out if isinstance(out, dict) else {}


def _position_bucket(code: str | None) -> str:
    c = str(code or "").upper()
    if c == "G":
        return "G"
    if c == "D":
        return "D"
    return "F"


def _age_on_date(birth_str: str, ref: date) -> float | None:
    if not birth_str or birth_str == "":
        return None
    try:
        bd = date.fromisoformat(birth_str[:10])
    except ValueError:
        return None
    return (ref - bd).days / 365.25


def _roster_metrics(blob: dict[str, Any], ref: date) -> dict[str, float]:
    players = blob.get("players") or []
    if not isinstance(players, list):
        players = []
    nf = nd = ng = 0
    ages: list[float] = []
    for p in players:
        if not isinstance(p, dict):
            continue
        bucket = _position_bucket(p.get("positionCode"))
        if bucket == "F":
            nf += 1
        elif bucket == "D":
            nd += 1
        else:
            ng += 1
        bd = p.get("birthDate") or p.get("birthdate")
        if bd:
            a = _age_on_date(str(bd), ref)
            if a is not None:
                ages.append(a)
    return {
        "roster_size": float(len(players)),
        "num_forwards": float(nf),
        "num_defensemen": float(nd),
        "num_goalies": float(ng),
        "avg_player_age": float(sum(ages) / len(ages)) if ages else np.nan,
    }


class NhlRosterFeatureGenerator(BaseFeatureGenerator):
    """Фичи из ``home_roster`` / ``away_roster`` (JSON).

    Требует колонки ``home_roster``, ``away_roster``, ``datetime``.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        config = dict(config)
        config["add_prefix"] = False
        super().__init__(config)
        self._datetime_column: str = str(config.get("datetime_column", "datetime"))
        self._required: list[str] = list(
            config.get(
                "required_columns",
                [self._datetime_column, "home_roster", "away_roster"],
            )
        )

    def get_feature_names(self) -> list[str]:
        return [
            "home_roster_size",
            "away_roster_size",
            "home_avg_player_age",
            "away_avg_player_age",
            "home_num_forwards",
            "away_num_forwards",
            "home_num_defensemen",
            "away_num_defensemen",
            "home_num_goalies",
            "away_num_goalies",
        ]

    def _missing(self, df: pd.DataFrame) -> list[str]:
        return [c for c in self._required if c not in df.columns]

    def get_actual_feature_names(self, df: pd.DataFrame) -> list[str]:
        if self._missing(df):
            return []
        return self.get_feature_names()

    def get_context_column_names(self) -> list[str]:
        return self.get_feature_names()

    def generate(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        miss = self._missing(df)
        if miss:
            logger.warning("%s: пропуск (нет колонок %s)", self.name, miss)
            return df

        dt = pd.to_datetime(df[self._datetime_column], errors="coerce", utc=True)

        home_sizes: list[float] = []
        away_sizes: list[float] = []
        home_ages: list[float] = []
        away_ages: list[float] = []
        hf: list[float] = []
        af: list[float] = []
        hd: list[float] = []
        ad: list[float] = []
        hg: list[float] = []
        ag: list[float] = []

        for i in range(len(df)):
            ref_d = date(2000, 1, 1)
            ts = dt.iloc[i]
            if pd.notna(ts):
                ref_d = ts.date()
            hb = _parse_roster_blob(df.iloc[i].get("home_roster"))
            ab = _parse_roster_blob(df.iloc[i].get("away_roster"))
            hm = _roster_metrics(hb, ref_d)
            am = _roster_metrics(ab, ref_d)
            home_sizes.append(hm["roster_size"])
            away_sizes.append(am["roster_size"])
            home_ages.append(hm["avg_player_age"])
            away_ages.append(am["avg_player_age"])
            hf.append(hm["num_forwards"])
            af.append(am["num_forwards"])
            hd.append(hm["num_defensemen"])
            ad.append(am["num_defensemen"])
            hg.append(hm["num_goalies"])
            ag.append(am["num_goalies"])

        df["home_roster_size"] = home_sizes
        df["away_roster_size"] = away_sizes
        df["home_avg_player_age"] = home_ages
        df["away_avg_player_age"] = away_ages
        df["home_num_forwards"] = hf
        df["away_num_forwards"] = af
        df["home_num_defensemen"] = hd
        df["away_num_defensemen"] = ad
        df["home_num_goalies"] = hg
        df["away_num_goalies"] = ag
        return df
