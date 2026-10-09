"""Строгая identity resolution для документированных historical ingest adapters."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pandas as pd
import yaml

from sports_forecast.identity.data_provenance import IdentityRowResolution
from sports_forecast.identity.events import CanonicalEventRef, RegistryEventResolver
from sports_forecast.identity.registry import EntityRegistry
from sports_forecast.identity.review_service import CandidateObservation, ReviewQueueService
from sports_forecast.identity.snapshot import RegistrySnapshotReader, VerifiedRegistrySnapshot


def _raw_text(value: object) -> str:
    """Нормализовать provider scalar, не превращая missing в строку `nan`."""
    if pd.isna(cast(Any, value)):
        return ""
    return str(value).strip()


def resolve_source_frame(
    frame: pd.DataFrame,
    *,
    tournament_name: str,
    source_config_path: Path,
    snapshot: VerifiedRegistrySnapshot,
    master_registry: EntityRegistry | None = None,
) -> tuple[str, str, str, tuple[IdentityRowResolution, ...]]:
    """Разрешить строки NHL/Smart Tables по явному source schema config."""
    config = yaml.safe_load(Path(source_config_path).read_text(encoding="utf-8"))
    adapters = config.get("adapters") if isinstance(config, dict) else None
    adapter = adapters.get(tournament_name) if isinstance(adapters, dict) else None
    if not isinstance(adapter, dict):
        raise ValueError(f"Для турнира {tournament_name} нет identity adapter")
    required = ("source", "sport", "row_id", "event_id", "scheduled_at")
    if any(not isinstance(adapter.get(key), str) or not adapter[key] for key in required):
        raise ValueError("Identity adapter не содержит обязательные source columns")
    row_column = str(adapter["row_id"])
    for field in ("row_id", "event_id", "scheduled_at"):
        column = str(adapter[field])
        if column not in frame.columns:
            raise ValueError(f"Identity adapter column отсутствует: {column}")
    home_column = adapter.get("home") or adapter.get("home_id")
    away_column = adapter.get("away") or adapter.get("away_id")
    if not isinstance(home_column, str) or not isinstance(away_column, str):
        raise ValueError("Identity adapter должен задать home/away columns")
    tournament_column = adapter.get("tournament")
    if tournament_column is not None and tournament_column not in frame.columns:
        raise ValueError(f"Identity adapter column отсутствует: {tournament_column}")
    if home_column not in frame.columns or away_column not in frame.columns:
        raise ValueError("Identity adapter participant columns отсутствуют")
    if frame[row_column].isna().any() or frame[row_column].astype(str).str.strip().eq("").any():
        raise ValueError("Source rows содержат отсутствующий provider row ID")
    if frame[row_column].astype(str).duplicated().any():
        raise ValueError("Provider row ID должен быть уникальным до feature fan-out")
    source = str(adapter["source"])
    sport = str(adapter["sport"])
    resolver = RegistryEventResolver(snapshot.event_snapshot)
    offline_reader = RegistrySnapshotReader(snapshot)
    reviewer = ReviewQueueService(master_registry) if master_registry is not None else None
    rows = [row for _, row in frame.iterrows()]
    refs: list[CanonicalEventRef] = []
    scheduled_values: list[datetime | None] = []
    tournament_values: list[str] = []
    for index, row in enumerate(rows):
        scheduled_value = row[adapter["scheduled_at"]]
        scheduled: datetime | None = None
        if pd.notna(scheduled_value) and str(scheduled_value).strip():
            parsed = pd.to_datetime(scheduled_value, utc=True, errors="coerce")
            if pd.isna(parsed):
                raise ValueError("Source scheduled_at не является корректным временем")
            scheduled = parsed.to_pydatetime().astimezone(UTC)
        tournament_value = (
            _raw_text(row[tournament_column])
            if tournament_column
            else str(adapter.get("tournament_value", tournament_name))
        )
        ref = CanonicalEventRef(
            canonical_event_id=int(index) + 1,
            sport=sport,
            tournament=tournament_value,
            source=source,
            source_event_id=_raw_text(row[adapter["event_id"]]),
            scheduled_at=scheduled,
            home_participant=_raw_text(row[home_column]) or None,
            away_participant=_raw_text(row[away_column]) or None,
        )
        refs.append(ref)
        scheduled_values.append(scheduled)
        tournament_values.append(tournament_value)

    resolutions = resolver.resolve_many(tuple(refs))
    results: list[IdentityRowResolution] = []
    for row, ref, scheduled, tournament_value, result in zip(
        rows, refs, scheduled_values, tournament_values, resolutions, strict=True
    ):
        if result.status != "resolved" and reviewer is not None:
            scope = {"sport": sport}
            tournament_designation = offline_reader.resolve_designation(
                source=source,
                kind="tournament",
                scope={"sport": sport},
                value_kind="name",
                raw_value=tournament_value,
                at=scheduled.isoformat() if scheduled else None,
            )
            if tournament_designation.entity_id:
                scope["tournament"] = tournament_designation.entity_id
            facts = {
                "source_event_id": ref.source_event_id[:200],
                "home": (ref.home_participant or "")[:200],
                "away": (ref.away_participant or "")[:200],
                "scheduled_at": scheduled.isoformat() if scheduled else "",
            }
            alias_candidates = [("tournament", "name", tournament_value, {"sport": sport})]
            if tournament_designation.entity_id:
                alias_candidates.extend(
                    (
                        (
                            "team",
                            str(adapter.get("home_value_kind", "external_id")),
                            ref.home_participant or "",
                            scope,
                        ),
                        (
                            "team",
                            str(adapter.get("away_value_kind", "external_id")),
                            ref.away_participant or "",
                            scope,
                        ),
                    )
                )
                alias_candidates.append(("event", "external_id", ref.source_event_id, scope))
            for kind, value_kind, raw_value, candidate_scope in alias_candidates:
                if not raw_value:
                    continue
                existing = offline_reader.resolve_designation(
                    source=source,
                    kind=kind,
                    scope=candidate_scope,
                    value_kind=value_kind,
                    raw_value=raw_value,
                    at=scheduled.isoformat() if scheduled else None,
                )
                if existing.status == "resolved":
                    continue
                key = hashlib.sha256(
                    f"{tournament_name}\0{row[adapter['event_id']]}\0{kind}\0{raw_value}".encode()
                ).hexdigest()
                reviewer.observe(
                    CandidateObservation(
                        source=source,
                        kind=kind,
                        scope=candidate_scope,
                        value_kind=value_kind,
                        raw_value=raw_value,
                        origin=f"local:ingest:{tournament_name}",
                        idempotency_key=key,
                        observed_at=datetime.now(UTC).isoformat(),
                        facts=facts,
                        basis=(
                            f"Нет подтверждённой designation в pinned snapshot "
                            f"{snapshot.snapshot_id}; требуется review"
                        ),
                    )
                )
        results.append(
            IdentityRowResolution(
                row_id=str(row[row_column]).strip(),
                source_event_id=ref.source_event_id,
                status=result.status,
                project_event_id=result.project_event_id,
                reason=result.reason,
            )
        )
    return str(adapter.get("name", tournament_name)), source, row_column, tuple(results)
