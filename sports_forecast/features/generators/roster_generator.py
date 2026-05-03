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
from collections import defaultdict
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


def _roster_sweater_set(raw: Any) -> frozenset[int]:
    """Множество номеров свитеров активного ростера (``players``)."""
    blob = _parse_roster_blob(raw)
    players = blob.get("players") or []
    if not isinstance(players, list):
        return frozenset()
    out: set[int] = set()
    for p in players:
        if not isinstance(p, dict):
            continue
        sn = p.get("sweaterNumber")
        if sn is None:
            continue
        try:
            out.add(int(sn))
        except (TypeError, ValueError):
            continue
    return frozenset(out)


def _jaccard_sweaters(prev: frozenset[int] | None, cur: frozenset[int]) -> float:
    if prev is None:
        return float("nan")
    if not prev and not cur:
        return float("nan")
    union = len(prev | cur)
    if union == 0:
        return float("nan")
    return float(len(prev & cur)) / float(union)


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
        self._lineup_enabled = bool(config.get("lineup_features_enabled", True))
        try:
            self._stability_window = max(1, int(config.get("stability_window", 5)))
        except (TypeError, ValueError):
            self._stability_window = 5

    @staticmethod
    def _lineup_column_names() -> list[str]:
        return [
            "home_lineup_continuity",
            "away_lineup_continuity",
            "home_roster_mean_seniority",
            "away_roster_mean_seniority",
            "home_roster_min_seniority",
            "away_roster_min_seniority",
            "home_roster_stability",
            "away_roster_stability",
        ]

    def get_feature_names(self) -> list[str]:
        base = [
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
        if self._lineup_enabled:
            return base + self._lineup_column_names()
        return base

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
        if self._lineup_enabled:
            self._add_lineup_features(df, dt)
        return df

    def _add_lineup_features(self, df: pd.DataFrame, dt: pd.Series) -> None:
        """R27: Jaccard непрерывности состава, seniority, stability по последним матчам."""
        for c in self._lineup_column_names():
            df[c] = np.nan
        if "home_team" not in df.columns or "away_team" not in df.columns:
            logger.warning("%s: lineup фичи — нет home_team/away_team, заполнено NaN", self.name)
            return

        last_sw: dict[str, frozenset[int]] = {}
        cum_app: dict[tuple[str, int], int] = {}
        cont_hist: dict[str, list[float]] = defaultdict(list)
        w = self._stability_window

        for idx in dt.sort_values().index:
            r = df.loc[idx]
            ht_raw, at_raw = r.get("home_team"), r.get("away_team")
            ht = (
                str(ht_raw).strip()
                if ht_raw is not None and not (isinstance(ht_raw, float) and np.isnan(ht_raw))
                else ""
            )
            at = (
                str(at_raw).strip()
                if at_raw is not None and not (isinstance(at_raw, float) and np.isnan(at_raw))
                else ""
            )
            if not ht or not at:
                continue

            hs = _roster_sweater_set(r.get("home_roster"))
            aws = _roster_sweater_set(r.get("away_roster"))

            def _one_team(team: str, cur: frozenset[int], prefix: str, row_idx: Any) -> None:
                prev = last_sw.get(team)
                cont = _jaccard_sweaters(prev, cur)
                sens = [float(cum_app.get((team, sn), 0)) for sn in cur] if cur else []
                mean_s = float(np.mean(sens)) if sens else float("nan")
                min_s = float(np.min(sens)) if sens else float("nan")
                hist = cont_hist[team]
                cont_f = float(cont) if not np.isnan(cont) else float("nan")
                combined = hist + ([cont_f] if not np.isnan(cont_f) else [])
                stab_vals = combined[-w:] if w > 0 else combined
                stab = float(np.mean(stab_vals)) if stab_vals else float("nan")
                df.loc[row_idx, f"{prefix}_lineup_continuity"] = cont
                df.loc[row_idx, f"{prefix}_roster_mean_seniority"] = mean_s
                df.loc[row_idx, f"{prefix}_roster_min_seniority"] = min_s
                df.loc[row_idx, f"{prefix}_roster_stability"] = stab
                if not np.isnan(cont_f):
                    cont_hist[team].append(cont_f)
                for sn in cur:
                    k = (team, sn)
                    cum_app[k] = cum_app.get(k, 0) + 1
                last_sw[team] = cur

            _one_team(ht, hs, "home", idx)
            _one_team(at, aws, "away", idx)
