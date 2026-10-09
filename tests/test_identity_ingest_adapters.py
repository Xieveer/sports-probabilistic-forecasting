"""Документированные NHL и Smart Tables identity adapters работают offline."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
import yaml

from sports_forecast.identity import EntityRegistry
from sports_forecast.identity.ingest import resolve_source_frame
from sports_forecast.identity.review_service import ReviewQueueService
from sports_forecast.identity.snapshot import export_registry_snapshot, verify_registry_snapshot


@pytest.mark.parametrize(
    ("tournament_name", "source", "sport", "tournament_raw", "row_id", "event_id"),
    [
        ("nhl", "nhl_api", "ice_hockey", "NHL", "id", "nhl_id"),
        (
            "football_nationals",
            "smart_tables",
            "football",
            "WC",
            "match_id",
            "match_id",
        ),
    ],
)
def test_documented_source_adapter_resolves_and_unknown_event_becomes_candidate(
    tmp_path: Path,
    tournament_name: str,
    source: str,
    sport: str,
    tournament_raw: str,
    row_id: str,
    event_id: str,
) -> None:
    registry = EntityRegistry(tmp_path / "master.sqlite3")
    registry.initialize()
    tournament = registry.create_entity("tournament", "Project tournament", sport=sport)
    home = registry.create_entity("team", "Project home", sport=sport)
    away = registry.create_entity("team", "Project away", sport=sport)
    event = registry.create_entity("event", "Project event", sport=sport)
    scope = {"sport": sport, "tournament": tournament.id}
    registry.add_designation(
        entity_id=tournament.id,
        source=source,
        kind="tournament",
        scope={"sport": sport},
        value_kind="name",
        raw_value=tournament_raw,
        state="confirmed",
    )
    for entity, kind, raw, value_kind in (
        (home, "team", "HOME", "external_id"),
        (away, "team", "AWAY", "external_id"),
        (event, "event", "event-1", "external_id"),
    ):
        registry.add_designation(
            entity_id=entity.id,
            source=source,
            kind=kind,
            scope=scope,
            value_kind=value_kind,
            raw_value=raw,
            state="confirmed",
        )
    registry.set_event_relation(
        event.id,
        tournament_id=tournament.id,
        home_team_id=home.id,
        away_team_id=away.id,
        scheduled_at="2026-10-04T17:00:00Z",
        actor="owner",
        reason="Adapter integration fixture",
    )
    package = export_registry_snapshot(registry, tmp_path / "snapshots")
    snapshot = verify_registry_snapshot(package.path)
    adapter = {
        "source": source,
        "sport": sport,
        "row_id": row_id,
        "event_id": event_id,
        "scheduled_at": "scheduled_at",
        "home_id": "home_id",
        "away_id": "away_id",
        "tournament": "tournament_raw",
    }
    config_path = tmp_path / "identity.yaml"
    config_path.write_text(
        yaml.safe_dump({"adapters": {tournament_name: adapter}}), encoding="utf-8"
    )
    frame = pd.DataFrame(
        [
            {
                row_id: "row-1",
                event_id: "event-1",
                "scheduled_at": "2026-10-04T17:00:00Z",
                "home_id": "HOME",
                "away_id": "AWAY",
                "tournament_raw": tournament_raw,
            }
        ]
    )

    _name, _source, _row_key, resolved = resolve_source_frame(
        frame,
        tournament_name=tournament_name,
        source_config_path=config_path,
        snapshot=snapshot,
        master_registry=registry,
    )
    assert resolved[0].status == "resolved"
    assert resolved[0].project_event_id == event.id

    frame.loc[0, "tournament_raw"] = "unreviewed-tournament"
    _name, _source, _row_key, unresolved = resolve_source_frame(
        frame,
        tournament_name=tournament_name,
        source_config_path=config_path,
        snapshot=snapshot,
        master_registry=registry,
    )
    assert unresolved[0].status == "unresolved"
    candidates = ReviewQueueService(registry).list_candidates(source=source, limit=20)
    assert len(candidates) == 1
    assert candidates[0].raw_value == "unreviewed-tournament"


def test_batch_adapter_marks_duplicate_source_ids_for_same_event_ambiguous(
    tmp_path: Path,
) -> None:
    registry = EntityRegistry(tmp_path / "master.sqlite3")
    registry.initialize()
    tournament = registry.create_entity("tournament", "League", sport="football")
    home = registry.create_entity("team", "Home", sport="football")
    away = registry.create_entity("team", "Away", sport="football")
    event = registry.create_entity("event", "Match", sport="football")
    scope = {"sport": "football", "tournament": tournament.id}
    for entity, kind, raw in (
        (tournament, "tournament", "WC"),
        (home, "team", "H"),
        (away, "team", "A"),
    ):
        registry.add_designation(
            entity_id=entity.id,
            source="feed",
            kind=kind,
            scope={"sport": "football"} if kind == "tournament" else scope,
            value_kind="external_id" if kind == "team" else "name",
            raw_value=raw,
            state="confirmed",
        )
    registry.set_event_relation(
        event.id,
        tournament_id=tournament.id,
        home_team_id=home.id,
        away_team_id=away.id,
        scheduled_at="2026-10-04T17:00:00Z",
        actor="owner",
        reason="Batch uniqueness fixture",
    )
    snapshot = verify_registry_snapshot(
        export_registry_snapshot(registry, tmp_path / "snapshots").path
    )
    config_path = tmp_path / "identity.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "adapters": {
                    "demo": {
                        "source": "feed",
                        "sport": "football",
                        "row_id": "id",
                        "event_id": "event_id",
                        "scheduled_at": "scheduled_at",
                        "tournament_value": "WC",
                        "home_id": "home",
                        "away_id": "away",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    frame = pd.DataFrame(
        [
            {
                "id": "r1",
                "event_id": "source-1",
                "scheduled_at": "2026-10-04T17:00:00Z",
                "home": "H",
                "away": "A",
            },
            {
                "id": "r2",
                "event_id": "source-2",
                "scheduled_at": "2026-10-04T17:00:00Z",
                "home": "H",
                "away": "A",
            },
        ]
    )

    _name, _source, _row_key, resolutions = resolve_source_frame(
        frame,
        tournament_name="demo",
        source_config_path=config_path,
        snapshot=snapshot,
    )

    assert [item.status for item in resolutions] == ["ambiguous", "ambiguous"]
    assert all(item.project_event_id is None for item in resolutions)
