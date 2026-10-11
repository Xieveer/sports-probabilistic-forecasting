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
    HistoricalSelection,
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
    unmapped_source_event_reasons: dict[str, int]
    categories: dict[str, list[dict[str, Any]]]

    def to_dict(self) -> dict[str, Any]:
        """Преобразовать отчёт в JSON-совместимую структуру."""
        return asdict(self)


def classify_provider_coverage(
    *,
    selection: HistoricalSelection | None = None,
    selection_age_seconds: float | None = None,
    has_selection: bool | None = None,
    conflict: bool,
    has_source: bool,
    mapping_valid: bool | None,
    statuses: set[str],
    diagnostics: set[str],
    max_age_seconds: float | None = None,
) -> tuple[str, str]:
    """Единая взаимно исключающая классификация coverage для заданного event T."""
    if conflict:
        return "conflict", "conflicting_snapshot"
    selected = selection is not None if has_selection is None else has_selection
    age = selection.age_seconds if selection is not None else selection_age_seconds
    if selected:
        if max_age_seconds is not None and age is not None and age > max_age_seconds:
            return "stale_price", "snapshot_older_than_limit"
        return "covered", "selected_snapshot"
    if mapping_valid is False:
        return "mapping_error", "source_event_not_confirmed"
    if not has_source:
        return "no_snapshot", "no_source_evidence"
    if not mapping_valid:
        return "mapping_error", "unresolved_or_conflicting_event_mapping"
    invalid = next((item for item in sorted(diagnostics) if item.startswith("duplicate_")), None)
    if "invalid_target_market" in statuses or invalid:
        return "mapping_error", invalid or "invalid_source_market"
    if "invalid_envelope_timestamp" in diagnostics:
        return "no_snapshot", "invalid_envelope_timestamp"
    if statuses and statuses <= {"no_pinnacle", "no_h2h"}:
        return "no_line", "no_pinnacle" if "no_pinnacle" in statuses else "no_h2h"
    return "no_snapshot", "no_snapshot_at_or_before_T"


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _unmapped_reason(status: str, reason: str) -> str:
    """Свернуть resolver status/reason в устойчивый счётчик причины unmapped."""
    if status == "ambiguous":
        return "ambiguous"
    if status == "conflict":
        return "mismatch" if "противоречит" in reason else "conflict"
    if reason in {
        "Неполный source key",
        "Tournament designation не подтверждён",
        "Home/away team designation не подтверждены",
        "Точное UTC время отсутствует",
    }:
        return "missing"
    return "mismatch"


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
    unmapped_reason_by_id: dict[str, str] = {}
    for row, resolution in zip(source_events, resolutions, strict=True):
        source_id = str(row["source_event_id"])
        if resolution.status == "resolved" and resolution.project_event_id:
            resolved_by_event.setdefault(source_id, set()).add(resolution.project_event_id)
        else:
            unresolved_ids.add(source_id)
            reason = _unmapped_reason(resolution.status, resolution.reason)
            previous = unmapped_reason_by_id.get(source_id)
            priority = {"missing": 0, "mismatch": 1, "ambiguous": 2, "conflict": 3}
            if previous is None or priority[reason] > priority[previous]:
                unmapped_reason_by_id[source_id] = reason
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
        conflict = False
        try:
            selection = query_provider_as_of(
                Path(database_path),
                registry_reader,
                project_event_id=event.id,
                at=instant,
            )
        except HistoricalOddsConflictError:
            selection = None
            conflict = True
        has_source = bool(candidates)
        mapping_valid = has_source and not any(
            str(row["source_event_id"]) in unresolved_ids
            or resolved_by_event.get(str(row["source_event_id"]), set()) != {event.id}
            for row in candidates
        )
        statuses = {str(row["target_market_status"]) for row in candidates}
        diagnostics_for_event = {str(row["diagnostic_code"] or "") for row in candidates}
        category, subreason = classify_provider_coverage(
            selection=selection,
            conflict=conflict,
            has_source=has_source,
            mapping_valid=mapping_valid if has_source else None,
            statuses=statuses,
            diagnostics=diagnostics_for_event,
        )
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
        item["subreason"] = subreason
        categories["mapping_error" if category == "conflict" else category].append(item)

    unmapped = set(unmapped_reason_by_id)
    unmapped_reasons: dict[str, int] = {}
    for reason in unmapped_reason_by_id.values():
        unmapped_reasons[reason] = unmapped_reasons.get(reason, 0) + 1
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
        unmapped_source_event_reasons=dict(sorted(unmapped_reasons.items())),
        categories=categories,
    )
