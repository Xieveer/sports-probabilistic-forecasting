#!/usr/bin/env python3
# ruff: noqa: E402 — ``sys.path`` до импортов ``sports_forecast`` для ``uv run python scripts/...``.
"""Краткая выгрузка нескольких матчей The Odds API в CSV (текущие линии, без исторического date).

Пример::

    uv run python scripts/export_odds_sample_matches.py --limit 5

Требуется ``ODDS_API_KEY`` в окружении или ``.env``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from dotenv import load_dotenv
from omegaconf import DictConfig, OmegaConf

from sports_forecast.config.loaders import PROJECT_ROOT, load_bookmaker_config
from sports_forecast.data.providers.odds.client import OddsApiClient
from sports_forecast.data.providers.odds.enrichment import unwrap_odds_payload
from sports_forecast.data.providers.odds.sample_export import events_to_match_sample_dataframe
from sports_forecast.data.providers.odds.team_name_registry import load_nhl_team_name_registry


def _default_out_path() -> Path:
    return (PROJECT_ROOT / "data" / "source" / "nhl" / "odds" / "sample_api_matches.csv").resolve()


def main(argv: list[str] | None = None) -> int:
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sport-key", default="icehockey_nhl", help="Ключ спорта API")
    parser.add_argument("--regions", default="eu", help="Параметр regions")
    parser.add_argument("--limit", type=int, default=5, help="Число матчей в CSV")
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help=f"Путь CSV (по умолчанию: {_default_out_path()})",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Принудительно сетевой GET (игнорировать дисковый кэш клиента)",
    )
    args = parser.parse_args(argv)

    cfg: DictConfig | None = load_bookmaker_config("the_odds_api")
    if cfg is None:
        print("Не найден conf/bookmaker/the_odds_api.yaml", file=sys.stderr)
        return 1
    book_root = OmegaConf.select(cfg, "bookmaker")
    if book_root is None:
        book_root = cfg

    out_path = (args.out or _default_out_path()).resolve()
    reg = load_nhl_team_name_registry()

    client = OddsApiClient(bookmaker_cfg=cfg)
    payload = client.fetch_odds_for_sport(
        args.sport_key,
        regions=args.regions,
        use_cache=not args.no_cache,
    )
    events = unwrap_odds_payload(payload)
    df = events_to_match_sample_dataframe(
        events,
        book_root,
        team_registry=reg,
        limit=args.limit,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False)
    print(f"Wrote {len(df)} rows, {len(df.columns)} columns → {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
