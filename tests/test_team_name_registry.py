"""Тесты :mod:`sports_forecast.data.providers.odds.team_name_registry`."""

from __future__ import annotations

from pathlib import Path

from sports_forecast.data.providers.odds.team_name_registry import (
    TeamNameRegistry,
    load_team_name_registry_file,
    normalize_team_key,
)


def test_normalize_team_key_strips_punctuation() -> None:
    assert normalize_team_key("A-B C") == "ABC"
    assert normalize_team_key("  x  ") == "X"


def test_resolve_uses_both_sections() -> None:
    r = TeamNameRegistry.from_source_sections(
        nhl_api={"One Team": "OT"},
        odds_api={"1 Team": "OT"},
    )
    assert r.resolve("One Team") == "OT"
    assert r.resolve("1 Team") == "OT"
    assert r.resolve("Unknown") == "UNKNOWN"


def test_load_from_yaml_file(tmp_path: Path) -> None:
    p = tmp_path / "r.yaml"
    p.write_text(
        """
nhl_api:
  "San Jose": "SJS"
odds_api:
  "SJ": "SJS"
""",
        encoding="utf-8",
    )
    r = load_team_name_registry_file(p)
    assert not r.is_empty
    assert r.resolve("San Jose") == "SJS"
    assert r.resolve("SJ") == "SJS"


def test_missing_file_returns_empty_registry(tmp_path: Path) -> None:
    r = load_team_name_registry_file(tmp_path / "nope.yaml")
    assert r.is_empty
    assert r.resolve("Anything") == normalize_team_key("Anything")


def test_later_section_can_override(tmp_path: Path) -> None:
    p = tmp_path / "r.yaml"
    p.write_text(
        """
nhl_api:
  "X": "A"
odds_api:
  "X": "B"
""",
        encoding="utf-8",
    )
    r = load_team_name_registry_file(p)
    # odds_api second in from_source_sections order — actually we iterate nhl then odds
    # so "X" from nhl -> A, then "X" from odds -> B
    assert r.resolve("X") == "B"
