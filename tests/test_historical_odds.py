from __future__ import annotations

import json
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest

from sports_forecast.data.providers.odds import historical
from sports_forecast.data.providers.odds.historical import (
    HistoricalOddsConflictError,
    import_historical_cache,
    list_imported_source_events,
    query_provider_as_of,
)
from sports_forecast.data.providers.odds.historical_coverage import build_coverage_report
from sports_forecast.identity import EntityRegistry
from sports_forecast.identity.snapshot import (
    RegistrySnapshotReader,
    export_registry_snapshot,
    verify_registry_snapshot,
)


def _reader(
    tmp_path: Path, *, source_event_id: str = "source-event-1"
) -> tuple[RegistrySnapshotReader, str, EntityRegistry]:
    registry = EntityRegistry(tmp_path / "master.sqlite3")
    registry.initialize()
    tournament = registry.create_entity("tournament", "NHL", sport="ice_hockey")
    home = registry.create_entity("team", "Boston Bruins", sport="ice_hockey")
    away = registry.create_entity("team", "Buffalo Sabres", sport="ice_hockey")
    event = registry.create_entity("event", "Boston Bruins v Buffalo Sabres", sport="ice_hockey")
    registry.set_event_relation(
        event.id,
        tournament_id=tournament.id,
        home_team_id=home.id,
        away_team_id=away.id,
        scheduled_at="2025-01-01T00:00:00Z",
        actor="owner",
        reason="Synthetic historical odds test fixture",
    )
    registry.add_designation(
        entity_id=tournament.id,
        source="the_odds_api",
        kind="tournament",
        scope={"sport": "ice_hockey"},
        value_kind="external_id",
        raw_value="icehockey_nhl",
        state="confirmed",
    )
    scope = {"sport": "ice_hockey", "tournament": tournament.id}
    for entity, raw, kind in (
        (home, "Boston Bruins", "team"),
        (away, "Buffalo Sabres", "team"),
        (event, source_event_id, "event"),
    ):
        registry.add_designation(
            entity_id=entity.id,
            source="the_odds_api",
            kind=kind,
            scope=scope,
            value_kind="external_id" if kind == "event" else "name",
            raw_value=raw,
            state="confirmed",
        )
    artifact = export_registry_snapshot(registry, tmp_path / "snapshots")
    return RegistrySnapshotReader(verify_registry_snapshot(artifact.path)), event.id, registry


def _cache(path: Path, timestamp: str, home_price: float, away_price: float) -> Path:
    payload = {
        "timestamp": timestamp,
        "previous_timestamp": None,
        "next_timestamp": None,
        "data": [
            {
                "id": "source-event-1",
                "sport_key": "icehockey_nhl",
                "commence_time": "2025-01-01T00:00:00Z",
                "home_team": "Boston Bruins",
                "away_team": "Buffalo Sabres",
                "bookmakers": [
                    {
                        "key": "pinnacle",
                        "last_update": timestamp,
                        "markets": [
                            {
                                "key": "h2h",
                                "last_update": timestamp,
                                "outcomes": [
                                    {"name": "Buffalo Sabres", "price": away_price},
                                    {"name": "Boston Bruins", "price": home_price},
                                ],
                            }
                        ],
                    }
                ],
            }
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_import_is_idempotent_and_query_selects_provider_snapshot(tmp_path: Path) -> None:
    database = tmp_path / "history.sqlite3"
    first = _cache(tmp_path / "first.json", "2025-01-01T00:00:00Z", 1.8, 2.1)
    reordered = _cache(tmp_path / "reordered.json", "2025-01-01T00:00:00Z", 1.8, 2.1)
    reordered_payload = json.loads(reordered.read_text(encoding="utf-8"))
    reordered_payload["data"][0]["bookmakers"][0]["markets"][0]["outcomes"].reverse()
    reordered.write_text(json.dumps(reordered_payload), encoding="utf-8")
    second = _cache(tmp_path / "second.json", "2025-01-01T00:30:00Z", 1.9, 2.0)
    second_payload = json.loads(second.read_text(encoding="utf-8"))
    second_payload["data"][0]["bookmakers"][0]["last_update"] = "2025-01-01T00:00:00Z"
    second_payload["data"][0]["bookmakers"][0]["markets"][0]["last_update"] = "2025-01-01T00:00:00Z"
    second.write_text(json.dumps(second_payload), encoding="utf-8")

    first_import = import_historical_cache((first, second, first, reordered), database)
    assert first_import.observations_inserted == 2
    assert first_import.observations_seen == 4

    reader, project_event_id, _ = _reader(tmp_path)
    between = query_provider_as_of(
        database,
        reader,
        project_event_id=project_event_id,
        at=datetime(2025, 1, 1, 0, 15, tzinfo=UTC),
    )
    after = query_provider_as_of(
        database,
        reader,
        project_event_id=project_event_id,
        at=datetime(2025, 1, 1, 1, 0, tzinfo=UTC),
    )
    before = query_provider_as_of(
        database,
        reader,
        project_event_id=project_event_id,
        at=datetime(2024, 12, 31, 23, 59, tzinfo=UTC),
    )

    assert between is not None and between.prices == {"home_win": "1.8", "away_win": "2.1"}
    assert after is not None and after.prices == {"home_win": "1.9", "away_win": "2"}
    assert before is None
    assert between.retrieved_at is None
    assert between.retrieval_status == "unknown"
    assert between.selection_mode == "provider_as_of"
    assert between.locally_known_at_t is False
    assert between.market_key == "winner_withOT"
    assert between.period == "full_game"
    assert between.includes_overtime is True
    assert between.includes_shootout is True
    assert between.source_file_sha256
    assert between.age_seconds == 900


def test_import_bounds_read_when_file_grows_after_descriptor_size_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "growing.json"
    content = b" " * 64
    source.write_bytes(content)
    monkeypatch.setattr(historical, "_MAX_FILE_BYTES", len(content))
    original_open = Path.open
    requested_reads: list[int] = []
    descriptor_sizes: list[int] = []
    original_fstat = os.fstat

    def recording_fstat(fd: int) -> os.stat_result:
        result = original_fstat(fd)
        descriptor_sizes.append(result.st_size)
        return result

    def growing_open(path: Path, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        opened = original_open(path, mode, *args, **kwargs)
        if path != source or mode != "rb":
            return opened

        class GrowingReader:
            def __enter__(self) -> GrowingReader:
                return self

            def __exit__(self, *_: object) -> None:
                opened.close()

            def fileno(self) -> int:
                return cast(int, opened.fileno())

            def read(self, size: int) -> bytes:
                requested_reads.append(size)
                with original_open(source, "ab") as append_handle:
                    append_handle.write(b"x")
                return cast(bytes, opened.read(size))

        return GrowingReader()

    monkeypatch.setattr(os, "fstat", recording_fstat)
    monkeypatch.setattr(Path, "open", growing_open)

    with pytest.raises(ValueError, match="обычным JSON-файлом допустимого размера"):
        import_historical_cache((source,), tmp_path / "history.sqlite3")

    assert descriptor_sizes == [len(content)]
    assert requested_reads == [len(content) + 1]


def test_query_rejects_timezone_naive_instant(tmp_path: Path) -> None:
    reader, project_event_id, _ = _reader(tmp_path)
    try:
        query_provider_as_of(
            tmp_path / "missing.sqlite3",
            reader,
            project_event_id=project_event_id,
            at=datetime(2025, 1, 1),
        )
    except ValueError as exc:
        assert "timezone" in str(exc).lower()
    else:
        raise AssertionError("timezone-naive T must be rejected")


def test_provider_as_of_exposes_late_retrieval_without_claiming_local_knowledge(
    tmp_path: Path,
) -> None:
    database = tmp_path / "history.sqlite3"
    source = _cache(tmp_path / "late.json", "2025-01-01T00:00:00Z", 1.8, 2.1)
    import_historical_cache((source,), database)
    import_historical_cache((source,), database, retrieved_at=datetime(2025, 1, 2, tzinfo=UTC))
    reader, project_event_id, _ = _reader(tmp_path)

    selected = query_provider_as_of(
        database,
        reader,
        project_event_id=project_event_id,
        at=datetime(2025, 1, 1, 12, tzinfo=UTC),
    )

    assert selected is not None
    assert selected.retrieval_status == "known"
    assert selected.late_retrieval is True
    assert selected.locally_known_at_t is False
    assert selected.receipt_id.startswith("hr1:")


@pytest.mark.parametrize("reverse_import_order", [False, True])
def test_conflicting_prices_at_one_provider_timestamp_are_not_selected(
    tmp_path: Path, reverse_import_order: bool
) -> None:
    database = tmp_path / "history.sqlite3"
    first = _cache(tmp_path / "first.json", "2025-01-01T00:00:00Z", 1.8, 2.1)
    conflicting = _cache(tmp_path / "conflicting.json", "2025-01-01T00:00:00Z", 1.81, 2.1)
    sources = (conflicting, first) if reverse_import_order else (first, conflicting)
    import_historical_cache(sources, database)
    reader, project_event_id, _ = _reader(tmp_path)

    with pytest.raises(HistoricalOddsConflictError):
        query_provider_as_of(
            database,
            reader,
            project_event_id=project_event_id,
            at=datetime(2025, 1, 1, 0, 1, tzinfo=UTC),
        )


def test_unconfirmed_source_event_does_not_return_project_price(tmp_path: Path) -> None:
    database = tmp_path / "history.sqlite3"
    source = _cache(tmp_path / "unmapped.json", "2025-01-01T00:00:00Z", 1.8, 2.1)
    import_historical_cache((source,), database)
    reader, project_event_id, _ = _reader(tmp_path, source_event_id="different-confirmed-id")

    selected = query_provider_as_of(
        database,
        reader,
        project_event_id=project_event_id,
        at=datetime(2025, 1, 1, 0, 1, tzinfo=UTC),
    )

    assert selected is None


def test_new_registry_mapping_resolves_old_observation_without_changing_old_snapshot(
    tmp_path: Path,
) -> None:
    database = tmp_path / "history.sqlite3"
    source = _cache(tmp_path / "late-mapping.json", "2025-01-01T00:00:00Z", 1.8, 2.1)
    import_historical_cache((source,), database)
    old_reader, project_event_id, registry = _reader(
        tmp_path, source_event_id="different-confirmed-id"
    )
    instant = datetime(2025, 1, 1, 0, 1, tzinfo=UTC)
    assert (
        query_provider_as_of(database, old_reader, project_event_id=project_event_id, at=instant)
        is None
    )
    with sqlite3.connect(database) as connection:
        prior_observation_id = connection.execute(
            "SELECT observation_id FROM historical_observations"
        ).fetchone()[0]

    tournament = registry.list_entities(kind="tournament")[0]
    registry.add_designation(
        entity_id=project_event_id,
        source="the_odds_api",
        kind="event",
        scope={"sport": "ice_hockey", "tournament": tournament.id},
        value_kind="external_id",
        raw_value="source-event-1",
        state="confirmed",
    )
    artifact = export_registry_snapshot(registry, tmp_path / "updated-snapshots")
    new_reader = RegistrySnapshotReader(verify_registry_snapshot(artifact.path))
    resolved = query_provider_as_of(
        database, new_reader, project_event_id=project_event_id, at=instant
    )

    assert resolved is not None
    assert resolved.observation_id == prior_observation_id
    assert resolved.project_event_id == project_event_id
    assert resolved.registry_snapshot_id == new_reader.snapshot_id
    assert (
        query_provider_as_of(database, old_reader, project_event_id=project_event_id, at=instant)
        is None
    )


def test_failed_file_transaction_keeps_no_partial_observations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "history.sqlite3"
    source = _cache(tmp_path / "transaction.json", "2025-01-01T00:00:00Z", 1.8, 2.1)
    payload = json.loads(source.read_text(encoding="utf-8"))
    second_event = json.loads(json.dumps(payload["data"][0]))
    second_event["id"] = "source-event-2"
    payload["data"].append(second_event)
    source.write_text(json.dumps(payload), encoding="utf-8")
    connect = historical._connect

    def connect_with_failure(path: Path) -> sqlite3.Connection:
        connection = connect(path)
        connection.execute(
            """CREATE TRIGGER fail_second_event BEFORE INSERT ON historical_observations
               WHEN NEW.source_event_id='source-event-2'
               BEGIN SELECT RAISE(ABORT, 'synthetic transaction failure'); END"""
        )
        return connection

    monkeypatch.setattr(historical, "_connect", connect_with_failure)
    with pytest.raises(sqlite3.IntegrityError, match="synthetic transaction failure"):
        import_historical_cache((source,), database)

    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT count(*) FROM historical_observations").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM historical_receipts").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM historical_cache_files").fetchone()[0] == 0


def test_import_keeps_nhl_source_event_without_target_market_for_coverage(
    tmp_path: Path,
) -> None:
    database = tmp_path / "history.sqlite3"
    source = _cache(tmp_path / "no-pinnacle.json", "2025-01-01T00:00:00Z", 1.8, 2.1)
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["data"][0]["bookmakers"][0]["key"] = "other_book"
    source.write_text(json.dumps(payload), encoding="utf-8")

    import_historical_cache((source,), database)
    records = list_imported_source_events(database)

    assert len(records) == 1
    assert records[0].source_event_id == "source-event-1"
    assert records[0].target_market_status == "no_pinnacle"
    assert records[0].commence_time == datetime(2025, 1, 1, tzinfo=UTC)


def test_coverage_counts_pinned_universe_and_reports_absent_line_separately(
    tmp_path: Path,
) -> None:
    reader, event_id, registry = _reader(tmp_path)
    tournament = registry.list_entities(kind="tournament")[0]
    home, away = registry.list_entities(kind="team")
    no_line_event = registry.create_entity(
        "event", "Boston Bruins v Buffalo Sabres without line", sport="ice_hockey"
    )
    registry.set_event_relation(
        no_line_event.id,
        tournament_id=tournament.id,
        home_team_id=home.id,
        away_team_id=away.id,
        scheduled_at="2025-01-02T00:00:00Z",
        actor="owner",
        reason="Проверка покрытия без линии",
    )
    registry.add_designation(
        entity_id=no_line_event.id,
        source="the_odds_api",
        kind="event",
        scope={"sport": "ice_hockey", "tournament": tournament.id},
        value_kind="external_id",
        raw_value="source-event-no-line",
        state="confirmed",
    )
    snapshot = export_registry_snapshot(registry, tmp_path / "updated-snapshots")
    reader = RegistrySnapshotReader(verify_registry_snapshot(snapshot.path))

    database = tmp_path / "history.sqlite3"
    covered = _cache(tmp_path / "covered.json", "2025-01-01T12:00:00Z", 1.8, 2.1)
    no_line = _cache(tmp_path / "no-line.json", "2025-01-01T12:00:00Z", 1.8, 2.1)
    payload = json.loads(no_line.read_text(encoding="utf-8"))
    payload["data"][0]["id"] = "source-event-no-line"
    payload["data"][0]["bookmakers"] = []
    no_line.write_text(json.dumps(payload), encoding="utf-8")
    import_historical_cache((covered, no_line), database)

    report = build_coverage_report(
        database,
        reader,
        start=datetime(2025, 1, 1, tzinfo=UTC),
        end=datetime(2025, 1, 3, tzinfo=UTC),
        at=datetime(2025, 1, 2, tzinfo=UTC),
    )

    assert report.expected_events == 2
    assert report.covered == 1
    assert report.no_line == 1
    assert report.no_snapshot == 0
    assert report.mapping_error == 0
    assert report.unmapped_source_events == 0
    assert report.imported_files == 2
    assert report.imported_file_fingerprint.startswith("sha256:")
    assert report.categories["no_line"][0]["subreason"] == "no_pinnacle"
    assert {item["project_event_id"] for item in report.categories["covered"]} == {event_id}


def test_coverage_zero_line_reports_no_snapshot_and_unmapped_source_event(
    tmp_path: Path,
) -> None:
    reader, event_id, _ = _reader(tmp_path)
    database = tmp_path / "empty-history.sqlite3"
    source = _cache(tmp_path / "unmapped.json", "2025-01-01T12:00:00Z", 1.8, 2.1)
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["data"][0]["id"] = "unknown-source-event"
    payload["data"][0]["home_team"] = "Unregistered Home Team"
    source.write_text(json.dumps(payload), encoding="utf-8")
    import_historical_cache((source,), database)

    report = build_coverage_report(
        database,
        reader,
        start=datetime(2025, 1, 1, tzinfo=UTC),
        end=datetime(2025, 1, 2, tzinfo=UTC),
        at=datetime(2025, 1, 2, tzinfo=UTC),
    )

    assert report.expected_events == 1
    assert report.covered == 0
    assert report.no_snapshot == 1
    assert report.no_line == report.mapping_error == 0
    assert report.categories["no_snapshot"][0] == {
        "project_event_id": event_id,
        "kickoff_utc": "2025-01-01T00:00:00.000000Z",
        "subreason": "no_source_evidence",
    }
    assert report.imported_files == 1
    assert report.unmapped_source_events == 1


def test_coverage_separates_invalid_mapping_from_missing_snapshot(tmp_path: Path) -> None:
    reader, event_id, _ = _reader(tmp_path)
    database = tmp_path / "history.sqlite3"
    source = _cache(tmp_path / "mis-mapped.json", "2025-01-01T12:00:00Z", 1.8, 2.1)
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["data"][0]["home_team"] = "Different Home Team"
    source.write_text(json.dumps(payload), encoding="utf-8")
    import_historical_cache((source,), database)

    report = build_coverage_report(
        database,
        reader,
        start=datetime(2025, 1, 1, tzinfo=UTC),
        end=datetime(2025, 1, 2, tzinfo=UTC),
        at=datetime(2025, 1, 2, tzinfo=UTC),
    )

    assert report.expected_events == 1
    assert report.mapping_error == 1
    assert report.categories["mapping_error"][0]["project_event_id"] == event_id
    assert report.no_snapshot == report.no_line == report.covered == 0


def test_coverage_reports_snapshot_after_t_as_no_snapshot(tmp_path: Path) -> None:
    reader, event_id, _ = _reader(tmp_path)
    database = tmp_path / "history.sqlite3"
    source = _cache(tmp_path / "after-t.json", "2025-01-01T00:02:00Z", 1.8, 2.1)
    import_historical_cache((source,), database)

    report = build_coverage_report(
        database,
        reader,
        start=datetime(2025, 1, 1, tzinfo=UTC),
        end=datetime(2025, 1, 2, tzinfo=UTC),
        at=datetime(2025, 1, 1, 0, 1, tzinfo=UTC),
    )

    assert report.no_snapshot == 1
    assert report.categories["no_snapshot"][0] == {
        "project_event_id": event_id,
        "kickoff_utc": "2025-01-01T00:00:00.000000Z",
        "subreason": "no_snapshot_at_or_before_T",
    }


def test_coverage_reports_invalid_snapshot_time_as_no_snapshot(tmp_path: Path) -> None:
    reader, event_id, _ = _reader(tmp_path)
    database = tmp_path / "history.sqlite3"
    source = _cache(tmp_path / "invalid-time.json", "2025-01-01T00:02:00Z", 1.8, 2.1)
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["timestamp"] = "not-a-timestamp"
    source.write_text(json.dumps(payload), encoding="utf-8")
    import_historical_cache((source,), database)

    report = build_coverage_report(
        database,
        reader,
        start=datetime(2025, 1, 1, tzinfo=UTC),
        end=datetime(2025, 1, 2, tzinfo=UTC),
        at=datetime(2025, 1, 1, 0, 3, tzinfo=UTC),
    )

    assert report.no_snapshot == 1
    assert report.mapping_error == 0
    assert report.categories["no_snapshot"][0]["project_event_id"] == event_id
    assert report.categories["no_snapshot"][0]["subreason"] == "invalid_envelope_timestamp"


def test_coverage_counts_import_diagnostics_and_timestamp_conflicts(tmp_path: Path) -> None:
    reader, event_id, _ = _reader(tmp_path)
    database = tmp_path / "history.sqlite3"
    first = _cache(tmp_path / "first.json", "2025-01-01T00:00:00Z", 1.8, 2.1)
    conflicting = _cache(tmp_path / "conflicting.json", "2025-01-01T00:00:00Z", 1.81, 2.1)
    invalid = _cache(tmp_path / "invalid.json", "2025-01-01T00:02:00Z", 1.8, 2.1)
    invalid_payload = json.loads(invalid.read_text(encoding="utf-8"))
    invalid_payload["data"][0]["bookmakers"][0]["markets"][0]["outcomes"].append(
        {"name": "Draw", "price": 10.0}
    )
    invalid.write_text(json.dumps(invalid_payload), encoding="utf-8")
    import_historical_cache((first, conflicting, invalid), database)

    report = build_coverage_report(
        database,
        reader,
        start=datetime(2025, 1, 1, tzinfo=UTC),
        end=datetime(2025, 1, 2, tzinfo=UTC),
        at=datetime(2025, 1, 1, 0, 1, tzinfo=UTC),
    )

    assert report.expected_events == 1
    assert report.conflicts == 1
    assert report.import_failures == 1
    assert report.import_diagnostics == {"invalid_h2h_outcomes": 1}
    assert report.mapping_error == 1
    assert report.covered + report.no_line + report.no_snapshot + report.mapping_error == 1
    assert report.categories["mapping_error"][0]["project_event_id"] == event_id
    assert report.imported_file_fingerprint.startswith("sha256:")


def test_import_rejects_draw_outcome_and_keeps_diagnostic(tmp_path: Path) -> None:
    database = tmp_path / "history.sqlite3"
    source = _cache(tmp_path / "draw.json", "2025-01-01T00:00:00Z", 1.8, 2.1)
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["data"][0]["bookmakers"][0]["markets"][0]["outcomes"].append(
        {"name": "Draw", "price": 10.0}
    )
    source.write_text(json.dumps(payload), encoding="utf-8")

    summary = import_historical_cache((source,), database)
    records = list_imported_source_events(database)

    assert summary.observations_inserted == 0
    assert records[0].target_market_status == "invalid_target_market"
    assert records[0].diagnostic_code == "invalid_h2h_outcomes"
