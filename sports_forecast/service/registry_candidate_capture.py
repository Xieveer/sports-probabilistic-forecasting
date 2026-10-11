"""Создание server feedback только для неразрешённых обозначений snapshot."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy.orm import Session

from sports_forecast.identity.installation import InstalledRegistryReader
from sports_forecast.service.db.models import CanonicalEvent, EventRegistryMapping
from sports_forecast.service.db.registry_feedback import (
    CandidateObservation,
    enqueue_registry_candidate,
    installation_id_from_environment,
)


def enqueue_unknown_designation(
    session: Session,
    reader: InstalledRegistryReader,
    *,
    source: str,
    kind: Literal["tournament", "team", "event", "player", "market"],
    scope: dict[str, str],
    value_kind: Literal["name", "external_id"],
    raw_value: str,
    basis: str,
    observed_at: datetime,
    effective_at: datetime | None = None,
    facts: dict[str, str] | None = None,
) -> bool:
    """Записать неразрешённое обозначение в durable outbox текущего ir1.

    Возвращает `True` только для unresolved/ambiguous/conflict. Пустое значение
    пропускается: оно не образует проверяемого обозначения для владельца.
    """
    value = raw_value.strip()
    if not value:
        return False
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("Candidate observed_at должен содержать timezone")
    result = reader.resolve_designation(
        source=source,
        kind=kind,
        scope=scope,
        value_kind=value_kind,
        raw_value=value,
        at=(effective_at or observed_at).astimezone(UTC).isoformat(),
    )
    if result.status == "resolved":
        return False
    identity = json.dumps(
        [source, kind, sorted(scope.items()), value_kind, value],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    key = hashlib.sha256(identity).hexdigest()
    evidence = {"snapshot_id": reader.snapshot_id, "resolution_status": result.status}
    if facts:
        evidence.update(facts)
    enqueue_registry_candidate(
        session,
        CandidateObservation(
            source=source,
            kind=kind,
            scope=scope,
            value_kind=value_kind,
            raw_value=value,
            origin="server",
            idempotency_key=f"designation:{key}",
            observed_at=observed_at.astimezone(UTC).isoformat(),
            facts=evidence,
            proposed_entity_ids=(),
            basis=basis,
        ),
        installation_id=installation_id_from_environment(),
    )
    return True


def enqueue_unresolved_canonical_event(
    session: Session,
    reader: InstalledRegistryReader,
    event: CanonicalEvent,
    mapping: EventRegistryMapping,
    *,
    observed_at: datetime,
    capture_unknown_designations: bool = True,
) -> int:
    """Передать только проверяемые неизвестные факты source event владельцу."""
    if mapping.status == "resolved":
        return 0
    source = str(event.source)
    sport = str(event.sport)
    scheduled_at = (
        event.scheduled_at.replace(tzinfo=UTC)
        if event.scheduled_at.tzinfo is None
        else event.scheduled_at.astimezone(UTC)
    )
    if not capture_unknown_designations:
        return int(
            _enqueue_confirmed_event_relation_conflict(
                session,
                reader,
                event,
                mapping,
                source=source,
                sport=sport,
                scheduled_at=scheduled_at,
                observed_at=observed_at,
            )
        )
    tournament = reader.resolve_designation(
        source=source,
        kind="tournament",
        scope={"sport": sport},
        value_kind="name",
        raw_value=str(event.tournament),
        at=scheduled_at.isoformat(),
    )
    if tournament.status != "resolved" or tournament.entity_id is None:
        return int(
            enqueue_unknown_designation(
                session,
                reader,
                source=source,
                kind="tournament",
                scope={"sport": sport},
                value_kind="name",
                raw_value=str(event.tournament),
                basis="Спортивный источник содержит неизвестный турнир",
                observed_at=observed_at,
                effective_at=scheduled_at,
                facts={"source_event_id": str(event.source_event_id)},
            )
        )
    scope = {"sport": sport, "tournament": tournament.entity_id}
    count = 0
    for raw in (str(event.home_participant or ""), str(event.away_participant or "")):
        if not raw:
            continue
        count += int(
            enqueue_unknown_designation(
                session,
                reader,
                source=source,
                kind="team",
                scope=scope,
                value_kind="name",
                raw_value=raw,
                basis="Спортивный источник содержит неизвестную команду",
                observed_at=observed_at,
                effective_at=scheduled_at,
                facts={"source_event_id": str(event.source_event_id)},
            )
        )
    count += int(
        _enqueue_confirmed_event_relation_conflict(
            session,
            reader,
            event,
            mapping,
            source=source,
            sport=sport,
            scheduled_at=scheduled_at,
            observed_at=observed_at,
        )
    )
    return count


def _enqueue_confirmed_event_relation_conflict(
    session: Session,
    reader: InstalledRegistryReader,
    event: CanonicalEvent,
    mapping: EventRegistryMapping,
    *,
    source: str,
    sport: str,
    scheduled_at: datetime,
    observed_at: datetime,
) -> bool:
    """Создать кандидата только при конфликте уже закреплённой event связи."""
    if mapping.status != "conflict":
        return False
    stored = session.get(EventRegistryMapping, (reader.snapshot_id, int(event.id)))
    if stored is None or stored.project_event_id is None:
        return False
    tournament = reader.resolve_designation(
        source=source,
        kind="tournament",
        scope={"sport": sport},
        value_kind="name",
        raw_value=str(event.tournament),
        at=scheduled_at.isoformat(),
    )
    if tournament.status != "resolved" or tournament.entity_id is None:
        return False
    scope = {"sport": sport, "tournament": tournament.entity_id}
    relation = reader.resolve_designation(
        source=source,
        kind="event",
        scope=scope,
        value_kind="external_id",
        raw_value=str(event.source_event_id),
        at=scheduled_at.isoformat(),
    )
    if relation.status != "resolved" or relation.entity_id != stored.project_event_id:
        return False
    values = [
        source,
        sport,
        scope,
        str(event.source_event_id),
        str(event.home_participant or ""),
        str(event.away_participant or ""),
        scheduled_at.isoformat(),
    ]
    key = hashlib.sha256(
        json.dumps(values, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    enqueue_registry_candidate(
        session,
        CandidateObservation(
            source=source,
            kind="event",
            scope=scope,
            value_kind="external_id",
            raw_value=str(event.source_event_id),
            origin="server",
            idempotency_key=f"event-relation:{key}",
            observed_at=observed_at.astimezone(UTC).isoformat(),
            facts={
                "snapshot_id": reader.snapshot_id,
                "canonical_event_id": str(event.id),
                "home_participant": str(event.home_participant or ""),
                "away_participant": str(event.away_participant or ""),
                "scheduled_at": scheduled_at.isoformat(),
                "resolution_status": mapping.status,
            },
            proposed_entity_ids=(str(stored.project_event_id),),
            basis="Изменившиеся участники source event противоречат подтверждённой связи",
        ),
        installation_id=installation_id_from_environment(),
    )
    return True
