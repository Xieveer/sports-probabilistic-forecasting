"""Unit-тесты динамического выбора open/close снимков (R21.4)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from sports_forecast.data.providers.odds.enrichment import unwrap_odds_payload
from sports_forecast.data.providers.odds.snapshot_discovery import (
    SnapshotPlan,
    build_close_snapshot_iso,
    commence_datetimes_from_events_payload,
    discover_snapshots_for_day,
    earliest_commence_on_day_from_payload,
    has_events_for_calendar_day,
    minutes_before_commence,
    parse_commence_utc_from_event,
    to_api_iso_z,
)


def _ev(commence: str) -> dict[str, Any]:
    return {
        "commence_time": commence,
        "home_team": "A",
        "away_team": "B",
        "bookmakers": [],
    }


def test_happy_path_known_commence_and_minutes() -> None:
    day = date(2024, 1, 10)
    ref_utc = datetime(2024, 1, 10, 20, 0, tzinfo=timezone.utc)
    seed_payload = {
        "data": [
            _ev("2024-01-10T20:00:00Z"),
            _ev("2024-01-10T23:00:00Z"),
        ]
    }
    # Probes: 72h (Jan 7 20:00) пусто для дня; 24h (Jan 9 20:00) — попадание
    t_72 = to_api_iso_z(ref_utc - timedelta(hours=72))
    t_24 = to_api_iso_z(ref_utc - timedelta(hours=24))
    t_close = build_close_snapshot_iso(ref_utc, 1.0)
    assert t_close == "2024-01-10T19:00:00Z"

    class C:
        def __init__(self) -> None:
            self.calls: list[str | None] = []

        def fetch_odds_for_sport(
            self,
            _sport: str,
            *,
            regions: str = "us",  # noqa: ARG002
            date_iso: str | None = None,
            use_cache: bool = True,  # noqa: ARG002
        ) -> object:
            self.calls.append(date_iso)
            if date_iso and date_iso.startswith("2024-01-10T12:00:00"):
                return seed_payload
            if date_iso == t_72:
                return {"data": []}
            if date_iso == t_24:
                return {"data": [_ev("2024-01-10T20:00:00Z")]}
            if date_iso == t_close:
                return {"data": [_ev("2024-01-10T20:00:00Z")]}
            return {"data": []}

    client = C()
    plan, p_open, p_close = discover_snapshots_for_day(
        client,  # type: ignore[arg-type]
        "icehockey_nhl",
        day,
        regions="eu",
        open_probe_offsets_hours=[72.0, 24.0],
        close_margin_hours=1.0,
        legacy_open_time_utc="12:00:00",
        legacy_close_time_utc="23:30:00",
    )
    assert isinstance(plan, SnapshotPlan)
    assert plan.open_iso == t_24
    assert plan.close_iso == t_close
    assert plan.reference_commence_time_utc == "2024-01-10T20:00:00Z"
    assert plan.close_minutes_before == 60
    assert plan.open_minutes_before == 24 * 60
    assert not plan.used_legacy_timestamps
    assert len(unwrap_odds_payload(p_open)) >= 1
    assert len(unwrap_odds_payload(p_close)) >= 1


def test_fallback_legacy_no_commence_in_seed() -> None:
    day = date(2024, 2, 1)

    class C:
        def __init__(self) -> None:
            self.calls: list[str | None] = []

        def fetch_odds_for_sport(
            self,
            _sport: str,
            *,
            date_iso: str | None = None,
            **_kwargs: object,
        ) -> object:
            self.calls.append(date_iso)
            if "12:00:00" in (date_iso or ""):
                return {"data": []}
            if "23:30:00" in (date_iso or ""):
                return {"data": []}
            return {"data": []}

    c = C()
    plan, _o, _cl = discover_snapshots_for_day(
        c,  # type: ignore[arg-type]
        "icehockey_nhl",
        day,
        regions="us",
        open_probe_offsets_hours=[24.0],
        legacy_open_time_utc="12:00:00",
        legacy_close_time_utc="23:30:00",
    )
    assert plan.used_legacy_timestamps
    assert plan.open_iso == "2024-02-01T12:00:00Z"
    assert plan.close_iso == "2024-02-01T23:30:00Z"
    assert plan.reference_commence_time_utc is None
    assert plan.open_minutes_before == 0
    assert plan.close_minutes_before == 0
    # seed + open + close
    assert len(c.calls) == 3
    assert c.calls[0] == "2024-02-01T12:00:00Z"


def test_open_probe_order_first_hit_wins() -> None:
    """Больший offset пустой, меньший — с данными: берём первый с данными по убыванию offset."""
    day = date(2024, 3, 15)
    ref_utc = datetime(2024, 3, 15, 1, 0, tzinfo=timezone.utc)
    seed = {"data": [_ev("2024-03-15T01:00:00Z")]}
    t_48 = to_api_iso_z(ref_utc - timedelta(hours=48))
    t_6 = to_api_iso_z(ref_utc - timedelta(hours=6))
    t_close = build_close_snapshot_iso(ref_utc, 1.0)

    class C:
        def __init__(self) -> None:
            self.n = 0

        def fetch_odds_for_sport(
            self,
            _sport: str,
            *,
            date_iso: str | None = None,
            **_kwargs: object,
        ) -> object:
            if "T12:00:00" in (date_iso or ""):
                return seed
            if date_iso == t_48:
                return {"data": []}
            if date_iso == t_6:
                return {"data": [_ev("2024-03-15T01:00:00Z")]}
            if date_iso == t_close:
                return {"data": [_ev("2024-03-15T01:00:00Z")]}
            return {"data": []}

    plan, _, _ = discover_snapshots_for_day(
        C(),  # type: ignore[arg-type]
        "x",
        day,
        open_probe_offsets_hours=[48, 6],
        close_margin_hours=1.0,
    )
    assert plan.open_iso == t_6
    assert not plan.used_legacy_timestamps


def test_minutes_before_non_negative() -> None:
    ref = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
    snap = datetime(2024, 1, 1, 10, 30, tzinfo=timezone.utc)
    assert minutes_before_commence(ref, snap) == 90
    # snapshot после старта — 0
    assert minutes_before_commence(ref, datetime(2024, 1, 1, 13, 0, tzinfo=timezone.utc)) == 0


def test_stability_empty_and_malformed_payloads() -> None:
    d = date(2024, 5, 1)
    assert commence_datetimes_from_events_payload({}, d) == []
    assert commence_datetimes_from_events_payload({"data": None}, d) == []  # type: ignore[arg-type]
    assert commence_datetimes_from_events_payload({"data": "bad"}, d) == []
    assert commence_datetimes_from_events_payload({"data": [{"no_commence": True}]}, d) == []
    assert earliest_commence_on_day_from_payload({"data": []}, d) is None
    assert not has_events_for_calendar_day(123, d)  # type: ignore[arg-type]
    assert parse_commence_utc_from_event({}) is None
    assert parse_commence_utc_from_event({"commence_time": "not-a-date"}) is None
    # событие на другой день не считается
    p = {"data": [_ev("2024-05-02T12:00:00Z")]}
    assert commence_datetimes_from_events_payload(p, d) == []


def test_discover_uses_open_fallback_when_probes_empty_but_ref_from_seed() -> None:
    """ref из seed есть, все пробы пусты — open = legacy, close остаётся динамическим."""
    day = date(2024, 6, 1)
    ref_utc = datetime(2024, 6, 1, 18, 0, tzinfo=timezone.utc)
    seed = {"data": [_ev("2024-06-01T18:00:00Z")]}
    t_close = build_close_snapshot_iso(ref_utc, 1.0)
    t_probe = to_api_iso_z(ref_utc - timedelta(hours=12))

    class C:
        def fetch_odds_for_sport(
            self,
            _sport: str,
            *,
            date_iso: str | None = None,
            **_kwargs: object,
        ) -> object:
            if "T12:00:00" in (date_iso or ""):
                return seed
            if date_iso == t_close:
                return {"data": [_ev("2024-06-01T18:00:00Z")]}
            if date_iso == t_probe:
                return {"data": []}
            if date_iso == "2024-06-01T12:00:00Z":
                return {"data": [_ev("2024-06-01T18:00:00Z")]}
            return {"data": []}

    plan, _, _ = discover_snapshots_for_day(
        C(),  # type: ignore[arg-type]
        "x",
        day,
        open_probe_offsets_hours=[12.0],
        close_margin_hours=1.0,
    )
    assert plan.used_legacy_timestamps
    assert plan.open_iso == "2024-06-01T12:00:00Z"
    assert plan.close_iso == t_close
    assert plan.open_minutes_before == 6 * 60  # 12:00 -> 18:00


def test_unwrap_from_enrichment() -> None:
    assert unwrap_odds_payload({"data": [{"a": 1}]}) == [{"a": 1}]


def test_snapshot_discovery_params_empty_offsets_falls_back_to_default() -> None:
    """Пустой ``open_probe_offsets_hours`` в YAML → дефолтный tuple (R21.8 / tech-debt R21.5)."""
    from sports_forecast.data.providers.odds.backfill import _snapshot_discovery_params

    off, margin = _snapshot_discovery_params(
        {"snapshot_discovery": {"open_probe_offsets_hours": [], "close_margin_hours": 2.5}}
    )
    assert off == (168.0, 72.0, 24.0)
    assert margin == 2.5


def test_snapshot_discovery_params_non_numeric_close_margin_falls_back() -> None:
    from sports_forecast.data.providers.odds.backfill import _snapshot_discovery_params

    _off, margin = _snapshot_discovery_params({"snapshot_discovery": {"close_margin_hours": "bad"}})
    assert margin == 1.0
