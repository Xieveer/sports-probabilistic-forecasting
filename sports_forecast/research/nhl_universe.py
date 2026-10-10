"""Закрепление ожидаемого NHL universe и строгих связей с historical events."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pandas as pd

from sports_forecast.data.providers.odds.historical import ImportedSourceEvent
from sports_forecast.identity import EntityRegistry
from sports_forecast.identity.events import (
    CanonicalEventRef,
    EventIdentitySnapshot,
    RegistryEventResolver,
)
from sports_forecast.identity.nhl_seed import import_nhl_yaml
from sports_forecast.identity.snapshot import export_registry_snapshot, verify_registry_snapshot
from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)
_POLICY_VERSION = "nhl-universe-exact-utc-v3"
_MATCH_COLUMNS = ("id", "nhl_id", "datetime", "home_team", "away_team", "game_type")


@dataclass(frozen=True)
class NHLUniverseResult:
    """Итог закрепления входного NHL universe."""

    run_id: str
    snapshot_id: str
    report_path: Path
    input_fingerprint: str
    raw_events_in_window: int
    expected_events: int
    excluded_non_model_game_type: int
    resolved_nhl_events: int
    unresolved_nhl_events: int
    source_event_resolutions: dict[str, int]
    registry_designations: int
    universe_by_month: dict[str, int]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _utc(value: object, *, field: str) -> datetime | None:
    if value is None or pd.isna(cast(Any, value)) or not str(value).strip():
        return None
    parsed = pd.to_datetime(str(value), utc=True, errors="coerce")
    if pd.isna(parsed):
        raise ValueError(f"Некорректное UTC время в поле {field}")
    return pd.Timestamp(parsed).to_pydatetime().astimezone(UTC)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z") if value else None


def _read_historical_inputs(
    database_path: Path,
) -> tuple[tuple[ImportedSourceEvent, ...], str]:
    """Прочитать исторические факты и fingerprints строго без записи в SQLite."""
    uri = f"{Path(database_path).resolve().as_uri()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    try:
        file_hashes = tuple(
            str(row["file_sha256"])
            for row in connection.execute(
                "SELECT file_sha256 FROM historical_cache_files ORDER BY file_sha256"
            )
        )
        rows = connection.execute(
            """SELECT file_sha256, source_event_id, commence_time, source_home, source_away,
                      bookmaker_keys_json, market_keys_json, target_market_status, diagnostic_code
               FROM historical_source_events
               ORDER BY commence_time, source_event_id, file_sha256"""
        ).fetchall()
    finally:
        connection.close()

    events = tuple(
        ImportedSourceEvent(
            file_sha256=row["file_sha256"],
            source_event_id=row["source_event_id"],
            commence_time=_utc(row["commence_time"], field="commence_time")
            if row["commence_time"]
            else None,
            source_home=row["source_home"],
            source_away=row["source_away"],
            bookmaker_keys=tuple(json.loads(row["bookmaker_keys_json"])),
            market_keys=tuple(json.loads(row["market_keys_json"])),
            target_market_status=row["target_market_status"],
            diagnostic_code=row["diagnostic_code"],
        )
        for row in rows
    )
    fingerprint = f"sha256:{hashlib.sha256(chr(10).join(file_hashes).encode()).hexdigest()}"
    return events, fingerprint


def _validate_registry_location(
    registry_path: Path, output_root: Path, historical_database_path: Path
) -> None:
    """Не допускать использования известных current/production registry путей."""
    resolved_registry = Path(registry_path).resolve()
    resolved_output = Path(output_root).resolve()
    resolved_historical = Path(historical_database_path).resolve()
    if resolved_registry == resolved_historical:
        raise ValueError("Research registry не может совпадать с historical input")
    if Path(registry_path).exists() and Path(historical_database_path).exists():
        try:
            if Path(registry_path).samefile(Path(historical_database_path)):
                raise ValueError("Research registry не может совпадать с historical input")
        except OSError:
            pass
    try:
        resolved_registry.relative_to(resolved_output)
    except ValueError as exc:
        raise ValueError(
            "Research registry должен находиться внутри отдельного output каталога"
        ) from exc

    project_data = Path(__file__).resolve().parents[2] / "data"
    protected_registry_root = project_data / "registry"
    if (
        resolved_registry == protected_registry_root
        or protected_registry_root in resolved_registry.parents
    ):
        raise ValueError("Нельзя использовать protected production registry для research output")
    if resolved_registry.parent == project_data and resolved_registry.name.startswith(
        "entity-registry"
    ):
        raise ValueError("Нельзя использовать protected production registry для research output")


def _read_matches(
    path: Path, start: datetime, end: datetime
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    frame = pd.read_parquet(Path(path), columns=list(_MATCH_COLUMNS))
    missing = set(_MATCH_COLUMNS) - set(frame.columns)
    if missing:
        raise ValueError(f"В NHL parquet отсутствуют поля идентичности: {sorted(missing)}")
    rows: list[dict[str, Any]] = []
    untimed: list[dict[str, Any]] = []
    excluded_game_types: list[dict[str, Any]] = []
    for record in frame.to_dict(orient="records"):
        kickoff = _utc(record["datetime"], field="datetime")
        nhl_id = "" if pd.isna(record["nhl_id"]) else str(record["nhl_id"]).strip()
        row_id = "" if pd.isna(record["id"]) else str(record["id"]).strip()
        home = "" if pd.isna(record["home_team"]) else str(record["home_team"]).strip()
        away = "" if pd.isna(record["away_team"]) else str(record["away_team"]).strip()
        game_type = "" if pd.isna(record["game_type"]) else str(record["game_type"]).strip()
        if kickoff is None:
            untimed.append(
                {"row_id": row_id, "source_event_id": nhl_id or None, "reason": "missing_kickoff"}
            )
            continue
        if start <= kickoff < end:
            if game_type.casefold() not in {"regular", "playoffs"}:
                excluded_game_types.append(
                    {
                        "row_id": row_id,
                        "source_event_id": nhl_id or None,
                        "kickoff_utc": _iso(kickoff),
                        "game_type": game_type or None,
                        "reason": "missing_game_type" if not game_type else "non_model_game_type",
                    }
                )
                continue
            rows.append(
                {
                    "row_id": row_id,
                    "nhl_id": nhl_id,
                    "kickoff": kickoff,
                    "home": home,
                    "away": away,
                    "game_type": game_type.casefold(),
                }
            )
    return (
        sorted(rows, key=lambda row: (row["kickoff"], row["nhl_id"], row["row_id"])),
        untimed,
        excluded_game_types,
    )


def _designation_counts(registry: EntityRegistry) -> int:
    return registry.count_designations()


def pin_nhl_universe(
    matches_path: Path,
    historical_database_path: Path,
    registry: EntityRegistry,
    *,
    seed_path: Path,
    output_root: Path,
    start: str | datetime,
    end: str | datetime,
) -> NHLUniverseResult:
    """Создать отдельный immutable report и `ir1` для заданного периода NHL.

    Входные parquet читаются только по колонкам идентичности; результаты игр и
    признаки не загружаются. Повторные и конфликтные связи остаются диагностикой.
    """
    lower = _utc(start, field="start")
    upper = _utc(end, field="end")
    if lower is None or upper is None or lower >= upper:
        raise ValueError("Требуется непустой UTC интервал start < end")
    if not Path(matches_path).is_file() or not Path(historical_database_path).is_file():
        raise ValueError("Локальные NHL parquet и historical SQLite должны существовать")
    _validate_registry_location(registry.path, Path(output_root), Path(historical_database_path))

    match_fingerprint = _sha256(Path(matches_path))
    seed_fingerprint = _sha256(Path(seed_path))
    imported_events, historical_fingerprint = _read_historical_inputs(
        Path(historical_database_path)
    )
    source_events_by_id: dict[str, list[ImportedSourceEvent]] = defaultdict(list)
    for event in imported_events:
        source_events_by_id[event.source_event_id].append(event)
    conflicting_source_ids: dict[str, list[ImportedSourceEvent]] = {}
    deduplicated_source_events: list[ImportedSourceEvent] = []
    for source_id, candidates in sorted(source_events_by_id.items()):
        in_window = [
            candidate
            for candidate in candidates
            if candidate.commence_time is not None and lower <= candidate.commence_time < upper
        ]
        if not in_window:
            continue
        facts = {
            (candidate.commence_time, candidate.source_home, candidate.source_away)
            for candidate in candidates
        }
        if len(facts) > 1:
            conflicting_source_ids[source_id] = in_window
        else:
            deduplicated_source_events.append(in_window[0])
    source_events = tuple(deduplicated_source_events)
    window = {"start_utc": _iso(lower), "end_utc_exclusive": _iso(upper)}
    input_identity = {
        "policy_version": _POLICY_VERSION,
        "window": window,
        "matches_sha256": match_fingerprint,
        "historical_files_sha256": historical_fingerprint,
        "team_seed_sha256": seed_fingerprint,
    }
    run_id = hashlib.sha256(
        json.dumps(input_identity, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    run_dir = Path(output_root) / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    report_path = run_dir / "manifest.json"
    rows, untimed_rows, excluded_game_types = _read_matches(Path(matches_path), lower, upper)
    raw_events_in_window = len(rows) + len(excluded_game_types)
    nhl_id_counts = Counter(row["nhl_id"] for row in rows if row["nhl_id"])
    exact_match_counts = Counter(
        (row["kickoff"], row["home"], row["away"]) for row in rows if row["kickoff"]
    )

    import_nhl_yaml(registry, Path(seed_path))
    tournament = next(
        entity
        for entity in registry.list_entities(kind="tournament")
        if entity.project_name.casefold() == "nhl" and entity.sport == "ice_hockey"
    )
    scope = {"sport": "ice_hockey", "tournament": tournament.id}
    match_diagnostics: list[dict[str, Any]] = [
        {
            "row_id": row["row_id"],
            "source_event_id": row["source_event_id"],
            "project_event_id": None,
            "kickoff_utc": None,
            "status": "unresolved",
            "reason": row["reason"],
        }
        for row in untimed_rows
    ]
    entities_by_nhl_id: dict[str, dict[str, Any]] = {}
    for row in rows:
        nhl_id = row["nhl_id"]
        issue: str | None = None
        if not nhl_id:
            issue = "missing_nhl_id"
        elif nhl_id_counts[nhl_id] > 1:
            issue = "duplicate_nhl_id"
        elif exact_match_counts[(row["kickoff"], row["home"], row["away"])] > 1:
            issue = "duplicate_exact_match"
        elif row["kickoff"] is None:
            issue = "missing_kickoff"
        elif not row["home"] or not row["away"]:
            issue = "missing_participant"

        home_resolution = (
            registry.resolve(
                "nhl_api", "team", scope, "external_id", row["home"], at=_iso(row["kickoff"])
            )
            if not issue
            else None
        )
        away_resolution = (
            registry.resolve(
                "nhl_api", "team", scope, "external_id", row["away"], at=_iso(row["kickoff"])
            )
            if not issue
            else None
        )
        if issue is None and (home_resolution is None or away_resolution is None):
            issue = "team_resolution_not_available"
        if issue is None and home_resolution is not None and home_resolution.status != "resolved":
            issue = "unknown_or_conflicting_home_team"
        if issue is None and away_resolution is not None and away_resolution.status != "resolved":
            issue = "unknown_or_conflicting_away_team"
        if (
            issue is None
            and home_resolution
            and away_resolution
            and home_resolution.entity_id == away_resolution.entity_id
        ):
            issue = "same_home_and_away_team"

        existing = (
            registry.resolve(
                "nhl_api", "event", scope, "external_id", nhl_id, at=_iso(row["kickoff"])
            )
            if nhl_id
            else None
        )
        event_id: str | None = None
        if issue is None and existing is not None and existing.status == "resolved":
            assert home_resolution is not None and away_resolution is not None
            assert home_resolution.entity_id is not None and away_resolution.entity_id is not None
            event_id = existing.entity_id
            try:
                relation = registry.get_event_relation(event_id or "")
            except KeyError:
                issue = "existing_event_missing_relation"
            else:
                if (
                    relation.tournament_id != tournament.id
                    or relation.home_team_id != home_resolution.entity_id
                    or relation.away_team_id != away_resolution.entity_id
                    or relation.scheduled_at != _iso(row["kickoff"])
                ):
                    issue = "existing_event_relation_conflict"
                    event_id = None
        elif issue is None and existing is not None and existing.status != "unresolved":
            issue = "existing_event_designation_ambiguous_or_conflicting"

        if issue is None and event_id is None:
            assert home_resolution is not None and away_resolution is not None
            project_event = registry.create_entity(
                "event",
                f"NHL {nhl_id}: {row['home']} v {row['away']}",
                sport="ice_hockey",
            )
            registry.set_event_relation(
                project_event.id,
                tournament_id=tournament.id,
                home_team_id=home_resolution.entity_id or "",
                away_team_id=away_resolution.entity_id or "",
                scheduled_at=row["kickoff"],
                actor="epic-030-research",
                reason="Точная NHL source запись, проверенные команды и UTC kickoff.",
            )
            registry.add_designation(
                entity_id=project_event.id,
                source="nhl_api",
                kind="event",
                scope=scope,
                value_kind="external_id",
                raw_value=nhl_id,
                state="confirmed",
                seed_key=f"epic-030:{_POLICY_VERSION}",
            )
            event_id = project_event.id
        if issue is None and event_id is not None:
            entities_by_nhl_id[nhl_id] = {
                "row_id": row["row_id"],
                "source_event_id": nhl_id,
                "project_event_id": event_id,
                "kickoff_utc": _iso(row["kickoff"]),
                "status": "resolved",
                "reason": "Точный NHL ID, confirmed team UUID и точный UTC kickoff.",
            }
        else:
            match_diagnostics.append(
                {
                    "row_id": row["row_id"],
                    "source_event_id": nhl_id or None,
                    "project_event_id": None,
                    "kickoff_utc": _iso(row["kickoff"]),
                    "status": "conflict" if issue and "conflict" in issue else "unresolved",
                    "reason": issue or "unresolved_identity",
                }
            )

    # Resolver получает полный batch, чтобы reverse uniqueness применялся к
    # историческим source IDs до сохранения любых их designations.
    event_snapshot = EventIdentitySnapshot.from_registry(registry)
    resolver = RegistryEventResolver(event_snapshot)
    refs = tuple(
        CanonicalEventRef(
            canonical_event_id=index,
            sport="ice_hockey",
            tournament="icehockey_nhl",
            source="the_odds_api",
            source_event_id=event.source_event_id,
            scheduled_at=event.commence_time,
            home_participant=event.source_home,
            away_participant=event.source_away,
        )
        for index, event in enumerate(source_events)
    )
    resolutions = resolver.resolve_many(refs)
    odds_status = Counter({"conflict": len(conflicting_source_ids)})
    confirmed_odds_events: list[dict[str, str | None]] = []
    odds_diagnostics: list[dict[str, Any]] = [
        {
            "source_event_id": source_id,
            "kickoff_utc": None,
            "status": "conflict",
            "reason": "Один historical source ID содержит несовместимые kickoff/participants.",
        }
        for source_id in sorted(conflicting_source_ids)
    ]
    for source_event, resolution in zip(source_events, resolutions, strict=True):
        status = resolution.status
        reason = resolution.reason
        if status == "resolved" and resolution.project_event_id:
            try:
                relation = registry.get_event_relation(resolution.project_event_id)
            except KeyError:
                status = "conflict"
                reason = "pinned_source_event_missing_relation"
            else:
                relation_kickoff = _utc(relation.scheduled_at, field="scheduled_at")
                if relation_kickoff != source_event.commence_time:
                    status = "conflict"
                    reason = "pinned_source_kickoff_conflict"
        odds_status[status] += 1
        if status == "resolved" and resolution.project_event_id:
            registry.add_designation(
                entity_id=resolution.project_event_id,
                source="the_odds_api",
                kind="event",
                scope={"sport": "ice_hockey", "tournament": tournament.id},
                value_kind="external_id",
                raw_value=source_event.source_event_id,
                state="confirmed",
                seed_key=f"epic-030:{_POLICY_VERSION}",
            )
            confirmed_odds_events.append(
                {
                    "source_event_id": source_event.source_event_id,
                    "project_event_id": resolution.project_event_id,
                    "kickoff_utc": _iso(source_event.commence_time),
                    "reason": reason,
                }
            )
        else:
            odds_diagnostics.append(
                {
                    "source_event_id": source_event.source_event_id,
                    "kickoff_utc": _iso(source_event.commence_time),
                    "status": status,
                    "reason": reason,
                }
            )

    snapshot = export_registry_snapshot(registry, Path(output_root) / "snapshots")
    verified = verify_registry_snapshot(snapshot.path)
    months = Counter(f"{row['kickoff']:%Y-%m}" for row in rows if row["kickoff"] is not None)
    years = Counter(f"{row['kickoff']:%Y}" for row in rows if row["kickoff"] is not None)
    exclusion_counts = Counter(
        str(item["reason"])
        for item in [*match_diagnostics, *odds_diagnostics, *excluded_game_types]
    )
    excluded_types = Counter(str(item["game_type"] or "missing") for item in excluded_game_types)
    manifest = {
        "format": "sports-forecast-pinned-nhl-universe",
        "format_version": 1,
        "run_id": run_id,
        "policy_version": _POLICY_VERSION,
        "source_fingerprints": {
            "matches_sha256": match_fingerprint,
            "historical_files_sha256": historical_fingerprint,
            "team_seed_sha256": seed_fingerprint,
        },
        "window": window,
        "snapshot_id": verified.snapshot_id,
        "snapshot_path": str(snapshot.path.relative_to(Path(output_root))),
        "raw_events_in_window": raw_events_in_window,
        "expected_events": len(rows),
        "excluded_non_model_game_type": len(excluded_game_types),
        "excluded_non_model_game_type_by_type": dict(sorted(excluded_types.items())),
        "resolved_nhl_events": len(entities_by_nhl_id),
        "unresolved_nhl_events": len(match_diagnostics) - len(untimed_rows),
        "untimed_source_rows": len(untimed_rows),
        "universe_by_month": dict(sorted(months.items())),
        "universe_by_year": dict(sorted(years.items())),
        "nhl_events": sorted(entities_by_nhl_id.values(), key=lambda item: item["source_event_id"]),
        "nhl_diagnostics": match_diagnostics,
        "non_model_game_type_diagnostics": excluded_game_types,
        "source_event_resolutions": {
            state: int(odds_status.get(state, 0))
            for state in ("resolved", "unresolved", "ambiguous", "conflict")
        },
        "confirmed_source_events": sorted(
            confirmed_odds_events, key=lambda item: str(item["source_event_id"])
        ),
        "source_event_diagnostics": odds_diagnostics,
        "exclusion_counts": dict(sorted(exclusion_counts.items())),
        "machine_decision": {
            "policy_version": _POLICY_VERSION,
            "basis": "confirmed tournament and team UUIDs, exact UTC kickoff, batch reverse uniqueness, no conflict",
            "source_designations": ["nhl_api", "the_odds_api"],
        },
    }
    encoded = json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if report_path.exists():
        previous = json.loads(report_path.read_text(encoding="utf-8"))
        identity_fields = (
            "format_version",
            "run_id",
            "policy_version",
            "source_fingerprints",
            "window",
            "snapshot_id",
        )
        if any(previous.get(field) != manifest.get(field) for field in identity_fields):
            raise ValueError("Существующий pinned run отличается; старый evidence не перезаписан")
    else:
        report_path.write_text(encoded, encoding="utf-8")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    designation_count = _designation_counts(registry)
    logger.info(
        "Закреплён NHL universe run=%s events=%d resolved=%d odds=%s snapshot=%s",
        run_id,
        len(rows),
        len(entities_by_nhl_id),
        dict(odds_status),
        verified.snapshot_id,
    )
    return NHLUniverseResult(
        run_id=run_id,
        snapshot_id=verified.snapshot_id,
        report_path=report_path,
        input_fingerprint=match_fingerprint,
        raw_events_in_window=int(report["raw_events_in_window"]),
        expected_events=int(report["expected_events"]),
        excluded_non_model_game_type=int(report["excluded_non_model_game_type"]),
        resolved_nhl_events=int(report["resolved_nhl_events"]),
        unresolved_nhl_events=int(report["unresolved_nhl_events"]),
        source_event_resolutions=report["source_event_resolutions"],
        registry_designations=designation_count,
        universe_by_month=report["universe_by_month"],
    )


def main() -> int:
    """Запустить локальное закрепление universe без сетевых операций."""
    parser = argparse.ArgumentParser(description="Закрепление NHL research universe")
    parser.add_argument("--matches", type=Path, required=True)
    parser.add_argument("--historical-database", type=Path, required=True)
    parser.add_argument("--registry-database", type=Path, required=True)
    parser.add_argument(
        "--team-seed", type=Path, default=Path("conf/bookmaker/team_name_registry/nhl.yaml")
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    args = parser.parse_args()
    _validate_registry_location(args.registry_database, args.output, args.historical_database)
    registry = EntityRegistry(args.registry_database)
    registry.initialize()
    result = pin_nhl_universe(
        args.matches,
        args.historical_database,
        registry,
        seed_path=args.team_seed,
        output_root=args.output,
        start=args.start,
        end=args.end,
    )
    print(json.dumps({**result.__dict__, "report_path": str(result.report_path)}, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
