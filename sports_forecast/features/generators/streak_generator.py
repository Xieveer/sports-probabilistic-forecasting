"""Серии побед/поражений и скользящий win-rate (long format, R27)."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import numpy as np
import pandas as pd

from sports_forecast.features.generators.base import BaseFeatureGenerator
from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)


def _apply_match_result(
    team: str,
    won: float,
    ws: dict[str, int],
    ls: dict[str, int],
    hist: dict[str, list[float]],
) -> None:
    """Обновить win/lose streak и историю исходов команды ``team`` после матча."""
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


def _win(plv: float, oppv: float) -> float:
    """1.0 если ``plv > oppv``, 0.0 если проигрыш, nan при неполных данных."""
    if np.isnan(plv) or np.isnan(oppv):
        return float("nan")
    return 1.0 if plv > oppv else 0.0


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
        n = len(long)
        feat_names = self.get_feature_names()
        out: dict[str, np.ndarray] = {
            name: np.full(n, np.nan, dtype=np.float64) for name in feat_names
        }

        ws: dict[str, int] = defaultdict(int)
        ls: dict[str, int] = defaultdict(int)
        hist: dict[str, list[float]] = defaultdict(list)

        ids = long["id"].to_numpy()
        sides = long["side"].astype(str).str.strip().str.lower().to_numpy()
        pl_pts = pd.to_numeric(long[pl_c], errors="coerce").to_numpy(dtype=np.float64, copy=False)
        opp_pts = pd.to_numeric(long[opp_c], errors="coerce").to_numpy(dtype=np.float64, copy=False)
        pl_names = long["pl"].astype(str).to_numpy()

        # O(n): id матча → позиция строки home / away (iloc).
        id_sides: dict[Any, dict[str, int]] = {}
        for pos in range(n):
            mid = ids[pos]
            side = sides[pos]
            bucket = id_sides.setdefault(mid, {})
            if side == "h":
                bucket["h"] = pos
            elif side == "a":
                bucket["a"] = pos

        dt = pd.to_datetime(long["datetime"], errors="coerce", utc=True)
        home_mask = sides == "h"
        home_pos = np.flatnonzero(home_mask)
        if len(home_pos) == 0:
            for name in feat_names:
                long[name] = out[name]
            return long

        order_df = pd.DataFrame(
            {"pos": home_pos, "_dt": dt.iloc[home_pos].to_numpy(), "id": ids[home_pos]}
        )
        order = order_df.sort_values(["_dt", "id"])["pos"].astype(int).tolist()

        for hi in order:
            mid = ids[hi]
            pair = id_sides.get(mid, {})
            ai = pair.get("a")
            if ai is None:
                logger.warning("%s: матч id=%s без away-строки — пропуск", self.name, mid)
                continue

            h_team = str(pl_names[hi])
            a_team = str(pl_names[ai])
            h_pl, h_opp = pl_pts[hi], opp_pts[hi]
            a_pl, a_opp = pl_pts[ai], opp_pts[ai]

            w_h = _win(float(h_pl), float(h_opp))
            w_a = _win(float(a_pl), float(a_opp))

            for row_pos, team, opp_team in ((hi, h_team, a_team), (ai, a_team, h_team)):
                out["pl_win_streak"][row_pos] = float(ws[team])
                out["pl_lose_streak"][row_pos] = float(ls[team])
                out["opp_win_streak"][row_pos] = float(ws[opp_team])
                out["opp_lose_streak"][row_pos] = float(ls[opp_team])
                out["streak_diff"][row_pos] = float(ws[team] - ws[opp_team])
                hist_list = hist[team]
                for wn in self._windows:
                    tail = hist_list[-wn:] if wn > 0 else []
                    rate = float(np.nanmean(tail)) if tail else float("nan")
                    out[f"pl_win_rate_last{wn}"][row_pos] = rate

                ho_list = hist[opp_team]
                for wn in self._windows:
                    tail_o = ho_list[-wn:] if wn > 0 else []
                    rate_o = float(np.nanmean(tail_o)) if tail_o else float("nan")
                    out[f"opp_win_rate_last{wn}"][row_pos] = rate_o

            _apply_match_result(h_team, w_h, ws, ls, hist)
            _apply_match_result(a_team, w_a, ws, ls, hist)

        for name in feat_names:
            long[name] = out[name]

        return long
