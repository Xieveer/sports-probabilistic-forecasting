"""Серии побед/поражений и скользящий win-rate (long format, R27)."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import numpy as np
import pandas as pd

from sports_forecast.features.generators.base import BaseFeatureGenerator
from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)


class StreakFeatureGenerator(BaseFeatureGenerator):
    """Фичи серий и win-rate до матча (без утечки текущего результата).

    Состояние команд обновляется **один раз на матч** (строка ``side == 'h'``),
    затем для обеих long-строк матча подставляются одни и те же pre-match streaks.

    Параметры конфига:
        win_mode: ``goals_full`` (по умолчанию) или ``points``.
        win_rate_windows: список окон для ``pl_win_rate_last{N}`` / ``opp_*``.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        config = dict(config)
        self._win_mode = str(config.get("win_mode", "goals_full")).lower()
        raw_w = config.get("win_rate_windows", [5, 10])
        self._windows: tuple[int, ...]
        if not isinstance(raw_w, (list, tuple)) or not raw_w:
            self._windows = (5, 10)
        else:
            self._windows = tuple(int(x) for x in raw_w)
        super().__init__(config)

    def validate_config(self) -> None:
        super().validate_config()
        if self._win_mode not in {"goals_full", "points"}:
            raise ValueError(
                f"{self.name}: win_mode must be goals_full or points, got {self._win_mode!r}"
            )

    def get_feature_names(self) -> list[str]:
        names = [
            "pl_win_streak",
            "pl_lose_streak",
            "opp_win_streak",
            "opp_lose_streak",
            "streak_diff",
        ]
        for w in self._windows:
            names.append(f"pl_win_rate_last{w}")
            names.append(f"opp_win_rate_last{w}")
        return names

    def _win_columns(self, df: pd.DataFrame) -> tuple[str, str]:
        if (
            self._win_mode == "goals_full"
            and "pl_goals_full" in df.columns
            and "opp_goals_full" in df.columns
        ):
            return "pl_goals_full", "opp_goals_full"
        return "pl_points", "opp_points"

    def generate(self, df: pd.DataFrame) -> pd.DataFrame:
        required = ["datetime", "id", "side", "pl", "opp"]
        missing = [c for c in required if c not in df.columns]
        if missing:
            raise ValueError(f"{self.name}: отсутствуют колонки: {missing}")

        pl_c, opp_c = self._win_columns(df)
        if pl_c not in df.columns or opp_c not in df.columns:
            raise ValueError(
                f"{self.name}: нет колонок для win_mode={self._win_mode}: {pl_c}, {opp_c}"
            )

        long = df.copy()
        for name in self.get_feature_names():
            long[name] = np.nan

        ws: dict[str, int] = defaultdict(int)
        ls: dict[str, int] = defaultdict(int)
        hist: dict[str, list[float]] = defaultdict(list)

        dt = pd.to_datetime(long["datetime"], errors="coerce", utc=True)
        home_rows = long["side"].astype(str) == "h"
        # Один представитель на матч (домашняя сторона), хронология по времени
        order = (
            long.loc[home_rows].assign(_dt=dt[home_rows]).sort_values(["_dt", "id"]).index.to_list()
        )

        for hi in order:
            row_h = long.loc[hi]
            mid = row_h["id"]
            same = long.index[long["id"] == mid]
            away_idx = None
            for j in same:
                if str(long.loc[j, "side"]) != "h":
                    away_idx = j
                    break
            if away_idx is None:
                logger.warning("%s: матч id=%s без away-строки — пропуск", self.name, mid)
                continue

            row_a = long.loc[away_idx]
            h_team, a_team = row_h["pl"], row_h["opp"]
            try:
                h_pl, h_opp = float(row_h[pl_c]), float(row_h[opp_c])
                a_pl, a_opp = float(row_a[pl_c]), float(row_a[opp_c])
            except (TypeError, ValueError):
                h_pl = h_opp = a_pl = a_opp = float("nan")

            def _win(plv: float, oppv: float) -> float:
                if np.isnan(plv) or np.isnan(oppv):
                    return float("nan")
                return 1.0 if plv > oppv else 0.0

            w_h = _win(h_pl, h_opp)
            # Для away-строки pl=a_team: победа если a_pl > a_opp
            w_a = _win(a_pl, a_opp)

            teams = (str(h_team), str(a_team))
            for idx, team, opp_team in (
                (hi, teams[0], teams[1]),
                (away_idx, teams[1], teams[0]),
            ):
                long.loc[idx, "pl_win_streak"] = ws[team]
                long.loc[idx, "pl_lose_streak"] = ls[team]
                long.loc[idx, "opp_win_streak"] = ws[opp_team]
                long.loc[idx, "opp_lose_streak"] = ls[opp_team]
                long.loc[idx, "streak_diff"] = float(ws[team] - ws[opp_team])
                hist_list = hist[team]
                for wn in self._windows:
                    tail = hist_list[-wn:] if wn > 0 else []
                    rate = float(np.nanmean(tail)) if tail else float("nan")
                    long.loc[idx, f"pl_win_rate_last{wn}"] = rate

                ho_list = hist[opp_team]
                for wn in self._windows:
                    tail_o = ho_list[-wn:] if wn > 0 else []
                    rate_o = float(np.nanmean(tail_o)) if tail_o else float("nan")
                    long.loc[idx, f"opp_win_rate_last{wn}"] = rate_o

            # Обновление состояния после матча (один раз на команду)
            def _apply(team: str, won: float) -> None:
                if np.isnan(won):
                    ws[team] = 0
                    ls[team] = 0
                    hist[team].append(float("nan"))
                    return
                if won == 1.0:
                    ws[team] = ws[team] + 1
                    ls[team] = 0
                    hist[team].append(1.0)
                else:
                    ws[team] = 0
                    ls[team] = ls[team] + 1
                    hist[team].append(0.0)

            _apply(str(h_team), w_h)
            _apply(str(a_team), w_a)

        return long
