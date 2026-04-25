"""Слияние линий The Odds API (мультибукмекер) в таблицу матчей NHL ``source.csv``.

Поля согласуются с ``conf/bookmaker/the_odds_api.yaml`` (``bookmaker_profiles``, legacy
``output_columns``) и :data:`sports_forecast.data.providers.odds.store.ODDS_STORE_COLUMNS_V2`.
Политика: эти поля **не** используются в :mod:`sports_forecast.features`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final

import pandas as pd
from omegaconf import DictConfig, OmegaConf

from sports_forecast.config.loaders import PROJECT_ROOT
from sports_forecast.data.providers.odds.team_name_registry import (
    TeamNameRegistry,
    normalize_team_key,
)
from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)

# Ключи соответствия store/enrichment → source (остальные поля `odds_df` — значения для left-merge).
_ODDS_JOIN_KEYS: Final[tuple[str, str, str]] = (
    "game_date",
    "home_team_norm",
    "away_team_norm",
)

# Семантика в именах колонок R21: ``winner``/``total`` = regulation; ``*withOT`` = полный матч.
_WINNER_WITH_OT: Final[str] = "winner_withOT"
_TOTAL_WITH_OT: Final[str] = "total_withOT"


@dataclass(frozen=True, slots=True)
class BookmakerExtractionProfile:
    """Профиль букмекера для извлечения: ключ API, префикс колонок, семантика рынков.

    ``winner`` / ``total`` — регулярка; ``winner_withOT`` / ``total_withOT`` — полный матч.
    """

    api_key: str
    column_prefix: str
    winner_semantics: str
    total_semantics: str
    has_draw: bool

    @classmethod
    def from_mapping(cls, section_name: str, node: Mapping[str, Any]) -> BookmakerExtractionProfile:
        """Собрать из узла ``bookmaker_profiles.<name>`` YAML или тестового dict."""
        key = str(node.get("key", section_name) or section_name)
        prefix = str(node.get("column_prefix", key) or key)
        return cls(
            api_key=key,
            column_prefix=prefix,
            winner_semantics=str(node.get("winner_semantics", _WINNER_WITH_OT)),
            total_semantics=str(node.get("total_semantics", _TOTAL_WITH_OT)),
            has_draw=bool(node.get("has_draw", True)),
        )


def _v2_row_keys_for_profile(p: BookmakerExtractionProfile) -> list[str]:
    """Список V2-имён колонок (OddsStore) для одного профиля."""
    pre = p.column_prefix
    w, t = p.winner_semantics, p.total_semantics
    keys: list[str] = []
    for side in ("home", "away", "draw"):
        for end in ("open", "close"):
            keys.append(f"{pre}_{w}_{side}_{end}")
    for end in ("open", "close"):
        keys.append(f"{pre}_{t}_line_{end}")
        keys.append(f"{pre}_{t}_over_{end}")
        keys.append(f"{pre}_{t}_under_{end}")
    return keys


def _empty_row_v2(p: BookmakerExtractionProfile) -> dict[str, None]:
    return dict.fromkeys(_v2_row_keys_for_profile(p), None)


def _coerce_profile_mapping(raw: Any) -> list[BookmakerExtractionProfile]:
    """Превратить ``bookmaker_profiles`` (dict / DictConfig) в упорядоченный список."""
    if raw is None:
        return []
    d: Any = raw
    if not isinstance(d, dict):
        try:
            d = OmegaConf.to_container(d, resolve=True)  # type: ignore[assignment]
        except (TypeError, ValueError):
            return []
    if not isinstance(d, dict) or not d:
        return []
    out: list[BookmakerExtractionProfile] = []
    for section_name, node in d.items():
        if not isinstance(node, Mapping):
            continue
        m = node if isinstance(node, dict) else dict(node)
        out.append(BookmakerExtractionProfile.from_mapping(str(section_name), m))
    return out


def _resolve_extraction_profiles(
    book_cfg: Any,
    bookmaker_profiles_explicit: Any,
) -> list[BookmakerExtractionProfile]:
    """Сначала ``bookmaker_profiles`` (явно), иначе из ``book_cfg``."""
    p = _coerce_profile_mapping(bookmaker_profiles_explicit)
    if p:
        return p
    if book_cfg is None:
        return []
    sub = OmegaConf.select(book_cfg, "bookmaker_profiles")
    return _coerce_profile_mapping(sub)


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


def _team_key(name: str, team_registry: TeamNameRegistry | None) -> str:
    """Ключ сопоставления: реестр (если есть) иначе :func:`normalize_team_key`."""
    if team_registry is not None and not team_registry.is_empty:
        return team_registry.resolve(name)
    return normalize_team_key(name)


def _h2h_prices(
    bm: dict[str, Any],
    home_name: str,
    away_name: str,
    *,
    team_registry: TeamNameRegistry | None = None,
) -> tuple[float | None, float | None, float | None]:
    """Извлечь decimal odds home / away / draw из рынка h2h."""
    home_n = _team_key(home_name, team_registry)
    away_n = _team_key(away_name, team_registry)
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
            nn = _team_key(name, team_registry)
            if nn == home_n:
                home_p = p
            elif nn == away_n:
                away_p = p
            elif name.strip().lower() in ("draw", "tie"):
                draw_p = p
        break
    return home_p, away_p, draw_p


def _totals_line_and_prices(bm: dict[str, Any]) -> tuple[float | None, float | None, float | None]:
    """База тотала (``point``) и цены over/under для первого рынка ``totals``."""
    for mkt in bm.get("markets") or []:
        if not isinstance(mkt, dict) or str(mkt.get("key")) != "totals":
            continue
        line: float | None = None
        over_p: float | None = None
        under_p: float | None = None
        mkt_point = mkt.get("point")
        if mkt_point is not None:
            with suppress(TypeError, ValueError):
                line = float(mkt_point)
        for out in mkt.get("outcomes") or []:
            if not isinstance(out, dict):
                continue
            pt = out.get("point")
            if line is None and pt is not None:
                with suppress(TypeError, ValueError):
                    line = float(pt)
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
        return (line, over_p, under_p)
    return (None, None, None)


def _totals_over_under(bm: dict[str, Any]) -> tuple[float | None, float | None]:
    """Коэффициенты over и under для первого рынка totals (совместимость R20)."""
    _line, o, u = _totals_line_and_prices(bm)
    return o, u


def _parse_commence_time_utc(ev: dict[str, Any]) -> str | None:
    """ISO-8601 старт матча (UTC) из ``commence_time``/``commenceTime``."""
    raw = ev.get("commence_time") or ev.get("commenceTime")
    if not raw or not isinstance(raw, str):
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    except ValueError:
        return None


def extract_bookmaker_row_from_event(
    ev: dict[str, Any],
    profile: BookmakerExtractionProfile,
    *,
    snapshot_role: str = "single",
    team_registry: TeamNameRegistry | None = None,
) -> dict[str, Any | None]:
    """Извлечь коэффициенты одного букмекера по V2-контракту имён (см. :data:`ODDS_STORE_COLUMNS_V2`).

    Args:
        ev: Одно событие JSON The Odds API.
        profile: Семантика и префикс колонок.
        snapshot_role: ``open`` | ``close`` | ``single`` — какие колонки ``*_open``/``*_close`` заполнять.
        team_registry: Алиасы команд → каноника.

    Returns:
        Словарь только с колонками этого букмекера; при отсутствии bookmaker в событии — все ``None``.
    """
    out: dict[str, Any | None] = dict.fromkeys(_v2_row_keys_for_profile(profile), None)
    home_name = str(ev.get("home_team") or "")
    away_name = str(ev.get("away_team") or "")
    bm = _find_bookmaker(ev, profile.api_key)
    if bm is None:
        return out

    hh, aa, dd = _h2h_prices(
        bm,
        home_name,
        away_name,
        team_registry=team_registry,
    )
    t_line, over_p, under_p = _totals_line_and_prices(bm)
    pfx = profile.column_prefix
    w_s = profile.winner_semantics
    t_s = profile.total_semantics

    def _w(side: str, part: str) -> str:
        return f"{pfx}_{w_s}_{side}_{part}"

    def _t(suffix: str, part: str) -> str:
        return f"{pfx}_{t_s}_{suffix}_{part}"

    if snapshot_role == "open":
        out[_w("home", "open")] = hh
        out[_w("away", "open")] = aa
        out[_w("draw", "open")] = dd
        out[_t("line", "open")] = t_line
        out[_t("over", "open")] = over_p
        out[_t("under", "open")] = under_p
    elif snapshot_role == "close":
        out[_w("home", "close")] = hh
        out[_w("away", "close")] = aa
        out[_w("draw", "close")] = dd
        out[_t("line", "close")] = t_line
        out[_t("over", "close")] = over_p
        out[_t("under", "close")] = under_p
    else:
        for part in ("open", "close"):
            out[_w("home", part)] = hh
            out[_w("away", part)] = aa
            out[_w("draw", part)] = dd
            out[_t("line", part)] = t_line
            out[_t("over", part)] = over_p
            out[_t("under", part)] = under_p

    return out


def _extract_row_legacy_pinnacle(
    ev: dict[str, Any],
    bookmaker_key: str,
    output_columns: dict[str, Any],
    *,
    snapshot_role: str = "single",
    team_registry: TeamNameRegistry | None = None,
) -> dict[str, Any | None]:
    """R19/R20: одна сетка имён из ``output_columns`` (YAML), over-only в total-колонках."""
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

    hh, aa, dd = _h2h_prices(
        bm,
        home_name,
        away_name,
        team_registry=team_registry,
    )
    _line, over_p, under_p = _totals_line_and_prices(bm)
    # Legacy: в pinnacle_total_{open,close} хранилась цена over (R20)
    total_line = over_p if over_p is not None else under_p

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


def extract_pinnacle_row_from_event(
    ev: dict[str, Any],
    bookmaker_key: str,
    output_columns: dict[str, Any],
    *,
    snapshot_role: str = "single",
    team_registry: TeamNameRegistry | None = None,
) -> dict[str, Any | None]:
    """Извлечь коэффициенты для одного события в колонки legacy-конфига (R19/R20 ``output_columns``)."""
    return _extract_row_legacy_pinnacle(
        ev,
        bookmaker_key,
        output_columns,
        snapshot_role=snapshot_role,
        team_registry=team_registry,
    )


def _events_to_odds_frame_v2(
    events_open: list[dict[str, Any]],
    events_close: list[dict[str, Any]] | None,
    profiles: Sequence[BookmakerExtractionProfile],
    team_registry: TeamNameRegistry | None = None,
) -> pd.DataFrame:
    close_idx: dict[str, dict[str, Any]] = {}
    for ev in events_close or []:
        if not isinstance(ev, dict):
            continue
        hk = _team_key(str(ev.get("home_team", "")), team_registry)
        ak = _team_key(str(ev.get("away_team", "")), team_registry)
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
        hk = _team_key(home, team_registry)
        ak = _team_key(away, team_registry)
        c_utc = _parse_commence_time_utc(ev)
        row: dict[str, Any] = {
            "game_date": game_date,
            "home_team_norm": hk,
            "away_team_norm": ak,
            "commence_time_utc": c_utc,
        }
        for p in profiles:
            if events_close:
                ovals = extract_bookmaker_row_from_event(
                    ev,
                    p,
                    snapshot_role="open",
                    team_registry=team_registry,
                )
                row.update(ovals)
                ev_c = close_idx.get(f"{hk}|{ak}")
                if ev_c is not None:
                    cvals = extract_bookmaker_row_from_event(
                        ev_c,
                        p,
                        snapshot_role="close",
                        team_registry=team_registry,
                    )
                    for k, v in cvals.items():
                        if v is not None:
                            row[k] = v
            else:
                single = extract_bookmaker_row_from_event(
                    ev,
                    p,
                    snapshot_role="single",
                    team_registry=team_registry,
                )
                row.update(single)
        rows.append(row)

    return pd.DataFrame(rows)


def _events_to_odds_frame_legacy(
    events_open: list[dict[str, Any]],
    events_close: list[dict[str, Any]] | None,
    bookmaker_key: str,
    output_columns: dict[str, Any],
    team_registry: TeamNameRegistry | None = None,
) -> pd.DataFrame:
    close_idx: dict[str, dict[str, Any]] = {}
    for ev in events_close or []:
        if not isinstance(ev, dict):
            continue
        hk = _team_key(str(ev.get("home_team", "")), team_registry)
        ak = _team_key(str(ev.get("away_team", "")), team_registry)
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
        hk = _team_key(home, team_registry)
        ak = _team_key(away, team_registry)
        c_utc = _parse_commence_time_utc(ev)
        row: dict[str, Any] = {
            "game_date": game_date,
            "home_team_norm": hk,
            "away_team_norm": ak,
            "commence_time_utc": c_utc,
        }
        if events_close:
            open_vals = _extract_row_legacy_pinnacle(
                ev,
                bookmaker_key,
                output_columns,
                snapshot_role="open",
                team_registry=team_registry,
            )
            row.update(open_vals)
            ev_c = close_idx.get(f"{hk}|{ak}")
            if ev_c is not None:
                close_vals = _extract_row_legacy_pinnacle(
                    ev_c,
                    bookmaker_key,
                    output_columns,
                    snapshot_role="close",
                    team_registry=team_registry,
                )
                for k, v in close_vals.items():
                    if v is not None:
                        row[k] = v
        else:
            single_vals = _extract_row_legacy_pinnacle(
                ev,
                bookmaker_key,
                output_columns,
                snapshot_role="single",
                team_registry=team_registry,
            )
            row.update(single_vals)
        rows.append(row)

    return pd.DataFrame(rows)


def events_to_odds_frame(
    events_open: list[dict[str, Any]],
    events_close: list[dict[str, Any]] | None,
    bookmaker_key: str,
    output_columns: dict[str, Any],
    team_registry: TeamNameRegistry | None = None,
    *,
    book_cfg: Any | None = None,
    bookmaker_profiles: Any | None = None,
) -> pd.DataFrame:
    """Построить DataFrame: ключ ``game_date`` + нормализованные команды + optional ``commence_time_utc``.

    Если в ``book_cfg`` (или в ``bookmaker_profiles``) заданы профили, извлекаются **все**
    букмекеры из **одного** снимка события, строка на event — V2-имена колонок. Иначе
    сценарий R19/R20: один букмекер, имена из ``output_columns``.

    Args:
        events_open: Снимок «open» (или единственный).
        events_close: Снимок «close``; ``None`` — single snapshot.
        bookmaker_key: Ключ в JSON (e.g. ``pinnacle``) для legacy-режима.
        output_columns: Ветка ``output_columns`` из YAML, только legacy-режим.
        team_registry: Алиасы команд.
        book_cfg: Узел конфига (``book_root``) с ``bookmaker_profiles``.
        bookmaker_profiles: Прямого словаря / DictConfig, переопределяет извлечение из ``book_cfg``.

    Returns:
        DataFrame: ``game_date``, ``home_team_norm``, ``away_team_norm``, ``commence_time_utc``,
        далее V2-поля **или** legacy ``pinnacle_*`` и т.д.
    """
    profs = _resolve_extraction_profiles(book_cfg, bookmaker_profiles)
    if profs:
        return _events_to_odds_frame_v2(
            events_open, events_close, profs, team_registry=team_registry
        )
    return _events_to_odds_frame_legacy(
        events_open,
        events_close,
        bookmaker_key,
        output_columns,
        team_registry=team_registry,
    )


def write_unmatched_odds_teams_report(
    odds_df: pd.DataFrame,
    source_match_keys: set[tuple[str, str, str]],
    report_path: Path,
) -> int:
    """Записать CSV со строками odds, не нашедшими пару в source (по дате и командам).

    Args:
        odds_df: Таблица с ``game_date``, ``home_team_norm``, ``away_team_norm``.
        source_match_keys: Множество ``(game_date, home, away)`` из source.
        report_path: Файл назначения; родительские каталоги создаются.

    Returns:
        Число записанных (уникальных) несоответствующих строк.
    """
    report_path.parent.mkdir(parents=True, exist_ok=True)
    cols = ["game_date", "home_team_norm", "away_team_norm"]
    if (
        odds_df.empty
        or "game_date" not in odds_df.columns
        or not {"home_team_norm", "away_team_norm"}.issubset(odds_df.columns)
    ):
        pd.DataFrame(columns=cols).to_csv(report_path, index=False)
        return 0
    seen: set[tuple[str, str, str]] = set()
    missing: list[tuple[str, str, str]] = []
    for _, r in odds_df.iterrows():
        gd = str(r.get("game_date", "") or "")
        h = str(r.get("home_team_norm", "") or "")
        a = str(r.get("away_team_norm", "") or "")
        t = (gd, h, a)
        if t in seen:
            continue
        seen.add(t)
        if t not in source_match_keys:
            missing.append(t)
    out = pd.DataFrame(missing, columns=cols) if missing else pd.DataFrame(columns=cols)
    out.to_csv(report_path, index=False)
    n = len(missing)
    if n:
        logger.info(
            "merge_odds: отчёт unmatched teams (%d строк) → %s",
            n,
            report_path,
        )
    return n


def default_unmatched_teams_report_path(
    tournament: str,
    project_root: Path | None = None,
) -> Path:
    """Путь ``data/source/{tournament}/odds/unmatched_teams.csv`` от корня проекта."""
    root = project_root or PROJECT_ROOT
    return (root / "data" / "source" / tournament / "odds" / "unmatched_teams.csv").resolve()


def merge_odds_into_source_dataframe(
    source_df: pd.DataFrame,
    odds_df: pd.DataFrame,
    book_cfg: DictConfig | None = None,
    team_registry: TeamNameRegistry | None = None,
    unmatched_teams_path: Path | str | None = None,
    tournament: str | None = None,
    project_root: Path | None = None,
) -> pd.DataFrame:
    """LEFT-merge коэффициентов в копию source-таблицы по дате игры и командам.

    Поддерживает :data:`sports_forecast.data.providers.odds.store.ODDS_STORE_COLUMNS_V2` и
    legacy V1-имена в ``odds_df``. Перед merge колонки source с теми же именами, что и
    несущиеся из ``odds_df`` (кроме ключей), удаляются — иначе pandas добавил бы суффикс
    ``_odds``; так не дублируются тайминги и остальные поля.

    Args:
        team_registry: Слой алиас → каноника перед fallback-нормализацией; ``None`` — как раньше.
        unmatched_teams_path: Явный путь к отчёту несоответствий odds↔source; ``None`` — не писать.
        tournament: Вместе с ``project_root`` задаёт путь отчёта по умолчанию (см. ниже).
        project_root: Корень репо для пути отчёта; по умолчанию ``PROJECT_ROOT``.

    Если заданы ``tournament`` и нет ``unmatched_teams_path``, отчёт:
    ``data/source/{tournament}/odds/unmatched_teams.csv``.
    """
    if odds_df.empty:
        logger.warning("merge_odds: пустой odds_df — исходная таблица без изменений")
        return source_df.copy()

    df = source_df.copy()
    dt = pd.to_datetime(df["datetime"], errors="coerce", utc=True)
    df["_game_date"] = dt.dt.date.astype(str)
    df["_hn"] = df["home_team"].map(lambda x: _team_key(str(x), team_registry))
    df["_an"] = df["away_team"].map(lambda x: _team_key(str(x), team_registry))

    o = odds_df.copy()
    if "game_date" not in o.columns:
        logger.error("odds_df без колонки game_date")
        return source_df.copy()
    for k in ("home_team_norm", "away_team_norm"):
        if k not in o.columns:
            logger.error("odds_df без колонки %s", k)
            return source_df.copy()

    # Все поля кроме ключей слияния: при пересечении с `source` удаляем слева, чтобы merge
    # не создавал «*_odds» и не дублировал V1/V2-поля (в т.ч. timing, fetched_at).
    odds_value_cols = [c for c in o.columns if c not in _ODDS_JOIN_KEYS]
    drop_from_left = [c for c in odds_value_cols if c in df.columns]
    if drop_from_left:
        df = df.drop(columns=drop_from_left, errors="ignore")

    source_match_keys = set(
        zip(
            df["_game_date"].astype(str),
            df["_hn"],
            df["_an"],
            strict=True,
        )
    )
    report_path: Path | None = None
    if unmatched_teams_path is not None:
        report_path = Path(unmatched_teams_path)
    elif tournament is not None:
        report_path = default_unmatched_teams_report_path(
            tournament,
            project_root=project_root,
        )

    merged = df.merge(
        o,
        how="left",
        left_on=["_game_date", "_hn", "_an"],
        right_on=["game_date", "home_team_norm", "away_team_norm"],
        suffixes=("", "_odds"),
    )
    if report_path is not None:
        write_unmatched_odds_teams_report(o, source_match_keys, report_path)
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
    team_registry: TeamNameRegistry | None = None,
    unmatched_teams_path: Path | str | None = None,
    tournament: str | None = None,
    project_root: Path | None = None,
) -> pd.DataFrame:
    """Прочитать ``source.csv``, merge, записать."""
    src = pd.read_csv(source_csv_path, low_memory=False)
    out = merge_odds_into_source_dataframe(
        src,
        odds_df,
        book_cfg=book_cfg,
        team_registry=team_registry,
        unmatched_teams_path=unmatched_teams_path,
        tournament=tournament,
        project_root=project_root,
    )
    target = out_csv_path or source_csv_path
    out.to_csv(target, index=False)
    logger.info("merge_odds: записано %d строк → %s", len(out), target)
    return out
