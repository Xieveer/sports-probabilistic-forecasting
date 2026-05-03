"""Турнирная таблица и «форма» (NHL): пре-генератор на wide-данных.

Мотивация / плей-офф-контекст (R22.6): при ``motivation.enabled`` добавляются фичи
гонки за очками, отставания от линии плей-оффа (по слотам в конференции) и
грубый «зазор» мест в таблице. Ранги ``*_conference_standing`` — внутри
конференции; для межконференцеских матчей регулярки сравнение мест шумное
(tech-debt: нет признака одной конференции без новых колонок).

**Tech-debt:** ``same_conference_standing_pressure`` не реализуется — из wide-CSV
нельзя надёжно вывести, что обе команды в одной конференции, не добавляя полей
(``home_conference`` / ``away_conference`` и т.п.).
"""

from __future__ import annotations

from collections import defaultdict, deque
from datetime import timedelta
from typing import Any

import numpy as np
import pandas as pd

from sports_forecast.features.generators.base import BaseFeatureGenerator
from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)


def _playoffs_phase_flag(val: Any) -> float:
    """Бинарный признак фазы: плей-оффы vs не плей-оффы.

    Returns:
        1.0 — playoffs; 0.0 — regular / preseason; nan — неизвестно или пусто.
    """
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return np.nan
    if pd.isna(val):
        return np.nan
    s = str(val).strip().lower()
    if s in ("playoffs", "playoff"):
        return 1.0
    if s in ("regular", "reg"):
        return 0.0
    if s in ("preseason", "pre"):
        return 0.0
    return np.nan


def _extended_game_flag(val: Any) -> float:
    """Слабый контекст «длина матча»: регламент vs овертайм/буллиты.

    Имеет смысл для завершённых строк; для пре-игровых снимков обычно пусто → nan.

    Returns:
        1.0 — OT/SO; 0.0 — REG; nan — нет данных или неразрешимо.
    """
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return np.nan
    if pd.isna(val):
        return np.nan
    s = str(val).strip().upper()
    if not s:
        return np.nan
    if s == "REG":
        return 0.0
    if s in ("OT", "SO"):
        return 1.0
    return np.nan


def _playoff_spots_out(rank: float, line_slots: int) -> float:
    """Число «мест» до зоны плей-оффа: max(0, rank − line_slots), ранг 1 — лучший."""
    if line_slots < 1:
        return np.nan
    if np.isnan(rank):
        return np.nan
    return max(0.0, float(rank) - float(line_slots))


class NhlStandingsFeatureGenerator(BaseFeatureGenerator):
    """Фичи из колонок таблицы (conference standing, P, GP) и формы последних матчей.

    Требует ``home_conference_standing``, ``home_P``, ``home_GP`` и симметрию для away.

    Базовые фичи (``FEATURE_KEYS``):
        conf_rank_diff, home_points_pct, away_points_pct, points_pct_diff,
        home_recent_form_5, away_recent_form_5, recent_form_5_diff

    Мотивация (``motivation.enabled``, по умолчанию True): очки в таблице, GP,
    отставание от линии плей-оффа, |Δrank|; опционально ``game_type`` и ``match_end``.
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

    MOTIVATION_CORE_KEYS = [
        "standing_points_diff",
        "gp_diff",
        "home_playoff_spots_out",
        "away_playoff_spots_out",
        "playoff_spots_out_diff",
        "standing_rank_gap",
    ]
    MOTIVATION_GAME_TYPE_KEY = "motivation_playoffs_phase"
    MOTIVATION_MATCH_END_KEY = "motivation_extended_game"

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
        motivation_cfg_raw = config.get("motivation")
        motivation_cfg: dict[str, Any] = (
            dict(motivation_cfg_raw) if isinstance(motivation_cfg_raw, dict) else {}
        )
        self._motivation_enabled: bool = bool(motivation_cfg.get("enabled", True))
        self._playoff_line_slots: int = int(motivation_cfg.get("playoff_line_slots", 8))

    def get_expected_feature_names(self) -> list[str]:
        names = list(self.FEATURE_KEYS)
        if self._motivation_enabled:
            names.extend(self.MOTIVATION_CORE_KEYS)
            names.append(self.MOTIVATION_GAME_TYPE_KEY)
            names.append(self.MOTIVATION_MATCH_END_KEY)
        return names

    def get_feature_names(self) -> list[str]:
        return self.get_expected_feature_names()

    def _missing(self, df: pd.DataFrame) -> list[str]:
        return [c for c in self._required if c not in df.columns]

    def get_actual_feature_names(self, df: pd.DataFrame) -> list[str]:
        if self._missing(df):
            return []
        names = list(self.FEATURE_KEYS)
        if not self._motivation_enabled:
            return names
        names.extend(self.MOTIVATION_CORE_KEYS)
        if "game_type" in df.columns:
            names.append(self.MOTIVATION_GAME_TYPE_KEY)
        if "match_end" in df.columns:
            names.append(self.MOTIVATION_MATCH_END_KEY)
        return names

    def get_context_column_names(self) -> list[str]:
        return self.get_feature_names()

    def generate(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        miss = self._missing(df)
        if miss:
            logger.warning("%s: пропуск (нет колонок %s)", self.name, miss)
            return df

        output_keys = self.get_actual_feature_names(df)
        dt_series = pd.to_datetime(df[self._datetime_column], errors="coerce", utc=True)
        df["_std_dt"] = dt_series.dt.normalize()

        order = df["_std_dt"].notna()
        idx_sorted = df.index[order].tolist()
        idx_sorted.sort(key=lambda i: (df.at[i, "_std_dt"], str(df.at[i, self._datetime_column])))

        history: dict[str, deque[tuple[pd.Timestamp, float]]] = defaultdict(deque)

        stored: dict[str, dict[int, Any]] = {k: {} for k in output_keys}

        has_game_type = "game_type" in df.columns and self._motivation_enabled
        has_match_end = "match_end" in df.columns and self._motivation_enabled
        slots = self._playoff_line_slots

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

            hsr = np.nan
            asr = np.nan
            try:
                hsr = float(df.at[i, "home_conference_standing"])  # type: ignore[arg-type]
                asr = float(df.at[i, "away_conference_standing"])  # type: ignore[arg-type]
                stored["conf_rank_diff"][i] = hsr - asr
            except (TypeError, ValueError):
                stored["conf_rank_diff"][i] = np.nan

            hp = ap = hgp = agp = np.nan
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

            if self._motivation_enabled:
                if not np.isnan(hp) and not np.isnan(ap):
                    stored["standing_points_diff"][i] = hp - ap
                else:
                    stored["standing_points_diff"][i] = np.nan
                if not np.isnan(hgp) and not np.isnan(agp):
                    stored["gp_diff"][i] = hgp - agp
                else:
                    stored["gp_diff"][i] = np.nan

                h_out = _playoff_spots_out(hsr, slots)
                a_out = _playoff_spots_out(asr, slots)
                stored["home_playoff_spots_out"][i] = h_out
                stored["away_playoff_spots_out"][i] = a_out
                if not np.isnan(h_out) and not np.isnan(a_out):
                    stored["playoff_spots_out_diff"][i] = h_out - a_out
                else:
                    stored["playoff_spots_out_diff"][i] = np.nan

                if not np.isnan(hsr) and not np.isnan(asr):
                    stored["standing_rank_gap"][i] = abs(hsr - asr)
                else:
                    stored["standing_rank_gap"][i] = np.nan

                if has_game_type:
                    stored[self.MOTIVATION_GAME_TYPE_KEY][i] = _playoffs_phase_flag(
                        df.at[i, "game_type"]
                    )
                if has_match_end:
                    stored[self.MOTIVATION_MATCH_END_KEY][i] = _extended_game_flag(
                        df.at[i, "match_end"]
                    )

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

        for fname in output_keys:
            df[fname] = df.index.map(lambda ix, fn=fname: stored[fn].get(ix))  # type: ignore[misc]

        df.drop(columns=["_std_dt"], inplace=True)
        return df
