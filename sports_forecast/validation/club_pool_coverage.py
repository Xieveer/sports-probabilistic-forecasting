"""Проверка состава закреплённого клубного source CSV."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any

from sports_forecast.config.loaders import PROJECT_ROOT, load_source_config
from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)
_REQUIRED_COLUMNS = frozenset(
    {"match_id", "competition_code", "datetime", "match_is_end", "odd_home", "odd_draw", "odd_away"}
)


def inspect_club_pool_source(path: Path, *, expected_codes: set[str]) -> dict[str, Any]:
    """Проверить точный состав соревнований и вернуть покрытие по каждому коду."""
    if not expected_codes:
        raise ValueError("Whitelist соревнований пуст")
    if not path.is_file():
        raise FileNotFoundError(f"Клубный source CSV не найден: {path}")
    seen_ids: set[str] = set()
    coverage: dict[str, dict[str, Any]] = {}
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        missing_columns = _REQUIRED_COLUMNS - set(reader.fieldnames or ())
        if missing_columns:
            raise ValueError(f"Отсутствуют колонки source CSV: {sorted(missing_columns)}")
        for row in reader:
            match_id = (row["match_id"] or "").strip()
            code = (row["competition_code"] or "").strip().upper()
            when = (row["datetime"] or "").strip()
            if not match_id or not code or not when:
                raise ValueError("Пустой match_id, competition_code или datetime")
            if match_id in seen_ids:
                raise ValueError(f"Повторный match_id: {match_id}")
            seen_ids.add(match_id)
            item = coverage.setdefault(
                code,
                {"rows": 0, "finished": 0, "odds_triples": 0, "first": when, "last": when},
            )
            item["rows"] += 1
            item["finished"] += (row["match_is_end"] or "").strip().lower() in {"1", "true"}
            item["odds_triples"] += all(
                (row[key] or "").strip() for key in ("odd_home", "odd_draw", "odd_away")
            )
            item["first"] = min(item["first"], when)
            item["last"] = max(item["last"], when)
    actual_codes = set(coverage)
    if actual_codes != expected_codes:
        raise ValueError(
            "Состав соревнований source CSV не совпадает с конфигурацией: "
            f"missing={sorted(expected_codes - actual_codes)}, "
            f"unexpected={sorted(actual_codes - expected_codes)}"
        )
    return {
        "source_sha256": digest.hexdigest(),
        "total_rows": len(seen_ids),
        "competitions": {code: coverage[code] for code in sorted(coverage)},
    }


def main(argv: list[str] | None = None) -> int:
    """Напечатать компактное покрытие уже собранного клубного snapshot."""
    parser = argparse.ArgumentParser(description="Клубный source coverage")
    parser.add_argument(
        "--source", type=Path, default=PROJECT_ROOT / "data/source/football_top_leagues/source.csv"
    )
    args = parser.parse_args(argv)
    try:
        source = load_source_config("football_top_leagues")
        codes = set(source.provider.competition_codes)
        report = inspect_club_pool_source(args.source, expected_codes=codes)
    except (FileNotFoundError, OSError, ValueError) as exc:
        logger.error("Проверка клубного source не прошла: %s", exc)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
