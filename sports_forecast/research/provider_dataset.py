"""Сборка детерминированного набора Pinnacle цен на event-specific T."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sports_forecast.data.providers.odds.historical import _utc, query_provider_as_of_many
from sports_forecast.data.providers.odds.historical_coverage import classify_provider_coverage
from sports_forecast.identity.snapshot import RegistrySnapshotReader, verify_registry_snapshot
from sports_forecast.research.nhl_universe import _POLICY_VERSION, _read_matches, _sha256
from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)
_FORMAT = "sports-forecast-provider-asof-dataset"


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _selection_payload(selection: Any) -> dict[str, Any]:
    """Сериализовать provenance с явными provider и decision timestamps."""
    return {
        "observation_id": selection.observation_id,
        "ho1": selection.observation_id,
        "ir1": selection.registry_snapshot_id,
        "source_event_id": selection.source_event_id,
        "receipt_id": selection.receipt_id or None,
        "source_file_sha256": selection.source_file_sha256 or None,
        "bookmaker": selection.bookmaker,
        "market_key": selection.market_key,
        "period": selection.period,
        "includes_overtime": selection.includes_overtime,
        "includes_shootout": selection.includes_shootout,
        "market_rules_version": selection.market_rules_version,
        "prices": selection.prices,
        "observed_at": _iso(selection.observed_at),
        "age_seconds": selection.age_seconds,
        "retrieved_at": _iso(selection.retrieved_at) if selection.retrieved_at else None,
        "retrieval_status": selection.retrieval_status,
        "late_retrieval": selection.late_retrieval,
    }


def _historical_fingerprint(path: Path) -> str:
    uri = f"{path.resolve().as_uri()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as db:
        hashes = [
            row[0]
            for row in db.execute(
                "SELECT file_sha256 FROM historical_cache_files ORDER BY file_sha256"
            )
        ]
    return "sha256:" + hashlib.sha256("\n".join(hashes).encode()).hexdigest()


def _expected_nhl_partition(
    raw_rows: list[dict[str, Any]],
    registry: RegistrySnapshotReader,
) -> list[tuple[tuple[str, str, str], str | None]]:
    """Независимо определить resolved/unresolved partition из parquet и ir1."""
    nhl_events = []
    tournament_ids: set[str] = set()
    for event in registry.snapshot.event_snapshot.events:
        if event.sport != "ice_hockey":
            continue
        try:
            tournament = registry.get_entity(event.tournament_id)
        except KeyError:
            continue
        if tournament.project_name.casefold() == "nhl":
            nhl_events.append(event)
            tournament_ids.add(event.tournament_id)
    if len(tournament_ids) > 1:
        raise ValueError("Pinned ir1 содержит несколько NHL tournament UUID")
    tournament_id = next(iter(tournament_ids), None)
    id_counts: dict[str, int] = defaultdict(int)
    exact_counts: dict[tuple[datetime, str, str], int] = defaultdict(int)
    for row in raw_rows:
        if row["nhl_id"]:
            id_counts[row["nhl_id"]] += 1
        exact_counts[(row["kickoff"], row["home"], row["away"])] += 1

    partition: list[tuple[tuple[str, str, str], str | None]] = []
    for row in raw_rows:
        identity = (row["row_id"], row["nhl_id"], _iso(row["kickoff"]))
        resolved_id: str | None = None
        if (
            tournament_id
            and row["nhl_id"]
            and id_counts[row["nhl_id"]] == 1
            and exact_counts[(row["kickoff"], row["home"], row["away"])] == 1
            and row["home"]
            and row["away"]
        ):
            scope = {"sport": "ice_hockey", "tournament": tournament_id}
            home = registry.resolve_designation(
                source="nhl_api",
                kind="team",
                scope=scope,
                value_kind="external_id",
                raw_value=row["home"],
                at=_iso(row["kickoff"]),
            )
            away = registry.resolve_designation(
                source="nhl_api",
                kind="team",
                scope=scope,
                value_kind="external_id",
                raw_value=row["away"],
                at=_iso(row["kickoff"]),
            )
            if home.status == away.status == "resolved" and home.entity_id != away.entity_id:
                candidates = [
                    event
                    for event in nhl_events
                    if _utc(event.scheduled_at, field="pinned scheduled_at") == row["kickoff"]
                    and event.home_team_id == home.entity_id
                    and event.away_team_id == away.entity_id
                    and any(
                        key.source == "nhl_api" and key.source_event_id == row["nhl_id"]
                        for key in event.source_keys
                    )
                ]
                if len(candidates) == 1:
                    resolved_id = candidates[0].id
        partition.append((identity, resolved_id))
    return partition


def build_provider_dataset(
    *,
    universe_manifest_path: Path,
    historical_database_path: Path,
    snapshot_path: Path,
    matches_path: Path,
    team_seed_path: Path,
    output_root: Path,
    start: str | datetime | None = None,
    end: str | datetime | None = None,
) -> Path:
    """Проверить закреплённые входы и записать provider-as-of набор без исходов."""
    universe_path, history_path, snapshot_dir = map(
        Path, (universe_manifest_path, historical_database_path, snapshot_path)
    )
    matches_input, seed_input = Path(matches_path), Path(team_seed_path)
    if (
        not universe_path.is_file()
        or not history_path.is_file()
        or not matches_input.is_file()
        or not seed_input.is_file()
    ):
        raise ValueError(
            "universe manifest, historical database, NHL parquet и team seed должны существовать"
        )
    universe = json.loads(universe_path.read_text(encoding="utf-8"))
    if (
        universe.get("format") != "sports-forecast-pinned-nhl-universe"
        or universe.get("format_version") != 1
    ):
        raise ValueError("Недопустимый формат pinned NHL universe")
    expected_fp = universe.get("source_fingerprints", {}).get("historical_files_sha256")
    actual_fp = _historical_fingerprint(history_path)
    if expected_fp != actual_fp:
        raise ValueError("Fingerprint historical inputs не совпадает с universe")
    source_fingerprints = universe.get("source_fingerprints", {})
    if source_fingerprints.get("matches_sha256") != _sha256(matches_input):
        raise ValueError("Fingerprint NHL matches не совпадает с universe")
    if source_fingerprints.get("team_seed_sha256") != _sha256(seed_input):
        raise ValueError("Fingerprint NHL team seed не совпадает с universe")
    window = universe.get("window", {})
    universe_start = _utc(window.get("start_utc"), field="universe start")
    universe_end = _utc(window.get("end_utc_exclusive"), field="universe end")
    if universe_start is None or universe_end is None or universe_start >= universe_end:
        raise ValueError("Pinned universe содержит некорректное окно")
    raw_rows, raw_untimed, raw_excluded = _read_matches(matches_input, universe_start, universe_end)
    if len(raw_rows) != int(universe.get("expected_events", -1)):
        raise ValueError("Expected event count не соответствует NHL parquet")
    if len(raw_excluded) != int(universe.get("excluded_non_model_game_type", -1)):
        raise ValueError("Game type exclusions не соответствуют NHL parquet")
    if len(raw_untimed) != int(universe.get("untimed_source_rows", -1)):
        raise ValueError("Untimed NHL diagnostics не соответствуют source parquet")
    if len(raw_rows) + len(raw_excluded) != int(universe.get("raw_events_in_window", -1)):
        raise ValueError("Raw in-window event count не соответствует NHL parquet")
    verified = verify_registry_snapshot(snapshot_dir)
    if verified.snapshot_id != universe.get("snapshot_id"):
        raise ValueError("Pinned ir1 не совпадает с universe")
    registry = RegistrySnapshotReader(verified)
    expected_partition = _expected_nhl_partition(raw_rows, registry)
    resolved_rows = list(universe.get("nhl_events", []))
    if any(
        row.get("status") != "resolved" or not row.get("project_event_id") for row in resolved_rows
    ):
        raise ValueError("nhl_events должен содержать только resolved строки с project UUID")
    timed_diagnostics = [
        row
        for row in universe.get("nhl_diagnostics", [])
        if row.get("kickoff_utc") is not None
        and universe_start <= _utc(row["kickoff_utc"], field="diagnostic kickoff") < universe_end
    ]
    if any(
        row.get("status") not in {"unresolved", "conflict"}
        or row.get("project_event_id") is not None
        for row in timed_diagnostics
    ):
        raise ValueError("Timed diagnostics должны быть non-resolved rows без project UUID")
    if len(resolved_rows) + len(timed_diagnostics) != int(universe.get("expected_events", -1)):
        raise ValueError("resolved NHL events + timed diagnostics не совпадают с expected_events")
    reported_keys = [
        (
            str(row.get("row_id") or ""),
            str(row.get("source_event_id") or ""),
            row.get("kickoff_utc"),
        )
        for row in [*resolved_rows, *timed_diagnostics]
    ]
    raw_keys = [(row["row_id"], row["nhl_id"], _iso(row["kickoff"])) for row in raw_rows]
    if sorted(reported_keys) != sorted(raw_keys):
        raise ValueError("Resolved events/diagnostics не покрывают source rows NHL parquet")
    reported_partition = [
        (
            (
                str(row.get("row_id") or ""),
                str(row.get("source_event_id") or ""),
                row["kickoff_utc"],
            ),
            row.get("project_event_id"),
        )
        for row in resolved_rows
    ] + [
        (
            (
                str(row.get("row_id") or ""),
                str(row.get("source_event_id") or ""),
                row["kickoff_utc"],
            ),
            None,
        )
        for row in timed_diagnostics
    ]
    if sorted(reported_partition) != sorted(expected_partition):
        raise ValueError("Resolved/unresolved partition не совпадает с raw rows и pinned ir1")
    matches = sorted(
        [*resolved_rows, *timed_diagnostics],
        key=lambda row: (
            row["kickoff_utc"],
            row.get("project_event_id") or "",
            row.get("row_id") or "",
        ),
    )
    run_identity = {
        "policy_version": universe.get("policy_version"),
        "window": window,
        "matches_sha256": source_fingerprints.get("matches_sha256"),
        "historical_files_sha256": expected_fp,
        "team_seed_sha256": source_fingerprints.get("team_seed_sha256"),
    }
    if universe.get("policy_version") != _POLICY_VERSION:
        raise ValueError("Неизвестная версия политики NHL universe")
    calculated_run_id = hashlib.sha256(_canonical(run_identity)).hexdigest()
    if calculated_run_id != universe.get("run_id"):
        raise ValueError("run_id universe не соответствует входным fingerprints/window/policy")
    pinned_events = {event.id: event for event in registry.snapshot.event_snapshot.events}
    nhl_source_links = {
        (key.source_event_id, event.id)
        for event in registry.snapshot.event_snapshot.events
        for key in event.source_keys
        if key.source == "nhl_api" and key.sport == "ice_hockey"
    }
    raw_by_identity = {
        (row["row_id"], row["nhl_id"], _iso(row["kickoff"])): row for row in raw_rows
    }
    seen_event_ids: set[str] = set()
    for row in matches:
        event_id = row.get("project_event_id")
        if not event_id:
            continue
        if event_id in seen_event_ids or event_id not in pinned_events:
            raise ValueError("NHL universe содержит отсутствующий или повторный project event UUID")
        seen_event_ids.add(event_id)
        identity = (
            str(row.get("row_id") or ""),
            str(row.get("source_event_id") or ""),
            row["kickoff_utc"],
        )
        raw = raw_by_identity.get(identity)
        if raw is None or (str(raw["nhl_id"]), event_id) not in nhl_source_links:
            raise ValueError("Project event UUID не подтверждён исходным NHL source key")
        pinned_kickoff = _utc(pinned_events[event_id].scheduled_at, field="pinned scheduled_at")
        if pinned_kickoff is None or _iso(pinned_kickoff) != row["kickoff_utc"]:
            raise ValueError("Kickoff NHL universe не совпадает с закреплённым ir1")
        event = pinned_events[event_id]
        tournament_scope = {"sport": "ice_hockey", "tournament": event.tournament_id}
        home = registry.resolve_designation(
            source="nhl_api",
            kind="team",
            scope=tournament_scope,
            value_kind="external_id",
            raw_value=raw["home"],
            at=row["kickoff_utc"],
        )
        away = registry.resolve_designation(
            source="nhl_api",
            kind="team",
            scope=tournament_scope,
            value_kind="external_id",
            raw_value=raw["away"],
            at=row["kickoff_utc"],
        )
        if (
            home.status != "resolved"
            or away.status != "resolved"
            or home.entity_id != event.home_team_id
            or away.entity_id != event.away_team_id
        ):
            raise ValueError("Project event teams не соответствуют source строке и pinned ir1")
    if (start is None) != (end is None):
        raise ValueError("Для окна dataset укажите обе границы start и end")
    universe_window = universe["window"]
    lower = (
        _utc(start, field="start")
        if start is not None
        else _utc(universe_window["start_utc"], field="start")
    )
    upper = (
        _utc(end, field="end")
        if end is not None
        else _utc(universe_window["end_utc_exclusive"], field="end")
    )
    if lower is None or upper is None or lower >= upper:
        raise ValueError("Окно dataset должно быть непустым и иметь start < end")
    universe_lower = _utc(universe_window["start_utc"], field="universe start")
    universe_upper = _utc(universe_window["end_utc_exclusive"], field="universe end")
    if lower < universe_lower or upper > universe_upper:
        raise ValueError("Окно dataset должно находиться внутри закреплённого NHL universe")
    matches = [row for row in matches if lower <= _utc(row["kickoff_utc"], field="kickoff") < upper]
    events = [
        row for row in matches if row.get("status") == "resolved" and row.get("project_event_id")
    ]
    instants = {
        row["project_event_id"]: _utc(row["kickoff_utc"], field="kickoff") - timedelta(minutes=15)
        for row in events
    }
    confirmed_rows = universe.get("confirmed_source_events", [])
    event_by_source_id: dict[str, str] = {}
    source_by_event_id: dict[str, str] = {}
    claimed_events: set[str] = set()
    registry_keys = {
        (key.source, key.source_event_id, event.id)
        for event in registry.snapshot.event_snapshot.events
        for key in event.source_keys
    }
    for row in confirmed_rows:
        source_id, event_id = str(row["source_event_id"]), str(row["project_event_id"])
        if source_id in event_by_source_id or event_id in claimed_events:
            raise ValueError("Pinned universe содержит неуникальные подтверждённые event links")
        if ("the_odds_api", source_id, event_id) not in registry_keys:
            raise ValueError("Pinned source link отсутствует в подтверждённом ir1")
        event_by_source_id[source_id] = event_id
        source_by_event_id[event_id] = source_id
        claimed_events.add(event_id)
    snapshot_links = {
        (event.id, key.source_event_id)
        for event in registry.snapshot.event_snapshot.events
        if event.id in seen_event_ids
        for key in event.source_keys
        if key.source == "the_odds_api" and key.sport == "ice_hockey"
    }
    if snapshot_links != {
        (event_id, source_id) for source_id, event_id in event_by_source_id.items()
    }:
        raise ValueError("Confirmed source links universe не совпадают с закреплённым ir1")
    selected, conflicts = query_provider_as_of_many(history_path, registry, instants)

    source_events: dict[str, list[sqlite3.Row]] = defaultdict(list)
    with sqlite3.connect(f"{history_path.resolve().as_uri()}?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        for row in db.execute(
            "SELECT source_event_id, target_market_status, diagnostic_code FROM historical_source_events"
        ):
            source_events[str(row["source_event_id"])].append(row)
    confirmed = {row["project_event_id"] for row in universe.get("confirmed_source_events", [])}
    output_events: list[dict[str, Any]] = []
    counts: dict[str, int] = defaultdict(int)
    for match in matches:
        event_id = match.get("project_event_id")
        kickoff = _utc(match["kickoff_utc"], field="kickoff")
        output_event: dict[str, Any] = {
            "project_event_id": event_id,
            "source_event_id": match.get("source_event_id"),
            "kickoff_utc": match["kickoff_utc"],
            "decision_at": _iso(kickoff - timedelta(minutes=15)),
            "market": "winner_withOT",
        }
        facts = source_events.get(source_by_event_id.get(str(event_id), ""), []) if event_id else []
        statuses = {str(row["target_market_status"]) for row in facts}
        diagnostics = {str(row["diagnostic_code"] or "") for row in facts}
        selection = selected.get(str(event_id)) if event_id else None
        price = _selection_payload(selection) if selection is not None else None
        category, reason = classify_provider_coverage(
            selection=selection,
            conflict=bool(event_id and event_id in conflicts),
            has_source=bool(facts),
            mapping_valid=bool(event_id and event_id in confirmed),
            statuses=statuses,
            diagnostics=diagnostics,
            max_age_seconds=86400,
        )
        if not event_id or match.get("status") != "resolved":
            category, reason = "mapping_error", "unresolved_universe_event"
        elif category == "stale_price" and price is not None:
            price["decision_at"] = _iso(instants[event_id])
            output_event["price_candidate"] = price
        elif category == "covered" and price is not None:
            if set(price["prices"]) != {"home_win", "away_win"}:
                category, reason = "mapping_error", "incomplete_outcome_vector"
            else:
                price["decision_at"] = _iso(instants[event_id])
                output_event["price"] = price
        output_event["coverage"] = category
        output_event["reason"] = reason
        counts[category] += 1
        output_events.append(output_event)
    categories = dict(sorted(counts.items()))
    retrieval = {
        "unknown": sum(
            1
            for event in output_events
            if (event.get("price") or event.get("price_candidate"))
            and (event.get("price") or event.get("price_candidate"))["retrieval_status"]
            == "unknown"
        ),
        "late": sum(
            1
            for event in output_events
            if (event.get("price") or event.get("price_candidate"))
            and (event.get("price") or event.get("price_candidate"))["late_retrieval"] is True
        ),
    }
    config = {
        "source": "the_odds_api",
        "bookmaker": "pinnacle",
        "market": "winner_withOT",
        "decision_offset_minutes": 15,
        "max_age_seconds": 86400,
        "selection_mode": "provider_as_of",
        "window_start_utc": _iso(lower),
        "window_end_utc_exclusive": _iso(upper),
    }
    data_bytes = b"".join(_canonical(row) + b"\n" for row in output_events)
    manifest_core = {
        "format": _FORMAT,
        "format_version": 1,
        "registry_snapshot_id": registry.snapshot_id,
        "universe_run_id": universe["run_id"],
        "universe_sha256": "sha256:" + hashlib.sha256(universe_path.read_bytes()).hexdigest(),
        "historical_fingerprint": actual_fp,
        "resolved_config": config,
        "events_sha256": "sha256:" + hashlib.sha256(data_bytes).hexdigest(),
        "expected_events": len(matches),
        "coverage": categories,
        "retrieval_diagnostics": retrieval,
    }
    dataset_id = "pd1:" + hashlib.sha256(_canonical(manifest_core)).hexdigest()
    manifest = {**manifest_core, "dataset_id": dataset_id}
    target = Path(output_root) / dataset_id.split(":", 1)[1]
    target.mkdir(parents=True, exist_ok=True)
    events_path, manifest_path = target / "events.jsonl", target / "manifest.json"
    for path, payload in ((events_path, data_bytes), (manifest_path, _canonical(manifest) + b"\n")):
        if path.exists() and path.read_bytes() != payload:
            raise ValueError("Существующий research dataset не совпадает с каноническим содержимым")
        if not path.exists():
            path.write_bytes(payload)
    logger.info("Собран provider-as-of dataset %s: %s", dataset_id, categories)
    return manifest_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Сборка локального Pinnacle provider-as-of dataset"
    )
    parser.add_argument("--universe-manifest", type=Path, required=True)
    parser.add_argument("--historical-database", type=Path, required=True)
    parser.add_argument("--matches", type=Path, required=True)
    parser.add_argument("--team-seed", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--start")
    parser.add_argument("--end")
    args = parser.parse_args()
    print(
        build_provider_dataset(
            universe_manifest_path=args.universe_manifest,
            historical_database_path=args.historical_database,
            snapshot_path=args.snapshot,
            matches_path=args.matches,
            team_seed_path=args.team_seed,
            output_root=args.output,
            start=args.start,
            end=args.end,
        )
    )


if __name__ == "__main__":
    main()
