"""Контракт закрепления provider-as-of цен для research набора."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from sports_forecast.data.providers.odds.historical import import_historical_cache
from sports_forecast.data.providers.odds.historical_coverage import classify_provider_coverage
from sports_forecast.identity import EntityRegistry
from sports_forecast.research.nhl_universe import pin_nhl_universe
from sports_forecast.research.provider_dataset import build_provider_dataset


def test_dataset_rejects_unverified_universe_before_creating_output(tmp_path: Path) -> None:
    universe = tmp_path / "universe.json"
    universe.write_text(json.dumps({"format": "unknown"}), encoding="utf-8")
    matches = tmp_path / "matches.parquet"
    matches.touch()
    seed = tmp_path / "seed.yaml"
    seed.touch()
    output = tmp_path / "out"
    with pytest.raises(ValueError, match="universe"):
        build_provider_dataset(
            universe_manifest_path=universe,
            historical_database_path=tmp_path / "history.sqlite3",
            snapshot_path=tmp_path / "snapshot",
            matches_path=matches,
            team_seed_path=seed,
            output_root=output,
        )
    assert not output.exists()


def test_shared_coverage_classifier_rejects_stale_and_conflicting_prices() -> None:
    assert classify_provider_coverage(
        has_selection=True,
        selection_age_seconds=86401,
        conflict=False,
        has_source=True,
        mapping_valid=True,
        statuses={"valid"},
        diagnostics=set(),
        max_age_seconds=86400,
    ) == ("stale_price", "snapshot_older_than_limit")
    assert classify_provider_coverage(
        has_selection=False,
        conflict=True,
        has_source=True,
        mapping_valid=True,
        statuses={"valid"},
        diagnostics=set(),
        max_age_seconds=86400,
    ) == ("conflict", "conflicting_snapshot")


def test_dataset_is_repeatable_and_keeps_expected_events_without_a_line(
    tmp_path: Path,
) -> None:
    matches = tmp_path / "matches.parquet"
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
                "home_team": "UNKNOWN TEAM",
                "away_team": "NYR",
                "game_type": "regular",
            },
        ]
    ).to_parquet(matches, index=False)
    cache = tmp_path / "history.json"
    cache.write_text(
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
    history = tmp_path / "history.sqlite3"
    import_historical_cache((cache,), history)
    seed = Path("conf/bookmaker/team_name_registry/nhl.yaml")
    output = tmp_path / "research"
    registry_path = output / "registry.sqlite3"
    registry = EntityRegistry(registry_path)
    registry.initialize()
    pinned = pin_nhl_universe(
        matches,
        history,
        registry,
        seed_path=seed,
        output_root=output,
        start="2023-10-01T00:00:00Z",
        end="2026-05-01T00:00:00Z",
    )
    run_dir = output / "runs" / pinned.run_id
    snapshot = output / "snapshots" / pinned.snapshot_id.split(":", 1)[1]
    kwargs: dict[str, Any] = {
        "universe_manifest_path": run_dir / "manifest.json",
        "historical_database_path": history,
        "snapshot_path": snapshot,
        "matches_path": matches,
        "team_seed_path": seed,
        "output_root": output / "datasets",
    }
    first = build_provider_dataset(**kwargs)
    second = build_provider_dataset(**kwargs)
    manifest = json.loads(first.read_text(encoding="utf-8"))
    events = [
        json.loads(line)
        for line in first.with_name("events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert first == second
    assert manifest["expected_events"] == 2
    assert len(events) == 2
    assert sum(manifest["coverage"].values()) == 2
    assert manifest["coverage"] == {"mapping_error": 1, "no_line": 1}
    unresolved = next(event for event in events if event["source_event_id"] == "2023020002")
    assert unresolved["project_event_id"] is None
    assert unresolved["kickoff_utc"] == "2023-10-11T23:00:00.000000Z"
    assert unresolved["decision_at"] == "2023-10-11T22:45:00.000000Z"
    assert unresolved["coverage"] == "mapping_error"
    assert "outcome" not in first.with_name("events.jsonl").read_text(encoding="utf-8").casefold()

    original_universe_bytes = kwargs["universe_manifest_path"].read_bytes()
    tampered = json.loads(original_universe_bytes)
    tampered["nhl_events"] = []
    tampered["expected_events"] = 1
    kwargs["universe_manifest_path"].write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(ValueError, match="Expected event count"):
        build_provider_dataset(**kwargs)
    kwargs["universe_manifest_path"].write_bytes(original_universe_bytes)
    tampered_id = json.loads(original_universe_bytes)
    tampered_id["run_id"] = "0" * 64
    kwargs["universe_manifest_path"].write_text(json.dumps(tampered_id), encoding="utf-8")
    with pytest.raises(ValueError, match="run_id universe"):
        build_provider_dataset(**kwargs)
    kwargs["universe_manifest_path"].write_bytes(original_universe_bytes)
    tampered_status = json.loads(original_universe_bytes)
    tampered_status["nhl_events"][0]["status"] = "unresolved"
    kwargs["universe_manifest_path"].write_text(json.dumps(tampered_status), encoding="utf-8")
    with pytest.raises(ValueError, match="nhl_events должен содержать только resolved"):
        build_provider_dataset(**kwargs)
    kwargs["universe_manifest_path"].write_bytes(original_universe_bytes)
    tampered_links = json.loads(original_universe_bytes)
    tampered_links["confirmed_source_events"] = []
    kwargs["universe_manifest_path"].write_text(json.dumps(tampered_links), encoding="utf-8")
    with pytest.raises(ValueError, match="source links universe не совпадают"):
        build_provider_dataset(**kwargs)
    kwargs["universe_manifest_path"].write_bytes(original_universe_bytes)
    tampered_partition = json.loads(original_universe_bytes)
    moved = tampered_partition["nhl_events"].pop(0)
    tampered_partition["nhl_diagnostics"].append(
        {
            "row_id": moved["row_id"],
            "source_event_id": moved["source_event_id"],
            "kickoff_utc": moved["kickoff_utc"],
            "project_event_id": None,
            "status": "unresolved",
            "reason": "tampered transfer",
        }
    )
    kwargs["universe_manifest_path"].write_text(json.dumps(tampered_partition), encoding="utf-8")
    with pytest.raises(ValueError, match="partition не совпадает"):
        build_provider_dataset(**kwargs)
