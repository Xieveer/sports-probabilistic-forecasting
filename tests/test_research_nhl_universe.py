"""Поведение подготовки закреплённого NHL universe для финансового исследования."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pandas as pd
import pytest

from sports_forecast.data.providers.odds.historical import import_historical_cache
from sports_forecast.identity import EntityRegistry
from sports_forecast.identity.events import EventIdentitySnapshot
from sports_forecast.research.nhl_universe import main, pin_nhl_universe


@pytest.fixture
def research_inputs(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    matches_path = tmp_path / "matches.parquet"
    pd.DataFrame(
        [
            {
                "id": "2023020001",
                "nhl_id": "2023020001",
                "datetime": "2023-10-10T23:00:00Z",
                "home_team": "BOS",
                "away_team": "NYR",
                "game_type": "regular",
            },
            {
                "id": "2023020002",
                "nhl_id": "2023020002",
                "datetime": "2023-10-11T23:00:00Z",
                "home_team": "NYR",
                "away_team": "BOS",
                "game_type": "playoffs",
            },
        ]
    ).to_parquet(matches_path, index=False)
    cache_path = tmp_path / "historical.json"
    cache_path.write_text(
        json.dumps(
            {
                "timestamp": "2023-10-10T22:00:00Z",
                "data": [
                    {
                        "id": "odds-event-1",
                        "sport_key": "icehockey_nhl",
                        "commence_time": "2023-10-10T23:00:00Z",
                        "home_team": "Boston Bruins",
                        "away_team": "New York Rangers",
                        "bookmakers": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    history_db = tmp_path / "history.sqlite3"
    import_historical_cache((cache_path,), history_db)
    seed_path = Path("conf/bookmaker/team_name_registry/nhl.yaml")
    return matches_path, history_db, seed_path, tmp_path / "research"


def test_pin_nhl_universe_is_idempotent_and_contains_matches_without_odds(
    research_inputs: tuple[Path, Path, Path, Path],
) -> None:
    matches, history, seed, output = research_inputs
    registry = EntityRegistry(output / "registry.sqlite3")
    registry.initialize()

    first = pin_nhl_universe(
        matches,
        history,
        registry,
        seed_path=seed,
        output_root=output,
        start="2023-10-01T00:00:00Z",
        end="2026-05-01T00:00:00Z",
    )
    second = pin_nhl_universe(
        matches,
        history,
        registry,
        seed_path=seed,
        output_root=output,
        start="2023-10-01T00:00:00Z",
        end="2026-05-01T00:00:00Z",
    )

    assert first.run_id == second.run_id
    assert first.snapshot_id == second.snapshot_id
    assert first.expected_events == 2
    assert first.raw_events_in_window == 2
    assert first.excluded_non_model_game_type == 0
    assert first.source_event_resolutions == {
        "resolved": 1,
        "unresolved": 0,
        "ambiguous": 0,
        "conflict": 0,
    }
    assert first.universe_by_month == {"2023-10": 2}
    assert registry.count_designations() == second.registry_designations
    snapshot = EventIdentitySnapshot.from_registry(registry)
    assert any(
        key.source == "the_odds_api" and key.source_event_id == "odds-event-1"
        for event in snapshot.events
        for key in event.source_keys
    )
    report = json.loads(first.report_path.read_text(encoding="utf-8"))
    assert report["source_fingerprints"]["matches_sha256"].startswith("sha256:")
    assert report["snapshot_id"] == first.snapshot_id
    assert "outcome" not in first.report_path.read_text(encoding="utf-8").casefold()


def test_pin_nhl_universe_reports_duplicate_source_ids_without_confirmation(
    research_inputs: tuple[Path, Path, Path, Path],
    tmp_path: Path,
) -> None:
    matches, history, seed, output = research_inputs
    duplicate_path = tmp_path / "duplicate.parquet"
    frame = pd.read_parquet(matches)
    frame.loc[1, "nhl_id"] = frame.loc[0, "nhl_id"]
    frame.to_parquet(duplicate_path, index=False)
    registry = EntityRegistry(output / "registry.sqlite3")
    registry.initialize()

    result = pin_nhl_universe(
        duplicate_path,
        history,
        registry,
        seed_path=seed,
        output_root=output,
        start="2023-10-01T00:00:00Z",
        end="2026-05-01T00:00:00Z",
    )
    assert registry.list_entities(kind="event") == []
    report = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert result.expected_events == 2
    assert result.unresolved_nhl_events == 2
    assert {row["reason"] for row in report["nhl_diagnostics"]} == {"duplicate_nhl_id"}


def test_pin_nhl_universe_keeps_reverse_duplicate_odds_refs_ambiguous(
    research_inputs: tuple[Path, Path, Path, Path],
    tmp_path: Path,
) -> None:
    matches, _history, seed, output = research_inputs
    cache_path = tmp_path / "duplicate-odds.json"
    event = {
        "sport_key": "icehockey_nhl",
        "commence_time": "2023-10-10T23:00:00Z",
        "home_team": "Boston Bruins",
        "away_team": "New York Rangers",
        "bookmakers": [],
    }
    cache_path.write_text(
        json.dumps(
            {
                "timestamp": "2023-10-10T22:00:00Z",
                "data": [
                    {"id": "odds-event-a", **event},
                    {"id": "odds-event-b", **event},
                ],
            }
        ),
        encoding="utf-8",
    )
    history = tmp_path / "history.sqlite3"
    import_historical_cache((cache_path,), history)
    registry = EntityRegistry(output / "registry.sqlite3")
    registry.initialize()

    result = pin_nhl_universe(
        matches,
        history,
        registry,
        seed_path=seed,
        output_root=output,
        start="2023-10-01T00:00:00Z",
        end="2026-05-01T00:00:00Z",
    )

    report = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert report["source_event_resolutions"]["ambiguous"] == 3
    assert {item["status"] for item in report["source_event_diagnostics"]} == {"ambiguous"}
    pinned = EventIdentitySnapshot.from_registry(registry)
    assert not any(
        key.source == "the_odds_api"
        for event_record in pinned.events
        for key in event_record.source_keys
    )


def test_pin_nhl_universe_rejects_pinned_odds_id_with_shifted_kickoff(
    research_inputs: tuple[Path, Path, Path, Path],
    tmp_path: Path,
) -> None:
    matches, history, seed, output = research_inputs
    registry = EntityRegistry(output / "registry.sqlite3")
    registry.initialize()
    first = pin_nhl_universe(
        matches,
        history,
        registry,
        seed_path=seed,
        output_root=output,
        start="2023-10-01T00:00:00Z",
        end="2026-05-01T00:00:00Z",
    )
    assert first.source_event_resolutions["resolved"] == 1
    designations_before_shift = registry.count_designations()

    shifted_cache = tmp_path / "shifted-historical.json"
    shifted_cache.write_text(
        json.dumps(
            {
                "timestamp": "2023-10-10T22:30:00Z",
                "data": [
                    {
                        "id": "odds-event-1",
                        "sport_key": "icehockey_nhl",
                        "commence_time": "2023-10-10T23:30:00Z",
                        "home_team": "Boston Bruins",
                        "away_team": "New York Rangers",
                        "bookmakers": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    shifted_history = tmp_path / "shifted-history.sqlite3"
    import_historical_cache((shifted_cache,), shifted_history)

    second = pin_nhl_universe(
        matches,
        shifted_history,
        registry,
        seed_path=seed,
        output_root=output,
        start="2023-10-01T00:00:00Z",
        end="2026-05-01T00:00:00Z",
    )

    report = json.loads(second.report_path.read_text(encoding="utf-8"))
    assert second.run_id != first.run_id
    assert second.source_event_resolutions["resolved"] == 0
    assert second.source_event_resolutions["conflict"] == 1
    assert registry.count_designations() == designations_before_shift
    assert report["confirmed_source_events"] == []
    assert report["source_event_diagnostics"][0]["reason"] == "pinned_source_kickoff_conflict"
    pinned = EventIdentitySnapshot.from_registry(registry)
    assert any(
        key.source == "the_odds_api" and key.source_event_id == "odds-event-1"
        for event_record in pinned.events
        for key in event_record.source_keys
    )


def test_pin_nhl_universe_rejects_registry_outside_research_output(
    research_inputs: tuple[Path, Path, Path, Path],
    tmp_path: Path,
) -> None:
    matches, history, seed, output = research_inputs
    registry = EntityRegistry(tmp_path / "production-like.sqlite3")
    registry.initialize()

    with pytest.raises(ValueError, match="отдельного output"):
        pin_nhl_universe(
            matches,
            history,
            registry,
            seed_path=seed,
            output_root=output,
            start="2023-10-01T00:00:00Z",
            end="2026-05-01T00:00:00Z",
        )


def test_cli_rejects_current_registry_path_before_database_initialization(
    research_inputs: tuple[Path, Path, Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    matches, history, seed, _output = research_inputs
    project_root = Path(__file__).resolve().parents[1]
    protected_output = project_root / "data" / "registry"
    protected_database = protected_output / "research-guard-test.sqlite3"
    assert not protected_database.exists()
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "nhl-universe",
            "--matches",
            str(matches),
            "--historical-database",
            str(history),
            "--registry-database",
            str(protected_database),
            "--team-seed",
            str(seed),
            "--output",
            str(protected_output),
            "--start",
            "2023-10-01T00:00:00Z",
            "--end",
            "2026-05-01T00:00:00Z",
        ],
    )

    with pytest.raises(ValueError, match="protected production"):
        main()

    assert not protected_database.exists()


@pytest.mark.parametrize("registry_alias_type", ["same_path", "symlink", "hardlink"])
def test_cli_rejects_registry_equal_to_historical_database_without_mutation(
    research_inputs: tuple[Path, Path, Path, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    registry_alias_type: str,
) -> None:
    matches, history, seed, output = research_inputs
    output.mkdir(parents=True, exist_ok=True)
    shared_database = output / "shared-history-registry.sqlite3"
    shared_database.write_bytes(history.read_bytes())
    original_bytes = shared_database.read_bytes()
    registry_database = output / "registry-alias.sqlite3"
    if registry_alias_type == "symlink":
        registry_database.symlink_to(shared_database)
    elif registry_alias_type == "hardlink":
        registry_database.hardlink_to(shared_database)
    else:
        registry_database = shared_database
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "nhl-universe",
            "--matches",
            str(matches),
            "--historical-database",
            str(shared_database),
            "--registry-database",
            str(registry_database),
            "--team-seed",
            str(seed),
            "--output",
            str(output),
            "--start",
            "2023-10-01T00:00:00Z",
            "--end",
            "2026-05-01T00:00:00Z",
        ],
    )

    with pytest.raises(ValueError, match="historical input"):
        main()

    assert shared_database.read_bytes() == original_bytes


def test_pin_nhl_universe_fingerprints_empty_imported_cache_files(
    research_inputs: tuple[Path, Path, Path, Path],
    tmp_path: Path,
) -> None:
    matches, _history, seed, output = research_inputs
    first_cache = tmp_path / "empty-first.json"
    first_cache.write_text('{"timestamp":"2023-10-10T22:00:00Z","data":[]}', encoding="utf-8")
    first_history = tmp_path / "empty-first.sqlite3"
    import_historical_cache((first_cache,), first_history)
    registry = EntityRegistry(output / "registry.sqlite3")
    registry.initialize()
    first = pin_nhl_universe(
        matches,
        first_history,
        registry,
        seed_path=seed,
        output_root=output,
        start="2023-10-01T00:00:00Z",
        end="2026-05-01T00:00:00Z",
    )

    changed_cache = tmp_path / "empty-changed.json"
    changed_cache.write_text('{"timestamp":"2023-10-10T22:00:00Z","data":[]}\n', encoding="utf-8")
    changed_history = tmp_path / "empty-changed.sqlite3"
    import_historical_cache((changed_cache,), changed_history)
    second = pin_nhl_universe(
        matches,
        changed_history,
        registry,
        seed_path=seed,
        output_root=output,
        start="2023-10-01T00:00:00Z",
        end="2026-05-01T00:00:00Z",
    )

    first_report = json.loads(first.report_path.read_text(encoding="utf-8"))
    second_report = json.loads(second.report_path.read_text(encoding="utf-8"))
    assert first.run_id != second.run_id
    assert (
        first_report["source_fingerprints"]["historical_files_sha256"]
        != second_report["source_fingerprints"]["historical_files_sha256"]
    )


def test_pin_nhl_universe_does_not_mutate_partial_historical_database_on_failure(
    research_inputs: tuple[Path, Path, Path, Path],
    tmp_path: Path,
) -> None:
    matches, _history, seed, output = research_inputs
    malformed = tmp_path / "partial-history.sqlite3"
    with sqlite3.connect(malformed) as connection:
        connection.execute("CREATE TABLE historical_source_events (file_sha256 TEXT)")
        connection.execute("INSERT INTO historical_source_events VALUES ('partial')")
    original_bytes = malformed.read_bytes()
    registry = EntityRegistry(output / "registry.sqlite3")
    registry.initialize()

    with pytest.raises((sqlite3.OperationalError, IndexError)):
        pin_nhl_universe(
            matches,
            malformed,
            registry,
            seed_path=seed,
            output_root=output,
            start="2023-10-01T00:00:00Z",
            end="2026-05-01T00:00:00Z",
        )

    assert malformed.read_bytes() == original_bytes


def test_pin_nhl_universe_excludes_non_model_game_types_before_expected_count(
    research_inputs: tuple[Path, Path, Path, Path],
    tmp_path: Path,
) -> None:
    matches, history, seed, output = research_inputs
    frame = pd.read_parquet(matches)
    frame.loc[1, "game_type"] = "preseason"
    changed_matches = tmp_path / "preseason.parquet"
    frame.to_parquet(changed_matches, index=False)
    registry = EntityRegistry(output / "registry.sqlite3")
    registry.initialize()

    result = pin_nhl_universe(
        changed_matches,
        history,
        registry,
        seed_path=seed,
        output_root=output,
        start="2023-10-01T00:00:00Z",
        end="2026-05-01T00:00:00Z",
    )

    report = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert result.raw_events_in_window == 2
    assert result.expected_events == 1
    assert result.excluded_non_model_game_type == 1
    assert report["non_model_game_type_diagnostics"][0]["game_type"] == "preseason"


def test_pin_nhl_universe_fingerprint_changes_when_window_changes(
    research_inputs: tuple[Path, Path, Path, Path],
) -> None:
    matches, history, seed, output = research_inputs
    registry = EntityRegistry(output / "registry.sqlite3")
    registry.initialize()

    first = pin_nhl_universe(
        matches,
        history,
        registry,
        seed_path=seed,
        output_root=output,
        start="2023-10-01T00:00:00Z",
        end="2026-05-01T00:00:00Z",
    )
    second = pin_nhl_universe(
        matches,
        history,
        registry,
        seed_path=seed,
        output_root=output,
        start="2023-10-11T00:00:00Z",
        end="2026-05-01T00:00:00Z",
    )

    assert first.run_id != second.run_id
    assert second.expected_events == 1
    first_manifest = json.loads(first.report_path.read_text(encoding="utf-8"))
    second_manifest = json.loads(second.report_path.read_text(encoding="utf-8"))
    assert first_manifest["window"] != second_manifest["window"]


def test_pin_nhl_universe_changes_run_id_when_source_fingerprint_changes(
    research_inputs: tuple[Path, Path, Path, Path],
    tmp_path: Path,
) -> None:
    matches, history, seed, output = research_inputs
    registry = EntityRegistry(output / "registry.sqlite3")
    registry.initialize()
    first = pin_nhl_universe(
        matches,
        history,
        registry,
        seed_path=seed,
        output_root=output,
        start="2023-10-01T00:00:00Z",
        end="2026-05-01T00:00:00Z",
    )
    frame = pd.read_parquet(matches)
    frame.loc[1, "game_type"] = " REGULAR "
    changed_matches = tmp_path / "changed-fingerprint.parquet"
    frame.to_parquet(changed_matches, index=False)

    second = pin_nhl_universe(
        changed_matches,
        history,
        registry,
        seed_path=seed,
        output_root=output,
        start="2023-10-01T00:00:00Z",
        end="2026-05-01T00:00:00Z",
    )

    assert first.input_fingerprint != second.input_fingerprint
    assert first.run_id != second.run_id


@pytest.mark.parametrize(
    ("field", "value", "expected_reason", "expected_events"),
    [
        ("home_team", "UNKNOWN", "unknown_or_conflicting_home_team", 2),
        ("datetime", None, "missing_kickoff", 1),
        ("nhl_id", "2023020001", "duplicate_nhl_id", 2),
    ],
)
def test_pin_nhl_universe_keeps_invalid_identity_rows_as_diagnostics(
    research_inputs: tuple[Path, Path, Path, Path],
    tmp_path: Path,
    field: str,
    value: str | None,
    expected_reason: str,
    expected_events: int,
) -> None:
    matches, history, seed, output = research_inputs
    frame = pd.read_parquet(matches)
    frame.loc[1, field] = value
    changed_matches = tmp_path / f"invalid-{field}.parquet"
    frame.to_parquet(changed_matches, index=False)
    registry = EntityRegistry(output / "registry.sqlite3")
    registry.initialize()

    result = pin_nhl_universe(
        changed_matches,
        history,
        registry,
        seed_path=seed,
        output_root=output,
        start="2023-10-01T00:00:00Z",
        end="2026-05-01T00:00:00Z",
    )

    report = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert result.expected_events == expected_events
    if expected_reason == "missing_kickoff":
        assert report["untimed_source_rows"] == 1
        assert any(item["reason"] == expected_reason for item in report["nhl_diagnostics"])
    else:
        assert any(item["reason"] == expected_reason for item in report["nhl_diagnostics"])
