"""Контракты immutable initial bootstrap canonical NHL history."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from sports_forecast.deploy.canonical_bootstrap import (
    _event_from_nhl_row,
    build_nhl_bootstrap_bundle,
    import_nhl_bootstrap_bundle,
    refresh_nhl_canonical_from_csv,
    verify_nhl_bootstrap_bundle,
)
from sports_forecast.deploy.serving_data import ArchiveVerificationError
from sports_forecast.service.db.models import (
    Base,
    BootstrapImport,
    CalendarCoverage,
    CanonicalEvent,
    CanonicalEventRevision,
    RefreshWatermark,
)


def _write_nhl_source_csv(path: Path) -> None:
    path.write_text(
        "id,datetime,match_is_end,home_score_ft,away_score_ft,match_end,home_team,away_team\n"
        "202401,2024-01-01T20:00:00Z,1,3,2,REG,Home A,Away A\n"
        "202402,2024-01-02T20:00:00Z,0,,,,Home B,Away B\n",
        encoding="utf-8",
    )


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


@pytest.mark.parametrize(
    ("game_state", "schedule_state", "finished", "expected"),
    [
        ("FUT", "", "0", "scheduled"),
        ("FUT", "PPD", "0", "postponed"),
        ("FUT", "CANCELLED", "0", "cancelled"),
        ("MYSTERY", "", "0", "needs_review"),
        ("LIVE", "", "0", "started"),
        ("OFF", "", "1", "finished"),
    ],
)
def test_nhl_calendar_statuses_are_normalized(
    game_state: str, schedule_state: str, finished: str, expected: str
) -> None:
    """Provider statuses маппятся в общий набор canonical статусов."""
    event = _event_from_nhl_row(
        {
            "id": "fixture-1",
            "datetime": "2026-09-26T12:00:00Z",
            "match_is_end": finished,
            "game_state": game_state,
            "game_schedule_state": schedule_state,
        }
    )
    assert event["status"] == expected


def test_verified_nhl_bootstrap_imports_canonical_history_once(tmp_path: Path) -> None:
    """Повтор того же verified bundle не создаёт второй набор event/revision."""
    source_csv = tmp_path / "source.csv"
    _write_nhl_source_csv(source_csv)
    bundle = build_nhl_bootstrap_bundle(source_csv, tmp_path / "bundles")
    session = _session()
    try:
        first = import_nhl_bootstrap_bundle(bundle.path, session)
        second = import_nhl_bootstrap_bundle(bundle.path, session)

        assert first.imported is True
        assert first.events_count == 2
        assert second.imported is False
        assert second.events_count == 2
        assert session.scalars(select(CanonicalEvent)).all()
        assert len(session.scalars(select(CanonicalEventRevision)).all()) == 2
        assert len(session.scalars(select(BootstrapImport)).all()) == 1
        watermark = session.scalar(select(RefreshWatermark))
        assert watermark is not None
        assert watermark.tournament == "nhl"
        assert watermark.snapshot_id == bundle.artifact_id
    finally:
        session.close()


def test_verified_nhl_bootstrap_can_be_checked_without_database_write(tmp_path: Path) -> None:
    """Release gate валидирует fixture до import и без database connection."""
    source_csv = tmp_path / "source.csv"
    _write_nhl_source_csv(source_csv)
    bundle = build_nhl_bootstrap_bundle(source_csv, tmp_path / "bundles")

    assert verify_nhl_bootstrap_bundle(bundle.path).artifact_id == bundle.artifact_id


def test_tampered_bootstrap_bundle_does_not_write_partial_history(tmp_path: Path) -> None:
    """Checksum проверяется до первой DB-записи canonical history."""
    source_csv = tmp_path / "source.csv"
    _write_nhl_source_csv(source_csv)
    bundle = build_nhl_bootstrap_bundle(source_csv, tmp_path / "bundles")
    events_path = bundle.path / "canonical_events.jsonl"
    original = events_path.read_text(encoding="utf-8")
    events_path.write_text(original.replace("Home A", "Xome A", 1), encoding="utf-8")
    session = _session()
    try:
        with pytest.raises(ArchiveVerificationError, match="checksum"):
            import_nhl_bootstrap_bundle(bundle.path, session)

        assert session.scalars(select(CanonicalEvent)).all() == []
        assert session.scalars(select(BootstrapImport)).all() == []
    finally:
        session.close()


def test_refresh_csv_creates_new_revision_for_provider_correction(tmp_path: Path) -> None:
    """Incremental provider CSV меняет revision, не создавая второй canonical event."""
    source_csv = tmp_path / "source.csv"
    _write_nhl_source_csv(source_csv)
    bundle = build_nhl_bootstrap_bundle(source_csv, tmp_path / "bundles")
    session = _session()
    try:
        import_nhl_bootstrap_bundle(bundle.path, session)
        source_csv.write_text(
            "id,datetime,match_is_end,home_score_ft,away_score_ft,match_end,home_team,away_team\n"
            "202401,2024-01-01T20:00:00Z,1,4,2,REG,Home A,Away A\n",
            encoding="utf-8",
        )
        assert refresh_nhl_canonical_from_csv(source_csv, session) == 1
        assert len(session.scalars(select(CanonicalEvent)).all()) == 2
        assert len(session.scalars(select(CanonicalEventRevision)).all()) == 3
    finally:
        session.close()


def test_refresh_csv_updates_same_calendar_event_and_imports_coverage(tmp_path: Path) -> None:
    """Перенос меняет ту же event identity, добавляет revision и записывает coverage."""
    source_csv = tmp_path / "source.csv"
    source_csv.write_text(
        "id,datetime,match_is_end,game_state,home_team,away_team\n"
        "2026020001,2026-09-26T01:00:00Z,0,FUT,NYR,PIT\n"
        "2026020002,2026-09-26T04:00:00Z,0,FUT,BOS,NYI\n",
        encoding="utf-8",
    )
    (tmp_path / ".nhl_calendar_coverage.json").write_text(
        '{"version":1,"covered_from":"2026-09-25T00:00:00Z",'
        '"covered_until":"2026-10-27T00:00:00Z",'
        '"checked_at":"2026-09-25T12:00:00Z","complete":true}',
        encoding="utf-8",
    )
    session = _session()
    try:
        assert refresh_nhl_canonical_from_csv(source_csv, session) == 2
        source_csv.write_text(
            "id,datetime,match_is_end,game_state,home_team,away_team\n"
            "2026020001,2026-09-26T03:00:00Z,0,FUT,NYR,PIT\n",
            encoding="utf-8",
        )
        assert refresh_nhl_canonical_from_csv(source_csv, session) == 1

        events = session.scalars(select(CanonicalEvent)).all()
        assert len(events) == 2
        moved_event = next(event for event in events if event.source_event_id == "2026020001")
        omitted_event = next(event for event in events if event.source_event_id == "2026020002")
        assert moved_event.scheduled_at == datetime(2026, 9, 26, 3)
        assert moved_event.status == "scheduled"
        assert moved_event.home_participant == "NYR"
        assert omitted_event.scheduled_at == datetime(2026, 9, 26, 4)
        assert len(session.scalars(select(CanonicalEventRevision)).all()) == 3
        coverage = session.scalar(select(CalendarCoverage))
        assert coverage is not None
        assert coverage.complete is True
        assert coverage.covered_until == datetime(2026, 10, 27)
    finally:
        session.close()


def test_later_bootstrap_bundle_does_not_overwrite_current_calendar_projection(
    tmp_path: Path,
) -> None:
    """Повторный explicit bootstrap добавляет revision, сохраняя projection refresh."""
    initial_csv = tmp_path / "initial.csv"
    initial_csv.write_text(
        "id,datetime,match_is_end,game_state,home_team,away_team\n"
        "2026020001,2026-09-26T01:00:00Z,0,FUT,NYR,PIT\n",
        encoding="utf-8",
    )
    initial_bundle = build_nhl_bootstrap_bundle(initial_csv, tmp_path / "bundles")
    session = _session()
    try:
        import_nhl_bootstrap_bundle(initial_bundle.path, session)
        refreshed_csv = tmp_path / "refreshed.csv"
        refreshed_csv.write_text(
            "id,datetime,match_is_end,game_state,home_team,away_team\n"
            "2026020001,2026-09-26T03:00:00Z,0,FUT,NYR,PIT\n",
            encoding="utf-8",
        )
        refresh_nhl_canonical_from_csv(refreshed_csv, session)
        current_hash = session.scalar(select(CanonicalEvent)).current_revision_sha256

        stale_csv = tmp_path / "stale.csv"
        stale_csv.write_text(
            "id,datetime,match_is_end,game_state,home_team,away_team\n"
            "2026020001,2026-09-26T00:00:00Z,0,FUT,DET,WPG\n",
            encoding="utf-8",
        )
        stale_bundle = build_nhl_bootstrap_bundle(stale_csv, tmp_path / "bundles")
        import_nhl_bootstrap_bundle(stale_bundle.path, session)

        event = session.scalar(select(CanonicalEvent))
        assert event is not None
        assert event.scheduled_at == datetime(2026, 9, 26, 3)
        assert event.home_participant == "NYR"
        assert event.away_participant == "PIT"
        assert event.current_revision_sha256 == current_hash
        assert len(session.scalars(select(CanonicalEventRevision)).all()) == 3
    finally:
        session.close()


def test_empty_source_period_can_publish_confirmed_calendar_coverage(tmp_path: Path) -> None:
    """Пустой source snapshot принимается только при явном полном coverage manifest."""
    source_csv = tmp_path / "source.csv"
    source_csv.write_text("id,datetime,match_is_end\n", encoding="utf-8")
    (tmp_path / ".nhl_calendar_coverage.json").write_text(
        '{"version":1,"covered_from":"2026-09-25T00:00:00Z",'
        '"covered_until":"2026-10-27T00:00:00Z",'
        '"checked_at":"2026-09-25T12:00:00Z","complete":true}',
        encoding="utf-8",
    )
    session = _session()
    try:
        assert refresh_nhl_canonical_from_csv(source_csv, session) == 0
        assert session.scalars(select(CanonicalEvent)).all() == []
        coverage = session.scalar(select(CalendarCoverage))
        assert coverage is not None and coverage.complete is True
    finally:
        session.close()
