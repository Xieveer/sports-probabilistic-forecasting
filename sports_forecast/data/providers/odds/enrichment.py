"""Слияние линий The Odds API (Pinnacle) в таблицу матчей NHL ``source.csv``.

Колонки согласуются с ``conf/bookmaker/the_odds_api.yaml`` → ``output_columns``.
Политика: эти поля **не** используются в :mod:`sports_forecast.features`.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from typing import Any

import pandas as pd
from omegaconf import DictConfig, OmegaConf

from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)


def _norm_team(s: str) -> str:
    """Нормализация имени команды для нечёткого сопоставления."""
    t = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^A-Z0-9]+", "", t.upper().strip())


def unwrap_odds_payload(payload: Any) -> list[dict[str, Any]]:
    """Достать список событий из ответа ``/odds`` или ``/historical/.../odds``."""
    if isinstance(payload, dict) and "data" in payload:
        data = payload["data"]
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    return []


def _find_bookmaker(ev: dict[str, Any], key: str) -> dict[str, Any] | None:
    for bm in ev.get("bookmakers") or []:
        if isinstance(bm, dict) and str(bm.get("key", "")).lower() == key.lower():
            return bm
    return None


def _h2h_prices(
    bm: dict[str, Any],
    home_name: str,
    away_name: str,
) -> tuple[float | None, float | None, float | None]:
    """Извлечь decimal odds home / away / draw из рынка h2h."""
    home_n = _norm_team(home_name)
    away_n = _norm_team(away_name)
    home_p: float | None = None
    away_p: float | None = None
    draw_p: float | None = None
    for mkt in bm.get("markets") or []:
        if not isinstance(mkt, dict) or str(mkt.get("key")) != "h2h":
            continue
        for out in mkt.get("outcomes") or []:
            if not isinstance(out, dict):
                continue
            name = str(out.get("name", ""))
            price = out.get("price")
            try:
                p = float(price) if price is not None else None
            except (TypeError, ValueError):
                p = None
            nn = _norm_team(name)
            if nn == home_n:
                home_p = p
            elif nn == away_n:
                away_p = p
            elif name.strip().lower() in ("draw", "tie"):
                draw_p = p
        break
    return home_p, away_p, draw_p


def _totals_over_under(bm: dict[str, Any]) -> tuple[float | None, float | None]:
    """Коэффициенты over и under для первого рынка totals."""
    for mkt in bm.get("markets") or []:
        if not isinstance(mkt, dict) or str(mkt.get("key")) != "totals":
            continue
        over_p: float | None = None
        under_p: float | None = None
        for out in mkt.get("outcomes") or []:
            if not isinstance(out, dict):
                continue
            nm = str(out.get("name", "")).lower()
            price = out.get("price")
            try:
                p = float(price) if price is not None else None
            except (TypeError, ValueError):
                p = None
            if "over" in nm:
                over_p = p
            elif "under" in nm:
                under_p = p
        return over_p, under_p
    return None, None


def extract_pinnacle_row_from_event(
    ev: dict[str, Any],
    bookmaker_key: str,
    output_columns: dict[str, Any],
    *,
    snapshot_role: str = "single",
) -> dict[str, Any | None]:
    """Извлечь коэффициенты Pinnacle для одного события.

    Args:
        snapshot_role: ``open`` — только открытие; ``close`` — только закрытие;
            ``single`` — один снимок, заполняем и open и close одинаково.
    """
    ml = (output_columns or {}).get("moneyline") or {}
    tot = (output_columns or {}).get("total") or {}
    out: dict[str, Any | None] = {}
    for k in list(ml.values()) + list(tot.values()):
        if k:
            out[str(k)] = None

    home_name = str(ev.get("home_team") or "")
    away_name = str(ev.get("away_team") or "")
    bm = _find_bookmaker(ev, bookmaker_key)
    if bm is None:
        return out

    hh, aa, dd = _h2h_prices(bm, home_name, away_name)
    ov, un = _totals_over_under(bm)
    total_line = ov if ov is not None else un

    def _set_ml(side: str, val: float | None) -> None:
        col = ml.get(side)
        if col:
            out[str(col)] = val

    def _set_tot(side: str, val: float | None) -> None:
        col = tot.get(side)
        if col:
            out[str(col)] = val

    if snapshot_role == "open":
        _set_ml("home_open", hh)
        _set_ml("away_open", aa)
        _set_ml("draw_open", dd)
        _set_tot("open", total_line)
    elif snapshot_role == "close":
        _set_ml("home_close", hh)
        _set_ml("away_close", aa)
        _set_ml("draw_close", dd)
        _set_tot("close", total_line)
    else:
        for side_h, v in (
            ("home_open", hh),
            ("home_close", hh),
            ("away_open", aa),
            ("away_close", aa),
        ):
            _set_ml(side_h, v)
        _set_ml("draw_open", dd)
        _set_ml("draw_close", dd)
        _set_tot("open", total_line)
        _set_tot("close", total_line)

    return out


def events_to_odds_frame(
    events_open: list[dict[str, Any]],
    events_close: list[dict[str, Any]] | None,
    bookmaker_key: str,
    output_columns: dict[str, Any],
) -> pd.DataFrame:
    """Построить DataFrame для merge: ключ ``game_date`` + нормализованные команды.

    Args:
        events_open: Снимок «open» (или единственный снимок).
        events_close: Снимок «close»; может быть ``None``.
        bookmaker_key: Например ``pinnacle``.
        output_columns: Ветка YAML ``output_columns``.

    Returns:
        DataFrame с колонками ``game_date``, ``home_team_norm``, ``away_team_norm``, ``pinnacle_*``.
    """
    close_idx: dict[str, dict[str, Any]] = {}
    for ev in events_close or []:
        if not isinstance(ev, dict):
            continue
        hk = _norm_team(str(ev.get("home_team", "")))
        ak = _norm_team(str(ev.get("away_team", "")))
        close_idx[f"{hk}|{ak}"] = ev

    rows: list[dict[str, Any]] = []
    for ev in events_open:
        if not isinstance(ev, dict):
            continue
        home = str(ev.get("home_team") or "")
        away = str(ev.get("away_team") or "")
        commence = ev.get("commence_time") or ev.get("commenceTime")
        game_date = ""
        if isinstance(commence, str):
            try:
                game_date = (
                    datetime.fromisoformat(commence.replace("Z", "+00:00")).date().isoformat()
                )
            except ValueError:
                game_date = ""
        hk = _norm_team(home)
        ak = _norm_team(away)
        row: dict[str, Any] = {
            "game_date": game_date,
            "home_team_norm": hk,
            "away_team_norm": ak,
        }
        if events_close:
            open_vals = extract_pinnacle_row_from_event(
                ev,
                bookmaker_key,
                output_columns,
                snapshot_role="open",
            )
            row.update(open_vals)
            ev_c = close_idx.get(f"{hk}|{ak}")
            if ev_c is not None:
                close_vals = extract_pinnacle_row_from_event(
                    ev_c,
                    bookmaker_key,
                    output_columns,
                    snapshot_role="close",
                )
                for k, v in close_vals.items():
                    if v is not None:
                        row[k] = v
        else:
            single_vals = extract_pinnacle_row_from_event(
                ev,
                bookmaker_key,
                output_columns,
                snapshot_role="single",
            )
            row.update(single_vals)
        rows.append(row)

    return pd.DataFrame(rows)


def merge_odds_into_source_dataframe(
    source_df: pd.DataFrame,
    odds_df: pd.DataFrame,
    book_cfg: DictConfig | None = None,
) -> pd.DataFrame:
    """LEFT-merge коэффициентов в копию source-таблицы по дате игры и командам."""
    if odds_df.empty:
        logger.warning("merge_odds: пустой odds_df — исходная таблица без изменений")
        return source_df.copy()

    df = source_df.copy()
    dt = pd.to_datetime(df["datetime"], errors="coerce", utc=True)
    df["_game_date"] = dt.dt.date.astype(str)
    df["_hn"] = df["home_team"].map(lambda x: _norm_team(str(x)))
    df["_an"] = df["away_team"].map(lambda x: _norm_team(str(x)))

    o = odds_df.copy()
    if "game_date" not in o.columns:
        logger.error("odds_df без колонки game_date")
        return source_df.copy()

    merged = df.merge(
        o,
        how="left",
        left_on=["_game_date", "_hn", "_an"],
        right_on=["game_date", "home_team_norm", "away_team_norm"],
        suffixes=("", "_odds"),
    )
    drop_cols = [
        c
        for c in (
            "_game_date",
            "_hn",
            "_an",
            "home_team_norm",
            "away_team_norm",
            "game_date",
        )
        if c in merged.columns
    ]
    merged = merged.drop(columns=drop_cols, errors="ignore")

    if book_cfg is not None:
        logger.info(
            "merge_odds: %s; строк: %d",
            OmegaConf.select(book_cfg, "name") or "the_odds_api",
            len(merged),
        )
    return merged


def merge_odds_into_source_csv(
    source_csv_path: str,
    odds_df: pd.DataFrame,
    out_csv_path: str | None = None,
    book_cfg: DictConfig | None = None,
) -> pd.DataFrame:
    """Прочитать ``source.csv``, merge, записать."""
    src = pd.read_csv(source_csv_path, low_memory=False)
    out = merge_odds_into_source_dataframe(src, odds_df, book_cfg=book_cfg)
    target = out_csv_path or source_csv_path
    out.to_csv(target, index=False)
    logger.info("merge_odds: записано %d строк → %s", len(out), target)
    return out
