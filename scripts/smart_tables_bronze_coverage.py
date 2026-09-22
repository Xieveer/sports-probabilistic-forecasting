#!/usr/bin/env python3
# ruff: noqa: E402 — ``sys.path`` нужен при прямом запуске из scripts/.
"""Показать полноту Smart Tables bronze и план targeted resume без HTTP.

Usage::

    uv run python scripts/smart_tables_bronze_coverage.py \
      --raw-root data/source/football_top_leagues/raw
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from sports_forecast.data.providers.smart_tables.bronze_manifest import (
    WINNER_BASELINE_PROFILE,
    BronzeManifest,
    scan_bronze_cache,
    write_manifest,
)


def _report(manifest: BronzeManifest) -> dict[str, Any]:
    """Собрать JSON-safe сводку coverage и targeted resume."""
    return {
        "manifest_version": manifest.manifest_version,
        "profile": {"name": manifest.profile_name, "version": manifest.profile_version},
        "matches_total": len(manifest.matches),
        "train_ready_coverage": manifest.train_ready_coverage,
        "component_coverage": manifest.component_coverage,
        "train_ready_match_ids": list(manifest.train_ready_match_ids),
        "missing_required_match_ids": list(manifest.missing_required_match_ids),
        "optional_only_match_ids": list(manifest.optional_only_match_ids),
    }


def main(argv: list[str] | None = None) -> int:
    """Запустить read-only scan и опционально сохранить его отдельным manifest-файлом."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-root", type=Path, required=True, help="Каталог bronze match-кэша")
    parser.add_argument(
        "--write-manifest",
        type=Path,
        default=None,
        help="Опциональный путь для JSON manifest; по умолчанию bronze не изменяется",
    )
    args = parser.parse_args(argv)

    manifest = scan_bronze_cache(args.raw_root, profile=WINNER_BASELINE_PROFILE)
    if args.write_manifest is not None:
        write_manifest(manifest, args.write_manifest)
    print(json.dumps(_report(manifest), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
