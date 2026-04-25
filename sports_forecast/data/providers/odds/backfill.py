"""Идемпотентный backfill исторических линий The Odds API (окно 2–3 сезонов).

Один календарный день: по умолчанию (R21.11) **один** close-снимок
:func:`snapshot_discovery.discover_close_snapshot_for_day` (T−N минут до ``commence``;
``snapshot_discovery.close_t_minus_minutes`` в YAML). Режим фиксированного UTC: ``--legacy-timestamps`` /
``legacy_timestamps`` — один снимок по ``backfill.close_snapshot_utc``.

CLI (диапазон дат)::

    uv run python -m sports_forecast.data.providers.odds.backfill \\
        --sport-key icehockey_nhl --from 2023-10-01 --to 2024-04-20

CLI (последние N сезонов NHL из ``conf/bookmaker/the_odds_api.yaml``)::

    uv run python -m sports_forecast.data.providers.odds.backfill \\
        --seasons 3 --tournament nhl --store

Слияние в ``source.csv`` — отдельно: :func:`sports_forecast.data.providers.odds.enrichment.merge_odds_into_source_csv`.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Final

import pandas as pd
from dotenv import load_dotenv
from omegaconf import DictConfig, OmegaConf

from sports_forecast.config.loaders import PROJECT_ROOT, load_bookmaker_config
from sports_forecast.data.providers.odds.client import OddsApiClient, QuotaBudgetError
from sports_forecast.data.providers.odds.enrichment import events_to_odds_frame, unwrap_odds_payload
from sports_forecast.data.providers.odds.snapshot_discovery import (
    CloseSnapshotPlan,
    discover_close_snapshot_for_day,
)
from sports_forecast.data.providers.odds.store import upsert_odds_store_file
from sports_forecast.data.providers.odds.team_name_registry import (
    TeamNameRegistry,
    load_nhl_team_name_registry,
)
from sports_forecast.utils.log_config import get_logger
from sports_forecast.validation.schemas import validate_odds_float_columns


logger = get_logger(__name__)

_PINNACLE_ODDS_FILE: Final[str] = "pinnacle_odds.parquet"


def _log_backfill_close_payload(
    day: date,
    payload: object,
) -> None:
    evs = unwrap_odds_payload(payload)
    keys: set[str] = set()
    for ev in evs:
        if not isinstance(ev, dict):
            continue
        for bm in ev.get("bookmakers") or []:
            if not isinstance(bm, dict):
                continue
            k = bm.get("key")
            if k is not None:
                keys.add(str(k))
    logger.info(
        "backfill_day_frames: day=%s events_found=%d bookmakers_in_response=%s",
        day.isoformat(),
        len(evs),
        sorted(keys),
    )


@dataclass(frozen=True)
class BackfillRunResult:
    """Результат :func:`run_backfill` (DataFrame + флаги квоты, для refresh/логов)."""

    frame: pd.DataFrame
    quota_hit: bool
    requests_remaining: int | None
    requests_used: int | None


@dataclass(frozen=True)
class _SeasonRow:
    """Один сезон из ``bookmaker.seasons.{tournament}``."""

    name: str
    date_from: date
    date_to: date


def daterange(d0: date, d1: date) -> list[date]:
    """Включительный перечень дат ``d0`` … ``d1`` (``d1`` >= ``d0``)."""
    out: list[date] = []
    cur = d0
    while cur <= d1:
        out.append(cur)
        cur += timedelta(days=1)
    return out


def default_odds_store_path(tournament: str, project_root: Path | None = None) -> Path:
    """Путь по умолчанию: ``data/source/{tournament}/odds/pinnacle_odds.parquet``."""
    root = project_root or PROJECT_ROOT
    return (root / "data" / "source" / tournament / "odds" / _PINNACLE_ODDS_FILE).resolve()


def _parse_season_rows_from_book_root(book_root: Any, tournament: str) -> list[_SeasonRow]:
    """Сезоны из конфига (порядок как в YAML — от старого к новому)."""
    raw = OmegaConf.select(book_root, f"seasons.{tournament}")
    if raw is None:
        return []
    items = OmegaConf.to_container(raw, resolve=True)
    if not isinstance(items, list):
        return []
    out: list[_SeasonRow] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        name = str(it.get("name", "") or "season")
        d0s = it.get("date_from")
        d1s = it.get("date_to")
        if not d0s or not d1s:
            continue
        try:
            d0 = date.fromisoformat(str(d0s))
            d1 = date.fromisoformat(str(d1s))
        except ValueError:
            continue
        if d1 < d0:
            continue
        out.append(_SeasonRow(name=name, date_from=d0, date_to=d1))
    return out


def last_n_season_windows(
    book_root: Any, tournament: str, last_n: int
) -> list[tuple[str, date, date]]:
    """``last_n`` последних сезонов из конфига: ``(имя, date_from, date_to)``."""
    if last_n < 1:
        raise ValueError("last_n должен быть >= 1")
    rows = _parse_season_rows_from_book_root(book_root, tournament)
    if not rows:
        raise ValueError(
            f"В конфиге bookmaker нет непустой секции seasons.{tournament} "
            f"(нужен список с name, date_from, date_to)"
        )
    n_conf = len(rows)
    if last_n > n_conf:
        logger.warning(
            "Запрошено %d последних сезонов, в конфиге только %d — используем все",
            last_n,
            n_conf,
        )
    return [(r.name, r.date_from, r.date_to) for r in rows[-last_n:]]


def _resolve_team_registry(tournament: str, sport_key: str) -> TeamNameRegistry | None:
    if tournament == "nhl" or sport_key == "icehockey_nhl":
        return load_nhl_team_name_registry()
    return None


def _book_get(book_root: Any, key: str) -> Any:
    """Поле узла ``bookmaker``: обычный ``dict`` или ``DictConfig`` (OmegaConf)."""
    if isinstance(book_root, dict):
        return book_root.get(key)
    return OmegaConf.select(book_root, key)


def _close_t_minus_minutes_from_config(book_root: Any) -> int:
    """``snapshot_discovery.close_t_minus_minutes`` (R21.11), по умолчанию 15."""
    raw = _book_get(book_root, "snapshot_discovery")
    if raw is None:
        return 15
    sd = raw if isinstance(raw, dict) else (OmegaConf.to_container(raw, resolve=True) or {})
    if not isinstance(sd, dict):
        return 15
    try:
        m = int(sd.get("close_t_minus_minutes", 15))
    except (TypeError, ValueError):
        m = 15
    return max(1, m)


def _attach_close_snapshot_timing(
    fr: pd.DataFrame,
    plan: CloseSnapshotPlan,
) -> pd.DataFrame:
    """Добавить в кадр V3: ``close_snapshot_utc``, ``close_minutes_before`` (R21.11)."""
    if fr.empty:
        return fr
    out = fr.copy()
    out["close_snapshot_utc"] = plan.close_iso
    out["close_minutes_before"] = int(plan.close_minutes_before)
    return out


def _legacy_day_snapshot_isos(
    day: date,
    open_t: str,
    close_t: str,
) -> tuple[str, str]:
    """Собрать open/close ISO из ``backfill.open_snapshot_utc`` / ``close_snapshot_utc`` (R20)."""
    day_s = day.isoformat()
    to = str(open_t).strip()
    tc = str(close_t).strip()
    if "T" in to and ("Z" in to or "+" in to):
        open_iso = to
    else:
        open_iso = f"{day_s}T{to}Z" if not to.upper().endswith("Z") else to
    if "T" in tc and ("Z" in tc or "+" in tc):
        close_iso = tc
    else:
        close_iso = f"{day_s}T{tc}Z" if not tc.upper().endswith("Z") else tc
    return (open_iso, close_iso)


def _read_quota_budget(book_root: Any) -> int | None:
    v = book_root.get("quota_budget_per_run") if hasattr(book_root, "get") else None
    if v is None:
        return 100
    try:
        n = int(v)
    except (TypeError, ValueError):
        return 100
    if n <= 0:
        return None
    return n


def backfill_day_frames(
    client: OddsApiClient,
    sport_key: str,
    day: date,
    book_root: Any,
    *,
    regions: str = "eu",
    team_registry: TeamNameRegistry | None = None,
    legacy_timestamps: bool = False,
) -> pd.DataFrame:
    """Загрузить (с кэшем) **close**-снимок на день и вернуть таблицу для OddsStore V3.

    При ``legacy_timestamps=False`` — :func:`snapshot_discovery.discover_close_snapshot_for_day`
    (T−N минут до ``min(commence)``). В кадр: ``close_snapshot_utc``, ``close_minutes_before``.

    Args:
        client: Клиент API.
        sport_key: Ключ спорта (``icehockey_nhl``).
        day: Календарная дата матчей (UTC по ``commence``).
        book_root: Узел ``bookmaker`` с ``bookmakers``, ``output_columns``, ``backfill``,
            ``snapshot_discovery``.
        regions: Регион букмекеров.
        team_registry: Нормализация названий (alias → canonical).
        legacy_timestamps: ``True`` — одна GET по ``backfill.close_snapshot_utc`` (без discovery).

    Returns:
        DataFrame для :func:`enrichment.merge_odds_into_source_dataframe` / OddsStore V3.
    """
    bk = _book_get(book_root, "bookmakers") or {}
    primary = str(bk.get("primary", "pinnacle"))
    raw_oc = _book_get(book_root, "output_columns") or {}
    if isinstance(raw_oc, dict):
        out_cols = dict(raw_oc)
    else:
        out_cols = OmegaConf.to_container(raw_oc, resolve=True)
    if not isinstance(out_cols, dict):
        out_cols = {}

    bf = _book_get(book_root, "backfill") or {}
    if not isinstance(bf, dict):
        bf = OmegaConf.to_container(bf, resolve=True)
    if not isinstance(bf, dict):
        bf = {}
    open_t = str(bf.get("open_snapshot_utc", "12:00:00"))
    close_t = str(bf.get("close_snapshot_utc", "23:30:00"))
    _legacy_open_iso, legacy_c = _legacy_day_snapshot_isos(day, open_t, close_t)

    def _one_close_frame(events: list[dict[str, Any]], plan: CloseSnapshotPlan) -> pd.DataFrame:
        fr = events_to_odds_frame(
            events,
            None,
            primary,
            out_cols,
            team_registry=team_registry,
            book_cfg=book_root,
        )
        return _attach_close_snapshot_timing(fr, plan)

    if legacy_timestamps:
        p_close = client.fetch_odds_for_sport(
            sport_key, regions=regions, date_iso=legacy_c, use_cache=True
        )
        _log_backfill_close_payload(day, p_close)
        ev = unwrap_odds_payload(p_close)
        plan = CloseSnapshotPlan(
            close_iso=legacy_c,
            close_minutes_before=0,
            reference_commence_time_utc=None,
            used_legacy_timestamps=True,
        )
        return _one_close_frame(ev, plan)

    tminus = _close_t_minus_minutes_from_config(book_root)
    plan, p_close = discover_close_snapshot_for_day(
        client,
        sport_key,
        day,
        regions=regions,
        close_t_minus_minutes=tminus,
        legacy_open_time_utc=open_t,
        legacy_close_time_utc=close_t,
        use_cache=True,
    )
    _log_backfill_close_payload(day, p_close)
    ev = unwrap_odds_payload(p_close)
    return _one_close_frame(ev, plan)


def _concat_dedup(parts: list[pd.DataFrame]) -> pd.DataFrame:
    if not parts:
        return pd.DataFrame()
    all_df = pd.concat(parts, ignore_index=True)
    return all_df.drop_duplicates(
        subset=["game_date", "home_team_norm", "away_team_norm"], keep="last"
    )


def _upsert_if_non_empty(
    chunk: pd.DataFrame,
    store_path: Path,
    *,
    context: str,
) -> None:
    if chunk.empty or store_path is None:
        return
    validate_odds_float_columns(chunk, context=context)
    upsert_odds_store_file(chunk, store_path)


def _backfill_date_range(
    client: OddsApiClient,
    book_root: Any,
    d0: date,
    d1: date,
    *,
    sport_key: str,
    regions: str,
    team_registry: TeamNameRegistry | None,
    legacy_timestamps: bool = False,
) -> tuple[pd.DataFrame, bool]:
    """Собрать дни [d0,d1]. Второй элемент — True, если остановка по :exc:`QuotaBudgetError` (частичные данные)."""
    parts: list[pd.DataFrame] = []
    days = daterange(d0, d1)
    total_days = len(days)
    for i, d in enumerate(days, start=1):
        qsnap = client.last_quota()
        logger.info(
            "backfill: Day %d/%d date=%s quota_remaining=%s",
            i,
            total_days,
            d.isoformat(),
            qsnap.requests_remaining,
        )
        try:
            fr = backfill_day_frames(
                client,
                sport_key,
                d,
                book_root,
                regions=regions,
                team_registry=team_registry,
                legacy_timestamps=legacy_timestamps,
            )
            if not fr.empty:
                parts.append(fr)
        except QuotaBudgetError as e:
            logger.warning("backfill: квота run исчерпана, останавливаемся на дате %s — %s", d, e)
            return _concat_dedup(parts), True
        except Exception as e:
            logger.warning("backfill: пропуск дня %s — %s", d, e)
    return _concat_dedup(parts), False


def run_backfill(
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    seasons_last_n: int | None = None,
    tournament: str = "nhl",
    sport_key: str = "icehockey_nhl",
    regions: str = "eu",
    out_parquet: Path | None = None,
    store_path: Path | None = None,
    bookmaker_key: str = "the_odds_api",
    legacy_timestamps: bool = False,
) -> BackfillRunResult:
    """Собрать backfill: либо ``date_from..date_to``, либо ``seasons_last_n`` последних сезонов.

    Сезоны обрабатываются **по очереди** (с логами по каждому). При ``store_path`` после каждого
    завершённого сезона (или оставшегося куска при остановке по квоте) вызывается
    :func:`store.upsert_odds_store_file`, чтобы не терять прогресс.

    Args:
        date_from, date_to: Календарный диапазон (должны быть заданы вместе, если нет ``seasons_last_n``).
        seasons_last_n: Число последних сезонов из ``bookmaker.seasons.{tournament}``; альтернатива датам.
        tournament: Ключ в ``seasons`` и в пути store по умолчанию.
        store_path: Если задан, upsert в Parquet-файл OddsStore.
        legacy_timestamps: Только фиксированный ``backfill.close_snapshot_utc``; иначе
            :func:`snapshot_discovery.discover_close_snapshot_for_day` (T−N мин, по YAML).

    Returns:
        :class:`BackfillRunResult` с дедуп DataFrame, флагом исчерпания квоты и
        (после запросов) снимком ``x-requests-*`` с последнего ответа API.
    """
    if seasons_last_n is not None:
        if date_from is not None or date_to is not None:
            raise ValueError("Нельзя сочетать seasons_last_n с date_from/date_to")
    else:
        if date_from is None or date_to is None:
            raise ValueError("Укажите date_from и date_to либо seasons_last_n")
        if date_to < date_from:
            raise ValueError("date_to < date_from")

    cfg: DictConfig | None = load_bookmaker_config(bookmaker_key)
    if cfg is None:
        raise ValueError("Не найден conf/bookmaker/the_odds_api.yaml")
    book_root = OmegaConf.select(cfg, "bookmaker")
    if book_root is None:
        book_root = cfg

    quota = _read_quota_budget(book_root)
    client = OddsApiClient(bookmaker_cfg=cfg, max_real_http_requests=quota)
    team_registry = _resolve_team_registry(tournament, sport_key)

    ran_seasons: list[str] = []
    all_chunks: list[pd.DataFrame] = []
    hit_quota_out = False

    if seasons_last_n is not None:
        try:
            windows = last_n_season_windows(book_root, tournament, seasons_last_n)
        except ValueError as e:
            raise ValueError(str(e)) from e
        for name, s0, s1 in windows:
            logger.info("backfill: сезон %s — диапазон %s..%s", name, s0, s1)
            ran_seasons.append(name)
            chunk, hit_quota = _backfill_date_range(
                client,
                book_root,
                s0,
                s1,
                sport_key=sport_key,
                regions=regions,
                team_registry=team_registry,
                legacy_timestamps=legacy_timestamps,
            )
            if not chunk.empty and store_path is not None:
                _upsert_if_non_empty(chunk, store_path, context="backfill:upsert")
                logger.info(
                    "backfill: upsert store после сезона %s (%d строк) → %s",
                    name,
                    len(chunk),
                    store_path,
                )
            all_chunks.append(chunk)
            if hit_quota:
                hit_quota_out = True
                logger.info(
                    "backfill: достигнут лимит сетевых запросов за run (%s) — дальше не идём",
                    quota,
                )
                break
    else:
        assert date_from is not None and date_to is not None
        name = f"{date_from}..{date_to}"
        logger.info("backfill: диапазон %s", name)
        chunk, hit_quota = _backfill_date_range(
            client,
            book_root,
            date_from,
            date_to,
            sport_key=sport_key,
            regions=regions,
            team_registry=team_registry,
            legacy_timestamps=legacy_timestamps,
        )
        hit_quota_out = hit_quota
        all_chunks.append(chunk)
        if not chunk.empty and store_path is not None:
            _upsert_if_non_empty(chunk, store_path, context="backfill:upsert")
            logger.info("backfill: upsert store (%d строк) → %s", len(chunk), store_path)

    result = _concat_dedup(all_chunks)
    q_snap = client.last_quota()
    if out_parquet is not None and not result.empty:
        out_parquet.parent.mkdir(parents=True, exist_ok=True)
        result.to_parquet(out_parquet, index=False)
        logger.info("backfill: сохранено %d строк → %s", len(result), out_parquet)
    elif out_parquet is not None and result.empty:
        logger.info("backfill: пустой результат — %s не создан", out_parquet)
    if ran_seasons:
        seasons_label = ", ".join(ran_seasons)
    else:
        assert date_from is not None and date_to is not None
        seasons_label = f"{date_from.isoformat()}..{date_to.isoformat()}"
    logger.info(
        "Backfill done: seasons=%s, total_rows=%d, quota_used=%s, quota_remaining=%s",
        seasons_label,
        len(result),
        q_snap.requests_used,
        q_snap.requests_remaining,
    )
    return BackfillRunResult(
        frame=result,
        quota_hit=hit_quota_out,
        requests_remaining=q_snap.requests_remaining,
        requests_used=q_snap.requests_used,
    )


def main(argv: list[str] | None = None) -> int:
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    parser = argparse.ArgumentParser(description="Backfill The Odds API → parquet / OddsStore")
    parser.add_argument("--sport-key", default="icehockey_nhl", help="Ключ спорта API")
    parser.add_argument(
        "--from",
        dest="date_from",
        default=None,
        help="YYYY-MM-DD (вместе с --to, если нет --seasons)",
    )
    parser.add_argument(
        "--to",
        dest="date_to",
        default=None,
        help="YYYY-MM-DD",
    )
    parser.add_argument(
        "--seasons",
        type=int,
        default=None,
        metavar="N",
        help="Взять N последних сезонов из bookmaker.seasons.{tournament} в the_odds_api.yaml",
    )
    parser.add_argument(
        "--tournament",
        type=str,
        default="nhl",
        help="Ключ в seasons и имя подкаталога data/source/ (по умолчанию nhl)",
    )
    parser.add_argument(
        "--regions",
        default="eu",
        help="Регион букмекеров (Pinnacle часто доступен в eu)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Путь к parquet со всеми строками (опционально)",
    )
    parser.add_argument(
        "--store",
        type=str,
        nargs="?",
        const="",
        default=None,
        metavar="PATH",
        help="Upsert в OddsStore. Без значения: data/source/TOURNAMENT/odds/pinnacle_odds.parquet",
    )
    parser.add_argument(
        "--legacy-timestamps",
        action="store_true",
        help="Только backfill.open_snapshot_utc/close в конфиге (R20), без динамического snapshot discovery",
    )
    args = parser.parse_args(argv)

    if args.seasons is not None:
        if args.date_from is not None or args.date_to is not None:
            logger.error("Нельзя сочетать --seasons и --from/--to")
            return 1
    else:
        if args.date_from is None or args.date_to is None:
            logger.error("Укажите --from и --to или --seasons N")
            return 1

    d0: date | None = None
    d1: date | None = None
    if args.date_from and args.date_to:
        d0 = date.fromisoformat(args.date_from)
        d1 = date.fromisoformat(args.date_to)
        if d1 < d0:
            logger.error("date_to < date_from")
            return 1

    store_path: Path | None = None
    if args.store is not None:
        if args.store == "":
            store_path = default_odds_store_path(args.tournament)
        else:
            store_path = Path(args.store).expanduser().resolve()

    try:
        run_backfill(
            date_from=d0,
            date_to=d1,
            seasons_last_n=args.seasons,
            tournament=args.tournament,
            sport_key=args.sport_key,
            regions=args.regions,
            out_parquet=args.out,
            store_path=store_path,
            legacy_timestamps=args.legacy_timestamps,
        )
    except ValueError as e:
        logger.error("%s", e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
