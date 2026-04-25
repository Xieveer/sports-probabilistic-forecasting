"""Идемпотентный backfill исторических линий The Odds API (окно 2–3 сезонов).

Один календарный день: до двух запросов (open/close UTC из конфига), ответы кэшируются на диск.
Не тянет «всю историю» — по умолчанию ~900 дней назад от ``date_to``.

CLI::

    uv run python -m sports_forecast.data.providers.odds.backfill \\
        --sport-key icehockey_nhl --from 2023-10-01 --to 2024-04-20

Слияние в ``source.csv`` — отдельно: :func:`sports_forecast.data.providers.odds.enrichment.merge_odds_into_source_csv`.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
from dotenv import load_dotenv
from omegaconf import OmegaConf

from sports_forecast.config.loaders import PROJECT_ROOT, load_bookmaker_config
from sports_forecast.data.providers.odds.client import OddsApiClient
from sports_forecast.data.providers.odds.enrichment import events_to_odds_frame, unwrap_odds_payload
from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)

_DEFAULT_LOOKBACK_DAYS = 900  # ~2.5 сезона


def daterange(d0: date, d1: date) -> list[date]:
    """Включительный перечень дат ``d0`` … ``d1`` (``d1`` >= ``d0``)."""
    out: list[date] = []
    cur = d0
    while cur <= d1:
        out.append(cur)
        cur += timedelta(days=1)
    return out


def backfill_day_frames(
    client: OddsApiClient,
    sport_key: str,
    day: date,
    book_root: Any,
    *,
    regions: str = "eu",
    use_open_close: bool = True,
) -> pd.DataFrame:
    """Загрузить (с кэшем) снимки на день и вернуть таблицу для merge.

    Args:
        client: Клиент API.
        sport_key: Ключ спорта (``icehockey_nhl``).
        day: Календарная дата (для двух ISO timestamp внутри дня).
        book_root: Узел ``bookmaker`` (или корень) с ``bookmakers``, ``output_columns``, ``backfill``.
        regions: Регион букмекеров (Pinnacle часто в ``eu``).
        use_open_close: Два снимка в день; ``False`` — один снимок (экономия квоты).

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
        return events_to_odds_frame(ev_o, ev_c, primary, out_cols)

    iso_mid = f"{day_s}T{open_t}Z"
    p_one = client.fetch_odds_for_sport(
        sport_key,
        regions=regions,
        date_iso=iso_mid,
        use_cache=True,
    )
    ev = unwrap_odds_payload(p_one)
    return events_to_odds_frame(ev, None, primary, out_cols)


def run_backfill(
    date_from: date,
    date_to: date,
    *,
    sport_key: str,
    regions: str,
    out_parquet: Path | None,
    use_open_close: bool,
) -> pd.DataFrame:
    """Собрать все дни в один DataFrame (дедуп по game_date + teams)."""
    cfg = load_bookmaker_config("the_odds_api")
    if cfg is None:
        raise ValueError("Не найден conf/bookmaker/the_odds_api.yaml")
    book_root = OmegaConf.select(cfg, "bookmaker")
    if book_root is None:
        book_root = cfg

    client = OddsApiClient(bookmaker_cfg=cfg)
    parts: list[pd.DataFrame] = []
    for d in daterange(date_from, date_to):
        try:
            fr = backfill_day_frames(
                client,
                sport_key,
                d,
                book_root,
                regions=regions,
                use_open_close=use_open_close,
            )
            if not fr.empty:
                parts.append(fr)
        except Exception as e:
            logger.warning("backfill: пропуск дня %s — %s", d, e)
    if not parts:
        return pd.DataFrame()
    all_df = pd.concat(parts, ignore_index=True)
    all_df = all_df.drop_duplicates(
        subset=["game_date", "home_team_norm", "away_team_norm"], keep="last"
    )
    if out_parquet is not None:
        out_parquet.parent.mkdir(parents=True, exist_ok=True)
        all_df.to_parquet(out_parquet, index=False)
        logger.info("backfill: сохранено %d строк → %s", len(all_df), out_parquet)
    return all_df


def main(argv: list[str] | None = None) -> int:
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    parser = argparse.ArgumentParser(description="Backfill The Odds API → parquet")
    parser.add_argument("--sport-key", default="icehockey_nhl", help="Ключ спорта API")
    parser.add_argument("--from", dest="date_from", required=True, help="YYYY-MM-DD")
    parser.add_argument("--to", dest="date_to", required=True, help="YYYY-MM-DD")
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
        "--single-snapshot",
        action="store_true",
        help="Один снимок на день (меньше запросов; open=close)",
    )
    args = parser.parse_args(argv)

    d0 = date.fromisoformat(args.date_from)
    d1 = date.fromisoformat(args.date_to)
    if d1 < d0:
        logger.error("date_to < date_from")
        return 1

    run_backfill(
        d0,
        d1,
        sport_key=args.sport_key,
        regions=args.regions,
        out_parquet=args.out,
        use_open_close=not args.single_snapshot,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
