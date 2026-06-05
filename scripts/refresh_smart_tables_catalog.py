#!/usr/bin/env python3
"""Обновить ``competition_catalog.json`` (slug → competition_id, match_count).

Читает существующий каталог или пары slug из HTML nationals, для каждой пары:
``GET /competitions/by-slug/`` и ``GET /matches?limit=1`` для ``total``.

Usage::

    uv run python scripts/refresh_smart_tables_catalog.py
    uv run python scripts/refresh_smart_tables_catalog.py --output docs/cursor/source_data/smart-tables/competition_catalog.json
"""

from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from typing import Any

from omegaconf import OmegaConf

from sports_forecast.config.loaders import PROJECT_ROOT
from sports_forecast.data.providers.smart_tables.catalog import load_competition_catalog
from sports_forecast.data.providers.smart_tables.client import SmartTablesApiClient


DEFAULT_CATALOG = PROJECT_ROOT / "docs/cursor/source_data/smart-tables/competition_catalog.json"
DEFAULT_HTML = (
    PROJECT_ROOT
    / "docs/cursor/source_data/smart-tables/Полный список футбольных лиг на Smart Tables.html"
)


def _slug_pairs_from_html(html_path: Path) -> list[tuple[str, str]]:
    text = html_path.read_text(encoding="utf-8", errors="replace")
    pairs = sorted(set(re.findall(r"/league/([^/]+)/([^\"'?#]+)", text)))
    return [(c, comp) for c, comp in pairs]


def _slug_pairs_from_catalog(path: Path) -> list[tuple[str, str]]:
    entries = load_competition_catalog(path)
    return [(e.country_slug, e.competition_slug) for e in entries]


def _match_total(client: SmartTablesApiClient, competition_id: int) -> int:
    payload = client.get_json(
        "matches",
        params={
            "offset": 0,
            "limit": 1,
            "filter[competition_id]": competition_id,
        },
    )
    data = payload.get("data")
    if isinstance(data, dict) and data.get("total") is not None:
        return int(data["total"])
    return 0


def refresh_catalog(
    pairs: list[tuple[str, str]],
    *,
    client: SmartTablesApiClient,
    delay_sec: float = 0.35,
) -> list[dict[str, Any]]:
    """Обойти slug-пары и собрать записи каталога."""
    out: list[dict[str, Any]] = []
    for country_slug, competition_slug in pairs:
        time.sleep(delay_sec)
        try:
            by_slug = client.get_json(
                "competitions/by-slug/",
                params={
                    "country_slug": country_slug,
                    "competition_slug": competition_slug,
                    "relatedEntities": "country",
                },
            )
        except Exception as e:
            out.append(
                {
                    "country_slug": country_slug,
                    "competition_slug": competition_slug,
                    "error": str(e),
                }
            )
            continue
        data = by_slug.get("data")
        item = data.get("item") if isinstance(data, dict) else None
        if not isinstance(item, dict):
            out.append(
                {
                    "country_slug": country_slug,
                    "competition_slug": competition_slug,
                    "error": "no item",
                }
            )
            continue
        cid = int(item["id"])
        time.sleep(delay_sec)
        match_count = _match_total(client, cid)
        out.append(
            {
                "country_slug": country_slug,
                "competition_slug": competition_slug,
                "competition_id": cid,
                "code": item.get("code", ""),
                "title": item.get("title") or item.get("common_title", ""),
                "for_national_teams": int(item.get("for_national_teams") or 0),
                "match_count": match_count,
            }
        )
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh Smart Tables competition catalog")
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_CATALOG,
        help="Путь к competition_catalog.json",
    )
    parser.add_argument(
        "--html",
        type=Path,
        default=DEFAULT_HTML,
        help="HTML со списком лиг (fallback для slug-пар)",
    )
    parser.add_argument(
        "--from-existing",
        action="store_true",
        help="Брать slug-пары из существующего catalog вместо HTML",
    )
    args = parser.parse_args()

    if args.from_existing and args.output.is_file():
        pairs = _slug_pairs_from_catalog(args.output)
    elif args.html.is_file():
        pairs = _slug_pairs_from_html(args.html)
    elif args.output.is_file():
        pairs = _slug_pairs_from_catalog(args.output)
    else:
        raise SystemExit("Нет HTML и каталога для slug-пар")

    provider_cfg = OmegaConf.create(
        {
            "base_url": "https://backend.smart-tables.ru/api/v1",
            "min_delay_sec": 1.0,
        }
    )
    client = SmartTablesApiClient(provider_cfg)
    catalog = refresh_catalog(pairs, client=client)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
    ok = sum(1 for x in catalog if "competition_id" in x)
    print(f"Wrote {len(catalog)} entries ({ok} ok) → {args.output}")


if __name__ == "__main__":
    main()
