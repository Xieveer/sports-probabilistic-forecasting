"""Составы (NHL JSON в ячейках): пре-генератор на wide-данных.

Фичи из ``home_roster`` / ``away_roster`` (сериализованный JSON).

**TOI (time on ice):** эндпоинт сезонного roster Web API обычно **не** содержит TOI.
Не подставляем фиктивные значения: агрегаты по TOI требуют отдельного фида или
``playerByGameStats`` (вне скоупа R22.4). См. tech-debt в ``docs/cursor/refactor/backlog/reviewer-tech-debt.md``.

**Стартовый вратарь (эвристика):** номер свитера ``primary_goalie_sweater`` — у **первого**
вратаря в порядке перечисления API (``forwards``, ``defensemen``, ``goalies`` → первый
элемент с ``positionCode`` ``G``). Это лишь прокси стартера, не старт на конкретный матч.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any, Literal

import numpy as np
import pandas as pd

from sports_forecast.features.generators.base import BaseFeatureGenerator
from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)


PositionBucket = Literal["F", "D", "G"]


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


def _position_bucket(code: str | None) -> PositionBucket:
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


def _height_inches(p: dict[str, Any]) -> float | None:
    """Рост в дюймах из ``heightInInches`` или ``heightInCm`` (если есть)."""
    hi = p.get("heightInInches")
    if hi is not None:
        try:
            return float(int(hi))
        except (TypeError, ValueError):
            pass
    hc = p.get("heightInCm")
    if hc is not None:
        try:
            return float(int(hc)) / 2.54
        except (TypeError, ValueError):
            pass
    return None


def _injured_count(blob: dict[str, Any]) -> float:
    inj = blob.get("injured")
    if not isinstance(inj, list):
        return 0.0
    return float(len(inj))


def _young_skater_means(
    players: list[Any],
    ref: date,
    position: Literal["F", "D"],
    n: int,
) -> tuple[float, float]:
    """Средний возраст и средний рост (дюймы) у **N** самых молодых скатеров позиции."""
    if n <= 0:
        return float("nan"), float("nan")
    rows: list[tuple[float, float | None]] = []
    for p in players:
        if not isinstance(p, dict):
            continue
        if _position_bucket(p.get("positionCode")) != position:
            continue
        bd = p.get("birthDate") or p.get("birthdate")
        age = _age_on_date(str(bd), ref) if bd else None
        if age is None:
            continue
        rows.append((age, _height_inches(p)))
    rows.sort(key=lambda t: t[0])
    k = min(n, len(rows))
    if k == 0:
        return float("nan"), float("nan")
    picked = rows[:k]
    ages = [a for a, _ in picked]
    mean_age = float(sum(ages) / k)
    heights = [h for _, h in picked if h is not None]
    mean_h = float(sum(heights) / len(heights)) if heights else float("nan")
    return mean_age, mean_h


def _primary_goalie_sweater(players: list[Any]) -> float:
    """Номер свитера первого вратаря по порядку в ``players`` (см. модульный докстринг)."""
    for p in players:
        if not isinstance(p, dict):
            continue
        if _position_bucket(p.get("positionCode")) != "G":
            continue
        sn = p.get("sweaterNumber")
        if sn is None:
            return float("nan")
        try:
            return float(int(sn))
        except (TypeError, ValueError):
            return float("nan")
    return float("nan")


def _roster_metrics(
    blob: dict[str, Any],
    ref: date,
    *,
    young_skaters_n: int,
) -> dict[str, float]:
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

    y_n = max(0, young_skaters_n)
    yf_age, yf_h = _young_skater_means(players, ref, "F", y_n)
    yd_age, yd_h = _young_skater_means(players, ref, "D", y_n)
    g_sweater = _primary_goalie_sweater(players)

    return {
        "roster_size": float(len(players)),
        "num_forwards": float(nf),
        "num_defensemen": float(nd),
        "num_goalies": float(ng),
        "avg_player_age": float(sum(ages) / len(ages)) if ages else np.nan,
        "primary_goalie_sweater": g_sweater,
        "single_goalie": 1.0 if ng == 1 else 0.0,
        "young_forwards_mean_age": yf_age,
        "young_forwards_mean_height_in": yf_h,
        "young_defense_mean_age": yd_age,
        "young_defense_mean_height_in": yd_h,
        "injured_listed": _injured_count(blob),
    }


class NhlRosterFeatureGenerator(BaseFeatureGenerator):
    """Фичи из ``home_roster`` / ``away_roster`` (JSON).

    Требует колонки ``home_roster``, ``away_roster``, ``datetime``.

    Параметры конфига:
        young_skaters_n: число самых молодых скатеров (отдельно для F и D), по умолчанию 9.
            Обрезается по размеру группы на ростере.
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
        raw_n = config.get("young_skaters_n", 9)
        try:
            self._young_skaters_n = int(raw_n)
        except (TypeError, ValueError):
            self._young_skaters_n = 9
        if self._young_skaters_n < 0:
            self._young_skaters_n = 0

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
            "home_primary_goalie_sweater",
            "away_primary_goalie_sweater",
            "home_single_goalie",
            "away_single_goalie",
            "home_young_forwards_mean_age",
            "away_young_forwards_mean_age",
            "home_young_forwards_mean_height_in",
            "away_young_forwards_mean_height_in",
            "home_young_defense_mean_age",
            "away_young_defense_mean_age",
            "home_young_defense_mean_height_in",
            "away_young_defense_mean_height_in",
            "home_injured_listed",
            "away_injured_listed",
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
        h_gs: list[float] = []
        a_gs: list[float] = []
        h_sg: list[float] = []
        a_sg: list[float] = []
        h_yfa: list[float] = []
        a_yfa: list[float] = []
        h_yfh: list[float] = []
        a_yfh: list[float] = []
        h_yda: list[float] = []
        a_yda: list[float] = []
        h_ydh: list[float] = []
        a_ydh: list[float] = []
        h_inj: list[float] = []
        a_inj: list[float] = []

        for i in range(len(df)):
            ref_d = date(2000, 1, 1)
            ts = dt.iloc[i]
            if pd.notna(ts):
                ref_d = ts.date()
            hb = _parse_roster_blob(df.iloc[i].get("home_roster"))
            ab = _parse_roster_blob(df.iloc[i].get("away_roster"))
            hm = _roster_metrics(hb, ref_d, young_skaters_n=self._young_skaters_n)
            am = _roster_metrics(ab, ref_d, young_skaters_n=self._young_skaters_n)
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
            h_gs.append(hm["primary_goalie_sweater"])
            a_gs.append(am["primary_goalie_sweater"])
            h_sg.append(hm["single_goalie"])
            a_sg.append(am["single_goalie"])
            h_yfa.append(hm["young_forwards_mean_age"])
            a_yfa.append(am["young_forwards_mean_age"])
            h_yfh.append(hm["young_forwards_mean_height_in"])
            a_yfh.append(am["young_forwards_mean_height_in"])
            h_yda.append(hm["young_defense_mean_age"])
            a_yda.append(am["young_defense_mean_age"])
            h_ydh.append(hm["young_defense_mean_height_in"])
            a_ydh.append(am["young_defense_mean_height_in"])
            h_inj.append(hm["injured_listed"])
            a_inj.append(am["injured_listed"])

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
        df["home_primary_goalie_sweater"] = h_gs
        df["away_primary_goalie_sweater"] = a_gs
        df["home_single_goalie"] = h_sg
        df["away_single_goalie"] = a_sg
        df["home_young_forwards_mean_age"] = h_yfa
        df["away_young_forwards_mean_age"] = a_yfa
        df["home_young_forwards_mean_height_in"] = h_yfh
        df["away_young_forwards_mean_height_in"] = a_yfh
        df["home_young_defense_mean_age"] = h_yda
        df["away_young_defense_mean_age"] = a_yda
        df["home_young_defense_mean_height_in"] = h_ydh
        df["away_young_defense_mean_height_in"] = a_ydh
        df["home_injured_listed"] = h_inj
        df["away_injured_listed"] = a_inj
        return df
