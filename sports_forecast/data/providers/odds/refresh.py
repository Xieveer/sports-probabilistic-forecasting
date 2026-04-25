"""Инкрементальное обновление линий Pinnacle: окно дат, checkpoint, OddsStore, merge в ``source.csv``.

План:
    * максимальная дата в :mod:`~sports_forecast.data.providers.odds.store` →
      ``from = max - buffer`` … ``to = сегодня``;
    * пустой store → backfill «текущего» (последнего в списке) сезона из ``the_odds_api.yaml``;
    * ограничение длины одного прогона — ``max_days_per_refresh``;
    * ``refresh_state.json`` — resume; идемпотентность —
      :func:`~sports_forecast.data.providers.odds.store.upsert_odds_store_file`.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Final

import pandas as pd
from omegaconf import DictConfig, OmegaConf

from sports_forecast.config.loaders import PROJECT_ROOT, load_bookmaker_config, load_source_config
from sports_forecast.data.providers.odds.backfill import (
    BackfillRunResult,
    default_odds_store_path,
    last_n_season_windows,
    run_backfill,
)
from sports_forecast.data.providers.odds.enrichment import merge_odds_into_source_csv
from sports_forecast.data.providers.odds.store import load_odds_store, max_game_date_in_store
from sports_forecast.data.providers.odds.team_name_registry import (
    TeamNameRegistry,
    load_nhl_team_name_registry,
)
from sports_forecast.utils.log_config import get_logger
from sports_forecast.validation.schemas import validate_pinnacle_odds_float_columns


logger = get_logger(__name__)

_REFRESH_STATE_NAME: Final[str] = "refresh_state.json"
_DEFAULT_BUFFER_DAYS: Final[int] = 3
_DEFAULT_MAX_DAYS: Final[int] = 30
_DEFAULT_AUTO_MERGE: Final[bool] = True
_DEFAULT_MIN_COVERAGE_PCT: Final[float] = 70.0
# Относительно ``data/source/{tournament}/``
_DEFAULT_STORE_REL: Final[str] = "odds/pinnacle_odds.parquet"
_DEFAULT_STATE_REL: Final[str] = "odds/refresh_state.json"
_DEFAULT_UNMATCHED_REL: Final[str] = "odds/unmatched_teams.csv"

# Покрытие в source после merge: Pinnacle/1xBet (R21 V2) и legacy V1.
_PINNACLE_V1_COVERAGE_COL: Final[str] = "pinnacle_home_close"
_PINNACLE_V2_COVERAGE_COL: Final[str] = "pinnacle_winner_withOT_home_close"
_ONEXBET_V2_COVERAGE_COL: Final[str] = "onexbet_winner_home_close"


@dataclass
class RefreshState:
    """Состояние инкрементального odds-refresh (``refresh_state.json``)."""

    last_successful_date: str | None
    """ISO ``YYYY-MM-DD`` последнего **полностью** обработанного дня в сегменте/прогоне."""
    in_progress_from: str | None
    """Начало текущего сегмента или **следующий** день для продолжения (после ``max_days`` / partial)."""
    updated_at: str
    """Время UTC ISO 8601 последней записи."""


@dataclass(frozen=True)
class RefreshDatePlan:
    """План инкрементального диапазона (до сегментации по ``max_days``)."""

    need_from: date
    need_to: date
    used_empty_store_season: bool
    """True, если store пуст — окно последнего сезона из YAML."""


@dataclass(frozen=True)
class RefreshSegment:
    """Один сегмент ``[date_from, date_to]`` (с учётом cap ``max_days_per_refresh``)."""

    date_from: date
    date_to: date
    has_more: bool
    """``True`` если после этого сегмента остались дни до ``need_to`` (следующий запуск)."""


@dataclass(frozen=True)
class OddsRefreshResult:
    """Результат :func:`run_odds_refresh`."""

    segment: RefreshSegment
    new_odds_rows: int
    store_rows: int
    merged_source: bool
    quota_hit: bool
    state: RefreshState
    used_empty_store_season: bool
    requests_remaining: int | None
    requests_used: int | None


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def resolve_path_under_tournament_source(
    project_root: Path,
    tournament: str,
    configured: Any,
    default_relative: str,
) -> Path:
    """Путь к файлу под ``data/source/{tournament}/``: абсолютный как есть, иначе относительный.

    ``None``/пустая строка/``null``/``~`` — ``default_relative`` (например ``odds/pinnacle_odds.parquet``).
    """
    base = (project_root / "data" / "source" / tournament).resolve()
    if configured is None:
        return (base / default_relative).resolve()
    s = str(configured).strip()
    if not s or s.lower() in ("null", "none", "~"):
        return (base / default_relative).resolve()
    p = Path(s)
    if p.is_absolute():
        return p.resolve()
    return (base / p).resolve()


def _normalize_backfill_out(
    out: pd.DataFrame | BackfillRunResult,
) -> tuple[pd.DataFrame, bool, int | None, int | None]:
    """:func:`run_backfill` / мок, совместимый с ``DataFrame``."""
    if isinstance(out, BackfillRunResult):
        return (
            out.frame,
            out.quota_hit,
            out.requests_remaining,
            out.requests_used,
        )
    return out, False, None, None


def _log_source_odds_metrics(
    source_csv: Path,
    min_odds_coverage_pct: float,
    store_rows: int,
) -> None:
    """Лог: primary coverage, per-bookmaker V2, предупреждение ниже порога.

    Primary-колонка: ``pinnacle_home_close`` (V1), иначе ``pinnacle_winner_withOT_home_close``
    (V2). *Match rate* = доля строк source с непустым primary после merge. Дополнительно
    логируются ``pinnacle_coverage_pct`` / ``onexbet_coverage_pct``, если соответствующие
    колонки присутствуют.
    """
    if not source_csv.is_file():
        return
    try:
        src = pd.read_csv(source_csv, low_memory=False)
    except OSError as e:
        logger.warning("odds metrics: не прочитан source.csv — %s", e)
        return
    n = len(src)
    if n == 0:
        return
    if _PINNACLE_V1_COVERAGE_COL in src.columns:
        col = _PINNACLE_V1_COVERAGE_COL
    elif _PINNACLE_V2_COVERAGE_COL in src.columns:
        col = _PINNACLE_V2_COVERAGE_COL
    elif _ONEXBET_V2_COVERAGE_COL in src.columns:
        col = _ONEXBET_V2_COVERAGE_COL
    else:
        logger.info(
            "odds metrics: нет колонок %s / %s / %s — primary coverage не посчитан",
            _PINNACLE_V1_COVERAGE_COL,
            _PINNACLE_V2_COVERAGE_COL,
            _ONEXBET_V2_COVERAGE_COL,
        )
        return
    with_close = int(src[col].notna().sum())
    coverage = 100.0 * float(with_close) / float(n)
    match_rate_pct = coverage
    logger.info(
        "odds metrics: source_rows=%d %s_nonnull=%d match_rate_vs_source_pct=%.2f "
        "odds_coverage_pct=%.2f (store_rows=%d) primary_col=%s",
        n,
        col,
        with_close,
        match_rate_pct,
        coverage,
        store_rows,
        col,
    )
    if _PINNACLE_V2_COVERAGE_COL in src.columns:
        p_cov = 100.0 * float(src[_PINNACLE_V2_COVERAGE_COL].notna().sum()) / float(n)
        logger.info(
            "odds metrics: pinnacle_coverage_pct=%.2f (%s)",
            p_cov,
            _PINNACLE_V2_COVERAGE_COL,
        )
    elif _PINNACLE_V1_COVERAGE_COL in src.columns:
        p_cov = 100.0 * float(src[_PINNACLE_V1_COVERAGE_COL].notna().sum()) / float(n)
        logger.info(
            "odds metrics: pinnacle_coverage_pct=%.2f (legacy %s)",
            p_cov,
            _PINNACLE_V1_COVERAGE_COL,
        )
    if _ONEXBET_V2_COVERAGE_COL in src.columns:
        ox = 100.0 * float(src[_ONEXBET_V2_COVERAGE_COL].notna().sum()) / float(n)
        logger.info(
            "odds metrics: onexbet_coverage_pct=%.2f (%s)",
            ox,
            _ONEXBET_V2_COVERAGE_COL,
        )
    if coverage < min_odds_coverage_pct:
        logger.warning(
            "odds coverage %.2f%% < min_odds_coverage_pct=%.2f — проверьте merge/registry/API",
            coverage,
            min_odds_coverage_pct,
        )


def _log_unmatched_report_metrics(report_path: Path) -> int:
    """Число строк-исключений (без заголовка) в ``unmatched_teams.csv``."""
    if not report_path.is_file():
        return 0
    try:
        text = report_path.read_text(encoding="utf-8")
        n_lines = len(text.splitlines()) if text else 0
    except OSError as e:
        logger.warning("odds metrics: не прочитан unmatched report %s — %s", report_path, e)
        return 0
    n = max(0, n_lines - 1)
    if n:
        logger.info("odds metrics: unmatched_report_rows=%d → %s", n, report_path)
    return n


def default_refresh_state_path(
    tournament: str,
    project_root: Path | None = None,
) -> Path:
    """``data/source/{tournament}/odds/refresh_state.json`` относительно корня проекта."""
    root = project_root or PROJECT_ROOT
    return (root / "data" / "source" / tournament / "odds" / _REFRESH_STATE_NAME).resolve()


def default_source_csv_path(tournament: str, project_root: Path | None = None) -> Path:
    """``data/source/{tournament}/source.csv``."""
    root = project_root or PROJECT_ROOT
    return (root / "data" / "source" / tournament / "source.csv").resolve()


def load_refresh_state(path: Path) -> RefreshState | None:
    """Прочитать JSON; битый/пустой файл — ``None``."""
    if not path.exists():
        return None
    try:
        raw = path.read_text(encoding="utf-8")
        d = json.loads(raw)
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("refresh_state: не читается %s — %s", path, e)
        return None
    if not isinstance(d, dict):
        return None
    return RefreshState(
        last_successful_date=(
            str(d["last_successful_date"]) if d.get("last_successful_date") else None
        ),
        in_progress_from=(str(d["in_progress_from"]) if d.get("in_progress_from") else None),
        updated_at=str(d.get("updated_at") or _now_utc_iso()),
    )


def save_refresh_state(path: Path, state: RefreshState) -> None:
    """Атомарная запись JSON (временный файл + rename) в ``path``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    full: dict[str, str | None] = {
        "last_successful_date": state.last_successful_date,
        "in_progress_from": state.in_progress_from,
        "updated_at": state.updated_at,
    }
    text = json.dumps(full, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    tmp = path.parent / f".{path.name}.tmp.{os.getpid()}.{uuid.uuid4().hex}"
    try:
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                logger.warning("Не удалось удалить временный refresh_state: %s", tmp)


def build_incremental_need_range(
    store_df: pd.DataFrame,
    buffer_days: int,
    today: date,
    book_root: Any,
    tournament: str,
    state: RefreshState | None,
) -> RefreshDatePlan:
    """Построить диапазон ``[need_from, need_to]`` до сегментации.

    * Пустой store → границы **последнего** сезона из ``bookmaker.seasons.{tournament}``,
      ``need_to = min(season_to, today)``.
    * Иначе ``need_from = max(game_date) - buffer`` (с ``min`` с
      ``last_successful - buffer`` при checkpoint), ``need_to = today``.
    """
    if store_df is None or store_df.empty or "game_date" not in store_df.columns:
        windows = last_n_season_windows(book_root, tournament, 1)
        _name, s0, s1 = windows[0]
        if today < s0:
            return RefreshDatePlan(need_from=today, need_to=today, used_empty_store_season=True)
        need_to = min(s1, today)
        return RefreshDatePlan(need_from=s0, need_to=need_to, used_empty_store_season=True)

    mx = max_game_date_in_store(store_df)
    if mx is None:
        return build_incremental_need_range(
            pd.DataFrame(), buffer_days, today, book_root, tournament, state
        )

    need_from = mx - timedelta(days=buffer_days)
    if state and state.last_successful_date:
        try:
            ls = date.fromisoformat(state.last_successful_date)
            overlap = ls - timedelta(days=buffer_days)
            need_from = min(need_from, overlap)
        except ValueError:
            pass
    return RefreshDatePlan(need_from=need_from, need_to=today, used_empty_store_season=False)


def _parse_iso_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def build_refresh_segment(
    plan: RefreshDatePlan,
    max_days_per_refresh: int,
    state: RefreshState | None,
) -> RefreshSegment:
    """Сегмент [date_from, date_to] c лимитом длины; ``in_progress_from`` сдвигает начало (resume)."""
    if plan.need_to < plan.need_from:
        return RefreshSegment(date_from=plan.need_to, date_to=plan.need_to, has_more=False)

    need_from = plan.need_from
    need_to = plan.need_to
    if state and state.in_progress_from:
        ip = _parse_iso_date(state.in_progress_from)
        if ip is not None and ip <= need_to:
            need_from = max(need_from, ip)
    if need_from > need_to:
        return RefreshSegment(date_from=need_to, date_to=need_to, has_more=False)

    days_total = (need_to - need_from).days + 1
    if max_days_per_refresh < 1 or days_total <= max_days_per_refresh:
        return RefreshSegment(date_from=need_from, date_to=need_to, has_more=False)

    seg_to = need_from + timedelta(days=max_days_per_refresh - 1)
    if seg_to > need_to:
        seg_to = need_to
    return RefreshSegment(
        date_from=need_from,
        date_to=seg_to,
        has_more=seg_to < need_to,
    )


def _resolve_team_registry(tournament: str, sport_key: str) -> TeamNameRegistry | None:
    if tournament == "nhl" or sport_key == "icehockey_nhl":
        return load_nhl_team_name_registry()
    return None


def _odds_runtime_from_source(
    source_name: str | None,
    tournament: str,
    project_root: Path,
) -> tuple[int, int, bool, Path, Path, Path, float]:
    """Параметры odds из ``source.yaml``: буфер, cap, merge, пути, порог coverage."""
    d_store = default_odds_store_path(tournament, project_root)
    d_state = default_refresh_state_path(tournament, project_root)
    d_unm = resolve_path_under_tournament_source(
        project_root, tournament, None, _DEFAULT_UNMATCHED_REL
    )
    if not source_name:
        return (
            _DEFAULT_BUFFER_DAYS,
            _DEFAULT_MAX_DAYS,
            _DEFAULT_AUTO_MERGE,
            d_store,
            d_state,
            d_unm,
            _DEFAULT_MIN_COVERAGE_PCT,
        )
    try:
        sc: DictConfig = load_source_config(source_name)
    except (FileNotFoundError, OSError) as e:
        logger.debug("refresh: нет source %s — дефолты — %s", source_name, e)
        return (
            _DEFAULT_BUFFER_DAYS,
            _DEFAULT_MAX_DAYS,
            _DEFAULT_AUTO_MERGE,
            d_store,
            d_state,
            d_unm,
            _DEFAULT_MIN_COVERAGE_PCT,
        )
    o = sc.get("odds") or {}
    b = o.get("incremental_buffer_days", _DEFAULT_BUFFER_DAYS)
    m = o.get("max_days_per_refresh", _DEFAULT_MAX_DAYS)
    am = o.get("auto_merge", _DEFAULT_AUTO_MERGE)
    try:
        bi = int(b)
    except (TypeError, ValueError):
        bi = _DEFAULT_BUFFER_DAYS
    try:
        mi = int(m)
    except (TypeError, ValueError):
        mi = _DEFAULT_MAX_DAYS
    am_bool = am if isinstance(am, bool) else str(am).lower() in ("1", "true", "yes")
    p_store = resolve_path_under_tournament_source(
        project_root, tournament, o.get("store_path"), _DEFAULT_STORE_REL
    )
    p_state = resolve_path_under_tournament_source(
        project_root, tournament, o.get("state_path"), _DEFAULT_STATE_REL
    )
    p_unm = resolve_path_under_tournament_source(
        project_root, tournament, o.get("unmatched_report_path"), _DEFAULT_UNMATCHED_REL
    )
    mc = o.get("min_odds_coverage_pct", _DEFAULT_MIN_COVERAGE_PCT)
    try:
        min_cov = float(mc)
    except (TypeError, ValueError):
        min_cov = _DEFAULT_MIN_COVERAGE_PCT
    return max(0, bi), max(1, mi), am_bool, p_store, p_state, p_unm, min_cov


def run_odds_refresh(
    *,
    tournament: str = "nhl",
    sport_key: str = "icehockey_nhl",
    bookmaker_key: str = "the_odds_api",
    buffer_days: int | None = None,
    max_days_per_refresh: int | None = None,
    auto_merge: bool | None = None,
    min_odds_coverage_pct: float | None = None,
    source_config_name: str | None = "nhl",
    store_path: Path | None = None,
    refresh_state_path: Path | None = None,
    unmatched_report_path: Path | None = None,
    source_csv_path: Path | None = None,
    project_root: Path | None = None,
    today: date | None = None,
    run_backfill_fn: Callable[..., pd.DataFrame | BackfillRunResult] | None = None,
) -> OddsRefreshResult:
    """Инкрементальный refresh: backfill в окне, upsert store, optional merge в ``source.csv``.

    Состояние записывается **до** сегмента (старт) и **после** (прогресс/завершение).
    """
    root = project_root or PROJECT_ROOT
    td = today or date.today()
    cfg_book = load_bookmaker_config(bookmaker_key)
    if cfg_book is None:
        raise ValueError(f"Конфиг bookmaker {bookmaker_key!r} не найден")
    book_root: Any = OmegaConf.select(cfg_book, "bookmaker")
    if book_root is None:
        book_root = cfg_book

    b_def, m_def, am_def, cfg_store, cfg_state, cfg_unm, cfg_min_cov = _odds_runtime_from_source(
        source_config_name, tournament, root
    )
    buf = b_def if buffer_days is None else buffer_days
    mx_days = m_def if max_days_per_refresh is None else max_days_per_refresh
    do_merge = am_def if auto_merge is None else auto_merge
    min_cov_cfg = cfg_min_cov if min_odds_coverage_pct is None else float(min_odds_coverage_pct)
    if buf < 0:
        raise ValueError("buffer_days must be >= 0")
    if mx_days < 1:
        raise ValueError("max_days_per_refresh must be >= 1")

    p_store = store_path or cfg_store
    st_path = refresh_state_path or cfg_state
    p_unmatched = unmatched_report_path or cfg_unm
    p_csv = source_csv_path or default_source_csv_path(tournament, root)
    backfill_call = run_backfill_fn or run_backfill
    reg = _resolve_team_registry(tournament, sport_key)

    state_in = load_refresh_state(st_path)
    store_df = load_odds_store(p_store)
    plan = build_incremental_need_range(store_df, buf, td, book_root, tournament, state_in)
    seg = build_refresh_segment(plan, mx_days, state_in)

    has_more = seg.has_more
    next_in_progress: str | None
    if has_more and seg.date_to < plan.need_to:
        next_in_progress = (seg.date_to + timedelta(days=1)).isoformat()
    else:
        next_in_progress = None

    if seg.date_to < seg.date_from:
        st_skip = state_in or RefreshState(
            last_successful_date=None, in_progress_from=None, updated_at=_now_utc_iso()
        )
        save_refresh_state(st_path, st_skip)
        return OddsRefreshResult(
            segment=seg,
            new_odds_rows=0,
            store_rows=len(store_df),
            merged_source=False,
            quota_hit=False,
            state=st_skip,
            used_empty_store_season=plan.used_empty_store_season,
            requests_remaining=None,
            requests_used=None,
        )

    before = RefreshState(
        last_successful_date=state_in.last_successful_date if state_in else None,
        in_progress_from=seg.date_from.isoformat(),
        updated_at=_now_utc_iso(),
    )
    save_refresh_state(st_path, before)

    raw_out = backfill_call(
        date_from=seg.date_from,
        date_to=seg.date_to,
        tournament=tournament,
        sport_key=sport_key,
        store_path=p_store,
        bookmaker_key=bookmaker_key,
    )
    new_part, quota_hit, req_rem, req_used = _normalize_backfill_out(raw_out)
    n_new = len(new_part)

    final_store = load_odds_store(p_store)
    if not final_store.empty:
        validate_pinnacle_odds_float_columns(
            final_store, context="odds refresh: store after backfill"
        )

    if req_rem is not None or req_used is not None:
        logger.info(
            "odds refresh: The Odds API quota (посл. ответ) requests_remaining=%s requests_used=%s",
            req_rem,
            req_used,
        )
    st_after: RefreshState
    if has_more and next_in_progress is not None:
        st_after = RefreshState(
            last_successful_date=seg.date_to.isoformat(),
            in_progress_from=next_in_progress,
            updated_at=_now_utc_iso(),
        )
    else:
        st_after = RefreshState(
            last_successful_date=seg.date_to.isoformat(),
            in_progress_from=None,
            updated_at=_now_utc_iso(),
        )
    save_refresh_state(st_path, st_after)

    merged = False
    if do_merge and p_csv.exists() and not final_store.empty:
        merge_odds_into_source_csv(
            str(p_csv),
            final_store,
            out_csv_path=None,
            book_cfg=cfg_book,
            team_registry=reg,
            unmatched_teams_path=p_unmatched,
            tournament=tournament,
            project_root=root,
        )
        merged = True
        _log_source_odds_metrics(p_csv, min_cov_cfg, len(final_store))
        _log_unmatched_report_metrics(p_unmatched)
    elif do_merge and not p_csv.exists():
        logger.info("odds refresh: source.csv нет — merge пропущен: %s", p_csv)
    elif do_merge and final_store.empty:
        logger.info("odds refresh: пустой store — merge в source пропущен")

    return OddsRefreshResult(
        segment=seg,
        new_odds_rows=n_new,
        store_rows=len(final_store),
        merged_source=merged,
        quota_hit=quota_hit,
        state=st_after,
        used_empty_store_season=plan.used_empty_store_season,
        requests_remaining=req_rem,
        requests_used=req_used,
    )
