"""Tests for tournament filter env parsing in data steps."""

from __future__ import annotations

from sports_forecast.data.clean import _get_tournament_filter as clean_filter
from sports_forecast.data.ingest import _get_tournament_filter as ingest_filter


def test_tournament_filter_returns_none_when_missing(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Missing env var keeps default behavior (all tournaments)."""
    monkeypatch.delenv("SF_TOURNAMENT_FILTER", raising=False)

    assert ingest_filter() is None
    assert clean_filter() is None


def test_tournament_filter_parses_csv_values(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """CSV env var is normalized to trimmed unique tournament set."""
    monkeypatch.setenv("SF_TOURNAMENT_FILTER", " lp_ru,lp_eu, lp_ru ")

    expected = {"lp_ru", "lp_eu"}
    assert ingest_filter() == expected
    assert clean_filter() == expected
