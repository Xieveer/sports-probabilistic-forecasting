"""Идемпотентный backfill исторических линий The Odds API (окно 2–3 сезонов).

Один календарный день: до двух запросов (open/close UTC из конфига), ответы кэшируются на диск.
Не тянет «всю историю» — по умолчанию ~900 дней назад от ``date_to``.

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
from sports_forecast.data.providers.odds.store import upsert_odds_store_file
from sports_forecast.data.providers.odds.team_name_registry import (
    TeamNameRegistry,
    load_nhl_team_name_registry,
)
from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)

_PINNACLE_ODDS_FILE: Final[str] = "pinnacle_odds.parquet"


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
    use_open_close: bool = True,
    team_registry: TeamNameRegistry | None = None,
) -> pd.DataFrame:
    """Загрузить (с кэшем) снимки на день и вернуть таблицу для merge.

    Args:
        client: Клиент API.
        sport_key: Ключ спорта (``icehockey_nhl``).
        day: Календарная дата (для двух ISO timestamp внутри дня).
        book_root: Узел ``bookmaker`` (или корень) с ``bookmakers``, ``output_columns``, ``backfill``.
        regions: Регион букмекеров (Pinnacle часто в ``eu``).
        use_open_close: Два снимка в день; ``False`` — один снимок (экономия квоты).
        team_registry: Нормализация названий (alias → canonical) для согласованного merge/stored.

    Returns:
        DataFrame для :func:`enrichment.merge_odds_into_source_dataframe`.
    """
    bk = OmegaConf.select(book_root, "bookmakers") or {}
    primary = str(bk.get("primary", "pinnacle"))
    out_cols = OmegaConf.to_container(book_root.get("output_columns") or {}, resolve=True)
    if not isinstance(out_cols, dict):
        out_cols = {}

    bf = book_root.get("backfill") or {}
    open_t = str(bf.get("open_snapshot_utc", "12:00:00"))
    close_t = str(bf.get("close_snapshot_utc", "23:30:00"))
    day_s = day.isoformat()

    if use_open_close:
        iso_open = f"{day_s}T{open_t}Z"
        iso_close = f"{day_s}T{close_t}Z"
        p_open = client.fetch_odds_for_sport(
            sport_key,
            regions=regions,
            date_iso=iso_open,
            use_cache=True,
        )
        p_close = client.fetch_odds_for_sport(
            sport_key,
            regions=regions,
            date_iso=iso_close,
            use_cache=True,
        )
        ev_o = unwrap_odds_payload(p_open)
        ev_c = unwrap_odds_payload(p_close)
        return events_to_odds_frame(ev_o, ev_c, primary, out_cols, team_registry=team_registry)

    iso_mid = f"{day_s}T{open_t}Z"
    p_one = client.fetch_odds_for_sport(
        sport_key,
        regions=regions,
        date_iso=iso_mid,
        use_cache=True,
    )
    ev = unwrap_odds_payload(p_one)
    return events_to_odds_frame(ev, None, primary, out_cols, team_registry=team_registry)


def _concat_dedup(parts: list[pd.DataFrame]) -> pd.DataFrame:
    if not parts:
        return pd.DataFrame()
    all_df = pd.concat(parts, ignore_index=True)
    return all_df.drop_duplicates(
        subset=["game_date", "home_team_norm", "away_team_norm"], keep="last"
    )


def _backfill_date_range(
    client: OddsApiClient,
    book_root: Any,
    d0: date,
    d1: date,
    *,
    sport_key: str,
    regions: str,
    use_open_close: bool,
    team_registry: TeamNameRegistry | None,
) -> tuple[pd.DataFrame, bool]:
    """Собрать дни [d0,d1]. Второй элемент — True, если остановка по :exc:`QuotaBudgetError` (частичные данные)."""
    parts: list[pd.DataFrame] = []
    for d in daterange(d0, d1):
        try:
            fr = backfill_day_frames(
                client,
                sport_key,
                d,
                book_root,
                regions=regions,
                use_open_close=use_open_close,
                team_registry=team_registry,
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
    use_open_close: bool = True,
    store_path: Path | None = None,
    bookmaker_key: str = "the_odds_api",
) -> pd.DataFrame:
    """Собрать backfill: либо ``date_from..date_to``, либо ``seasons_last_n`` последних сезонов.

    Сезоны обрабатываются **по очереди** (с логами по каждому). При ``store_path`` после каждого
    завершённого сезона (или оставшегося куска при остановке по квоте) вызывается
    :func:`store.upsert_odds_store_file`, чтобы не терять прогресс.

    Args:
        date_from, date_to: Календарный диапазон (должны быть заданы вместе, если нет ``seasons_last_n``).
        seasons_last_n: Число последних сезонов из ``bookmaker.seasons.{tournament}``; альтернатива датам.
        tournament: Ключ в ``seasons`` и в пути store по умолчанию.
        store_path: Если задан, upsert в Parquet-файл OddsStore.

    Returns:
        Общий дедуп DataFrame.
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
                use_open_close=use_open_close,
                team_registry=team_registry,
            )
            if not chunk.empty and store_path is not None:
                upsert_odds_store_file(chunk, store_path)
                logger.info(
                    "backfill: upsert store после сезона %s (%d строк) → %s",
                    name,
                    len(chunk),
                    store_path,
                )
            all_chunks.append(chunk)
            if hit_quota:
                logger.info(
                    "backfill: достигнут лимит сетевых запросов за run (%s) — дальше не идём",
                    quota,
                )
                break
    else:
        assert date_from is not None and date_to is not None
        name = f"{date_from}..{date_to}"
        logger.info("backfill: диапазон %s", name)
        chunk, _hit_quota = _backfill_date_range(
            client,
            book_root,
            date_from,
            date_to,
            sport_key=sport_key,
            regions=regions,
            use_open_close=use_open_close,
            team_registry=team_registry,
        )
        all_chunks.append(chunk)
        if not chunk.empty and store_path is not None:
            upsert_odds_store_file(chunk, store_path)
            logger.info("backfill: upsert store (%d строк) → %s", len(chunk), store_path)

    result = _concat_dedup(all_chunks)
    if out_parquet is not None and not result.empty:
        out_parquet.parent.mkdir(parents=True, exist_ok=True)
        result.to_parquet(out_parquet, index=False)
        logger.info("backfill: сохранено %d строк → %s", len(result), out_parquet)
    elif out_parquet is not None and result.empty:
        logger.info("backfill: пустой результат — %s не создан", out_parquet)
    if ran_seasons:
        logger.info(
            "backfill: обработаны сезоны: %s; всего строк: %d", ", ".join(ran_seasons), len(result)
        )
    return result


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
        "--single-snapshot",
        action="store_true",
        help="Один снимок на день (меньше запросов; open=close)",
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
            use_open_close=not args.single_snapshot,
            store_path=store_path,
        )
    except ValueError as e:
        logger.error("%s", e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
