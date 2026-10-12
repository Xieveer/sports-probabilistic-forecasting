"""Проверка состава и покрытия локального клубного снимка."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from sports_forecast.validation.club_pool_coverage import inspect_club_pool_source


def _write_rows(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=[
                "match_id",
                "competition_code",
                "datetime",
                "match_is_end",
                "odd_home",
                "odd_draw",
                "odd_away",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)


def test_coverage_reports_each_competition_and_odds_gap(tmp_path: Path) -> None:
    """Один пробел в odds виден в отчёте, не теряя клубный матч."""
    path = tmp_path / "source.csv"
    _write_rows(
        path,
        [
            {
                "match_id": "1",
                "competition_code": "ENG1",
                "datetime": "2025-01-01 12:00:00",
                "match_is_end": "1",
                "odd_home": "2",
                "odd_draw": "3",
                "odd_away": "4",
            },
            {
                "match_id": "2",
                "competition_code": "SPA1",
                "datetime": "2025-01-02 12:00:00",
                "match_is_end": "1",
                "odd_home": "2",
                "odd_draw": "",
                "odd_away": "4",
            },
        ],
    )

    report = inspect_club_pool_source(path, expected_codes={"ENG1", "SPA1"})

    assert report["total_rows"] == 2
    assert report["competitions"]["ENG1"]["odds_triples"] == 1
    assert report["competitions"]["SPA1"]["odds_triples"] == 0
    assert report["competitions"]["SPA1"]["finished"] == 1


@pytest.mark.parametrize("codes", [{"ENG1", "SPA1"}, {"ENG1", "GER1"}])
def test_coverage_rejects_missing_or_unexpected_competition(
    tmp_path: Path, codes: set[str]
) -> None:
    """Состав snapshot должен точно совпадать с конфигурационным whitelist."""
    path = tmp_path / "source.csv"
    _write_rows(
        path,
        [
            {
                "match_id": "1",
                "competition_code": "ENG1",
                "datetime": "2025-01-01 12:00:00",
                "match_is_end": "1",
                "odd_home": "2",
                "odd_draw": "3",
                "odd_away": "4",
            }
        ],
    )

    with pytest.raises(ValueError, match="Состав соревнований"):
        inspect_club_pool_source(path, expected_codes=codes)


def test_coverage_rejects_duplicate_match_id(tmp_path: Path) -> None:
    """Дубли ID нельзя молча посчитать как два матча."""
    path = tmp_path / "source.csv"
    row = {
        "match_id": "1",
        "competition_code": "ENG1",
        "datetime": "2025-01-01 12:00:00",
        "match_is_end": "1",
        "odd_home": "2",
        "odd_draw": "3",
        "odd_away": "4",
    }
    _write_rows(path, [row, row])

    with pytest.raises(ValueError, match="Повторный match_id"):
        inspect_club_pool_source(path, expected_codes={"ENG1"})
