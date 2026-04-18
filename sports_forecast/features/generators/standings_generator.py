"""Турнирная таблица и «форма» (NHL): пре-генератор на wide-данных."""

from __future__ import annotations

from collections import defaultdict, deque
from datetime import timedelta
from typing import Any

import numpy as np
import pandas as pd

from sports_forecast.features.generators.base import BaseFeatureGenerator
from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)


class NhlStandingsFeatureGenerator(BaseFeatureGenerator):
    """Фичи из колонок таблицы (conference standing, P, GP) и формы последних матчей.

    Требует ``home_conference_standing``, ``home_P``, ``home_GP`` и симметрию для away.

    Фичи:
        conf_rank_diff, home_points_pct, away_points_pct, points_pct_diff,
        home_recent_form_5, away_recent_form_5, recent_form_5_diff
    """

    FEATURE_KEYS = [
        "conf_rank_diff",
        "home_points_pct",
        "away_points_pct",
        "points_pct_diff",
        "home_recent_form_5",
        "away_recent_form_5",
        "recent_form_5_diff",
    ]

    def __init__(self, config: dict[str, Any]) -> None:
        config = dict(config)
        config["add_prefix"] = False
        super().__init__(config)
        self._datetime_column: str = str(config.get("datetime_column", "datetime"))
        self._required: list[str] = list(
            config.get(
                "required_columns",
                [
                    "home_team",
                    "away_team",
                    self._datetime_column,
                    "home_conference_standing",
                    "away_conference_standing",
                    "home_P",
                    "away_P",
                    "home_GP",
                    "away_GP",
                    "home_points",
                    "away_points",
                ],
            )
        )
        self._form_window: int = int(config.get("form_window", 5))

    def get_feature_names(self) -> list[str]:
        return list(self.FEATURE_KEYS)

    def _missing(self, df: pd.DataFrame) -> list[str]:
        return [c for c in self._required if c not in df.columns]

    def get_actual_feature_names(self, df: pd.DataFrame) -> list[str]:
        if self._missing(df):
            return []
        return self.get_feature_names()

    def get_context_column_names(self) -> list[str]:
        return list(self.FEATURE_KEYS)

    def generate(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        miss = self._missing(df)
        if miss:
            logger.warning("%s: пропуск (нет колонок %s)", self.name, miss)
            return df

        dt_series = pd.to_datetime(df[self._datetime_column], errors="coerce", utc=True)
        df["_std_dt"] = dt_series.dt.normalize()

        order = df["_std_dt"].notna()
        idx_sorted = df.index[order].tolist()
        idx_sorted.sort(key=lambda i: (df.at[i, "_std_dt"], str(df.at[i, self._datetime_column])))

        history: dict[str, deque[tuple[pd.Timestamp, float]]] = defaultdict(deque)

        stored: dict[str, dict[int, Any]] = {k: {} for k in self.FEATURE_KEYS}

        for i in idx_sorted:
            ht = str(df.at[i, "home_team"]).strip()
            at = str(df.at[i, "away_team"]).strip()
            cur_t: pd.Timestamp = df.at[i, "_std_dt"]  # type: ignore[assignment]

            def form_sum(team: str, _ct: pd.Timestamp = cur_t) -> float:
                q = history[team]
                s = 0.0
                for t0, r in q:
                    if (_ct - t0) <= timedelta(days=400):
                        s += r
                return s

            hr = form_sum(ht)
            ar = form_sum(at)
            stored["home_recent_form_5"][i] = hr
            stored["away_recent_form_5"][i] = ar
            stored["recent_form_5_diff"][i] = hr - ar

            try:
                hsr = float(df.at[i, "home_conference_standing"])  # type: ignore[arg-type]
                asr = float(df.at[i, "away_conference_standing"])  # type: ignore[arg-type]
                stored["conf_rank_diff"][i] = hsr - asr
            except (TypeError, ValueError):
                stored["conf_rank_diff"][i] = np.nan

            try:
                hp = float(df.at[i, "home_P"])  # type: ignore[arg-type]
                hgp = float(df.at[i, "home_GP"])  # type: ignore[arg-type]
                home_pp = hp / (hgp * 2.0) if hgp > 0 else np.nan
            except (TypeError, ValueError):
                home_pp = np.nan
            try:
                ap = float(df.at[i, "away_P"])  # type: ignore[arg-type]
                agp = float(df.at[i, "away_GP"])  # type: ignore[arg-type]
                away_pp = ap / (agp * 2.0) if agp > 0 else np.nan
            except (TypeError, ValueError):
                away_pp = np.nan

            stored["home_points_pct"][i] = home_pp
            stored["away_points_pct"][i] = away_pp
            if not np.isnan(home_pp) and not np.isnan(away_pp):
                stored["points_pct_diff"][i] = home_pp - away_pp
            else:
                stored["points_pct_diff"][i] = np.nan

            hpts = df.at[i, "home_points"]
            apts = df.at[i, "away_points"]
            res_h = np.nan
            res_a = np.nan
            try:
                if pd.notna(hpts) and pd.notna(apts):
                    hf = float(hpts)  # type: ignore[arg-type]
                    af = float(apts)  # type: ignore[arg-type]
                    if hf > af:
                        res_h = 1.0
                        res_a = -1.0
                    elif hf < af:
                        res_h = -1.0
                        res_a = 1.0
                    else:
                        res_h = 0.0
                        res_a = 0.0
            except (TypeError, ValueError):
                pass

            if not np.isnan(res_h):
                dq = history[ht]
                dq.append((cur_t, res_h))  # type: ignore[arg-type]
                while len(dq) > self._form_window:
                    dq.popleft()
            if not np.isnan(res_a):
                dq = history[at]
                dq.append((cur_t, res_a))  # type: ignore[arg-type]
                while len(dq) > self._form_window:
                    dq.popleft()

        for fname in self.FEATURE_KEYS:
            df[fname] = df.index.map(lambda ix, fn=fname: stored[fn].get(ix))  # type: ignore[misc]

        df.drop(columns=["_std_dt"], inplace=True)
        return df
