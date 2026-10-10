"""Локальный coverage отчёт provider history для закреплённого registry."""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sports_forecast.data.providers.odds.historical import (
    HistoricalOddsConflictError,
    _utc,
    query_provider_as_of,
)
from sports_forecast.identity.events import CanonicalEventRef, RegistryEventResolver
from sports_forecast.identity.snapshot import RegistrySnapshotReader


@dataclass(frozen=True)
class HistoricalCoverageReport:
    """Воспроизводимые параметры и взаимно исключающие категории ожидаемых матчей."""

    source: str
    bookmaker: str
    market: str
    registry_snapshot_id: str
    from_utc: str
    to_utc: str
    at_utc: str
    expected_events: int
    covered: int
    no_line: int
    no_snapshot: int
    mapping_error: int
    imported_files: int
    imported_file_fingerprint: str
    import_diagnostics: dict[str, int]
    import_failures: int
    conflicts: int
    unknown_retrieval: int
    late_retrieval: int
    unmapped_source_events: int
    categories: dict[str, list[dict[str, Any]]]

    def to_dict(self) -> dict[str, Any]:
        """Преобразовать отчёт в JSON-совместимую структуру."""
        return asdict(self)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _load_import_facts(
    database_path: Path,
) -> tuple[list[sqlite3.Row], dict[str, int], list[sqlite3.Row], int]:
    connection = sqlite3.connect(Path(database_path))
    connection.row_factory = sqlite3.Row
    try:
        source_events = connection.execute(
            """SELECT DISTINCT source_event_id, commence_time, source_home, source_away,
                      bookmaker_keys_json, market_keys_json, target_market_status, diagnostic_code
               FROM historical_source_events ORDER BY source_event_id"""
        ).fetchall()
        diagnostics = {
            str(row["diagnostic_code"]): int(row["count"])
            for row in connection.execute(
                "SELECT diagnostic_code, SUM(count) AS count FROM historical_diagnostics GROUP BY diagnostic_code"
            ).fetchall()
        }
        files = connection.execute(
            "SELECT file_sha256 FROM historical_cache_files ORDER BY file_sha256"
        ).fetchall()
        conflicts = connection.execute(
            """SELECT COUNT(*) FROM (
                   SELECT source_event_id, observed_at
                   FROM historical_observations
                   GROUP BY source_event_id, observed_at
                   HAVING COUNT(DISTINCT observation_id) > 1
               )"""
        ).fetchone()[0]
        return source_events, diagnostics, files, int(conflicts)
    finally:
        connection.close()


def _receipt_counts(database_path: Path, at: datetime) -> tuple[int, int, int]:
    connection = sqlite3.connect(Path(database_path))
    try:
        row = connection.execute(
            """SELECT COUNT(*),
                      SUM(CASE WHEN retrieved_at IS NULL THEN 1 ELSE 0 END),
                      SUM(CASE WHEN retrieved_at > ? THEN 1 ELSE 0 END)
               FROM historical_receipts""",
            (_iso(at),),
        ).fetchone()
        return int(row[0] or 0), int(row[1] or 0), int(row[2] or 0)
    finally:
        connection.close()


def build_coverage_report(
    database_path: Path,
    registry_reader: RegistrySnapshotReader,
    *,
    start: datetime,
    end: datetime,
    at: datetime,
) -> HistoricalCoverageReport:
    """Посчитать event coverage по NHL universe pinned snapshot и UTC окну kickoff."""
    lower, upper, instant = (
        _utc(start, field="from"),
        _utc(end, field="to"),
        _utc(at, field="T"),
    )
    if lower >= upper:
        raise ValueError("from должен предшествовать to")

    expected = []
    for event in registry_reader.snapshot.event_snapshot.events:
        if event.sport != "ice_hockey" or event.scheduled_at is None:
            continue
        scheduled = _utc(event.scheduled_at, field="scheduled_at")
        if not lower <= scheduled < upper:
            continue
        try:
            tournament = registry_reader.get_entity(event.tournament_id)
        except KeyError:
            continue
        if tournament.project_name.casefold() == "nhl":
            expected.append((event, scheduled))

    source_events, diagnostics, files, stored_conflicts = _load_import_facts(Path(database_path))
    categories: dict[str, list[dict[str, Any]]] = {
        "covered": [],
        "no_line": [],
        "no_snapshot": [],
        "mapping_error": [],
    }
    refs = tuple(
        CanonicalEventRef(
            canonical_event_id=index,
            sport="ice_hockey",
            tournament="icehockey_nhl",
            source="the_odds_api",
            source_event_id=str(row["source_event_id"]),
            scheduled_at=(
                _utc(row["commence_time"], field="commence_time") if row["commence_time"] else None
            ),
            home_participant=row["source_home"],
            away_participant=row["source_away"],
        )
        for index, row in enumerate(source_events)
    )
    resolutions = RegistryEventResolver(registry_reader.snapshot.event_snapshot).resolve_many(refs)
    resolved_by_event: dict[str, set[str]] = {}
    unresolved_ids: set[str] = set()
    for row, resolution in zip(source_events, resolutions, strict=True):
        source_id = str(row["source_event_id"])
        if resolution.status == "resolved" and resolution.project_event_id:
            resolved_by_event.setdefault(source_id, set()).add(resolution.project_event_id)
        else:
            unresolved_ids.add(source_id)
    conflicts = stored_conflicts
    for event, scheduled in expected:
        source_ids = {
            key.source_event_id
            for key in event.source_keys
            if key.source == "the_odds_api"
            and key.sport == "ice_hockey"
            and key.tournament_id == event.tournament_id
        }
        candidates = [row for row in source_events if row["source_event_id"] in source_ids]
        item: dict[str, Any] = {"project_event_id": event.id, "kickoff_utc": _iso(scheduled)}
        try:
            selection = query_provider_as_of(
                Path(database_path),
                registry_reader,
                project_event_id=event.id,
                at=instant,
            )
        except HistoricalOddsConflictError:
            selection = None
            item["subreason"] = "conflicting_snapshot"
            categories["mapping_error"].append(item)
            continue
        if selection is not None:
            item.update(
                {
                    "subreason": "selected_snapshot",
                    "observation_id": selection.observation_id,
                    "observed_at": _iso(selection.observed_at),
                    "retrieval_status": selection.retrieval_status,
                    "late_retrieval": selection.late_retrieval,
                }
            )
            categories["covered"].append(item)
            continue
        if not candidates:
            item["subreason"] = "no_source_evidence"
            categories["no_snapshot"].append(item)
            continue
        if any(
            str(row["source_event_id"]) in unresolved_ids
            or resolved_by_event.get(str(row["source_event_id"]), set()) != {event.id}
            for row in candidates
        ):
            item["subreason"] = "unresolved_or_conflicting_event_mapping"
            categories["mapping_error"].append(item)
            continue
        statuses = {str(row["target_market_status"]) for row in candidates}
        invalid = [
            row
            for row in candidates
            if (
                str(row["target_market_status"]) == "invalid_target_market"
                or str(row["diagnostic_code"] or "").startswith("duplicate_")
            )
        ]
        if invalid:
            item["subreason"] = str(invalid[0]["diagnostic_code"] or "invalid_source_market")
            categories["mapping_error"].append(item)
        elif any(row["diagnostic_code"] == "invalid_envelope_timestamp" for row in candidates):
            item["subreason"] = "invalid_envelope_timestamp"
            categories["no_snapshot"].append(item)
        elif statuses <= {"no_pinnacle", "no_h2h"}:
            item["subreason"] = "no_pinnacle" if "no_pinnacle" in statuses else "no_h2h"
            categories["no_line"].append(item)
        else:
            item["subreason"] = "no_snapshot_at_or_before_T"
            categories["no_snapshot"].append(item)

    unmapped = {
        str(row["source_event_id"])
        for row, resolution in zip(source_events, resolutions, strict=True)
        if resolution.status != "resolved"
    }
    _, unknown_retrieval, late_retrieval = _receipt_counts(Path(database_path), instant)
    fingerprint = hashlib.sha256(
        "\n".join(str(row["file_sha256"]) for row in files).encode("utf-8")
    ).hexdigest()
    return HistoricalCoverageReport(
        source="the_odds_api",
        bookmaker="pinnacle",
        market="winner_withOT",
        registry_snapshot_id=registry_reader.snapshot_id,
        from_utc=_iso(lower),
        to_utc=_iso(upper),
        at_utc=_iso(instant),
        expected_events=len(expected),
        covered=len(categories["covered"]),
        no_line=len(categories["no_line"]),
        no_snapshot=len(categories["no_snapshot"]),
        mapping_error=len(categories["mapping_error"]),
        imported_files=len(files),
        imported_file_fingerprint=f"sha256:{fingerprint}",
        import_diagnostics=diagnostics,
        import_failures=sum(diagnostics.values()),
        conflicts=conflicts,
        unknown_retrieval=unknown_retrieval,
        late_retrieval=late_retrieval,
        unmapped_source_events=len(unmapped),
        categories=categories,
    )
