"""Strict event identity resolution and snapshot-pinned canonical bridge."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, TypedDict, cast

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from sports_forecast.identity.registry import EntityRegistry, _normalize
from sports_forecast.service.db.models import (
    CanonicalEvent,
    EventRegistryMapping,
    RegistryIdentitySnapshot,
)


EventResolutionStatus = Literal["resolved", "unresolved", "ambiguous", "conflict"]
NORMALIZATION_VERSION = "nfkc-casefold-alnum-v1"
_SUPPORTED_NORMALIZATION_VERSIONS = frozenset({NORMALIZATION_VERSION})
PROJECTION_SCHEMA_VERSION = 1


class _ResolutionMetadata(TypedDict):
    snapshot_id: str
    policy_version: str


def registry_event_reader_enabled(config_path: Path = Path("conf/identity_event.yaml")) -> bool:
    """Прочитать compatibility switch; по умолчанию новый reader выключен."""
    config = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
    if not isinstance(config, dict) or not isinstance(
        config.get("registry_event_reader_enabled"), bool
    ):
        raise ValueError("identity_event.yaml должен задать boolean registry_event_reader_enabled")
    return cast(bool, config["registry_event_reader_enabled"])


@dataclass(frozen=True)
class CanonicalEventRef:
    """Существующая canonical row с исходными значениями источника."""

    canonical_event_id: int
    sport: str
    tournament: str
    source: str
    source_event_id: str
    scheduled_at: datetime | None
    home_participant: str | None
    away_participant: str | None


@dataclass(frozen=True)
class EventSourceKey:
    """Подтверждённый source event key внутри проектного tournament scope."""

    source: str
    sport: str
    tournament_id: str
    source_event_id: str


@dataclass(frozen=True)
class ProjectEvent:
    """Проектное событие с подтверждёнными tournament/team relations."""

    id: str
    sport: str
    tournament_id: str
    home_team_id: str
    away_team_id: str
    scheduled_at: datetime | None
    source_keys: tuple[EventSourceKey, ...]


@dataclass(frozen=True)
class ConfirmedEventDesignation:
    """Snapshot designation включая состояние, нужное строгому resolver."""

    designation_id: str
    source: str
    kind: str
    scope: tuple[tuple[str, str], ...]
    value_kind: str
    raw_value: str
    entity_id: str | None
    state: str
    valid_from: str | None = None
    valid_until: str | None = None


@dataclass(frozen=True)
class EventConflictOverlay:
    """Revisioned conflict fact frozen as part of event projection."""

    designation_id: str
    peer_designation_id: str
    valid_from: str | None
    valid_until: str | None
    state: str
    selected_entity_id: str | None


@dataclass(frozen=True)
class EventIdentitySnapshot:
    """Неизменяемый набор подтверждённых event facts одной версии registry."""

    snapshot_id: str
    events: tuple[ProjectEvent, ...]
    designations: tuple[ConfirmedEventDesignation, ...]
    conflicts: tuple[EventConflictOverlay, ...]
    projection_sha256: str
    projection_json: str
    registry_schema_version: int
    projection_schema_version: int
    policy_version: str
    normalization_version: str

    @classmethod
    def from_registry(cls, registry: EntityRegistry) -> EventIdentitySnapshot:
        """Построить content-derived snapshot из одной SQLite read transaction."""
        policy_version = "strict-v1"
        normalization_version = NORMALIZATION_VERSION
        with registry._connect(write=False) as connection:
            relation_rows = connection.execute(
                "SELECT r.*,e.sport FROM event_relations r JOIN entities e ON e.id=r.event_id WHERE e.state='active' ORDER BY r.event_id"
            ).fetchall()
            designation_rows = connection.execute(
                "SELECT id,source,kind,scope_json,value_kind,raw_value,entity_id,state,valid_from,valid_until FROM designations ORDER BY id"
            ).fetchall()
            conflict_rows = connection.execute(
                "SELECT designation_id,peer_designation_id,valid_from,valid_until,state,selected_entity_id FROM designation_conflicts ORDER BY designation_id,peer_designation_id,valid_from,valid_until,state,selected_entity_id"
            ).fetchall()
            designations = tuple(
                ConfirmedEventDesignation(
                    row["id"],
                    row["source"],
                    row["kind"],
                    tuple(sorted(json.loads(row["scope_json"]).items())),
                    row["value_kind"],
                    row["raw_value"],
                    row["entity_id"],
                    row["state"],
                    row["valid_from"],
                    row["valid_until"],
                )
                for row in designation_rows
            )
            conflicts = tuple(
                EventConflictOverlay(
                    row["designation_id"],
                    row["peer_designation_id"],
                    row["valid_from"],
                    row["valid_until"],
                    row["state"],
                    row["selected_entity_id"],
                )
                for row in conflict_rows
            )
            events: list[ProjectEvent] = []
            for row in relation_rows:
                source_keys = tuple(
                    sorted(
                        (
                            EventSourceKey(
                                item.source, row["sport"], row["tournament_id"], item.raw_value
                            )
                            for item in designations
                            if item.kind == "event"
                            and item.state == "confirmed"
                            and item.entity_id == row["event_id"]
                            and dict(item.scope).get("sport") == row["sport"]
                            and dict(item.scope).get("tournament") == row["tournament_id"]
                            and item.value_kind == "external_id"
                        ),
                        key=lambda item: (
                            item.source,
                            item.sport,
                            item.tournament_id,
                            item.source_event_id,
                        ),
                    )
                )
                scheduled = _parse_utc(row["scheduled_at"])
                events.append(
                    ProjectEvent(
                        row["event_id"],
                        row["sport"],
                        row["tournament_id"],
                        row["home_team_id"],
                        row["away_team_id"],
                        scheduled,
                        source_keys,
                    )
                )
        return _make_snapshot(
            tuple(events),
            designations,
            conflicts,
            registry_schema_version=registry.schema_version,
            projection_schema_version=PROJECTION_SCHEMA_VERSION,
            policy_version=policy_version,
            normalization_version=normalization_version,
        )


@dataclass(frozen=True)
class EventResolution:
    """Строгий результат сопоставления без fuzzy/nearest fallback."""

    status: EventResolutionStatus
    project_event_id: str | None
    reason: str
    snapshot_id: str
    policy_version: str
    candidate_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class EventBackfillPlan:
    """Детерминированный dry-run или итог apply canonical bridge."""

    snapshot_id: str
    dry_run: bool
    mappings: tuple[EventResolution, ...]
    counts: dict[str, int]


def _snapshot_projection(
    events: tuple[ProjectEvent, ...],
    designations: tuple[ConfirmedEventDesignation, ...],
    conflicts: tuple[EventConflictOverlay, ...],
    *,
    registry_schema_version: int,
    projection_schema_version: int,
    policy_version: str,
    normalization_version: str,
) -> str:
    """Канонически сериализовать все факты, влияющие на resolver."""
    payload = {
        "format_version": 1,
        "projection_schema_version": projection_schema_version,
        "registry_schema_version": registry_schema_version,
        "policy_version": policy_version,
        "normalization_version": normalization_version,
        "events": [asdict(item) for item in sorted(events, key=lambda item: item.id)],
        "designations": [
            asdict(item)
            for item in sorted(
                designations,
                key=lambda item: (
                    item.source,
                    item.kind,
                    item.scope,
                    item.value_kind,
                    item.raw_value,
                    item.entity_id or "",
                    item.state,
                    item.valid_from or "",
                    item.valid_until or "",
                ),
            )
        ],
        "conflicts": [
            asdict(item)
            for item in sorted(
                conflicts,
                key=lambda item: (
                    item.designation_id,
                    item.peer_designation_id,
                    item.valid_from or "",
                    item.valid_until or "",
                    item.state,
                    item.selected_entity_id or "",
                ),
            )
        ],
    }
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_projection_value,
    )


def _json_projection_value(value: object) -> str:
    """Сериализовать timestamp только после канонизации UTC."""
    if isinstance(value, datetime):
        parsed = _parse_utc(value)
        if parsed is None:
            raise ValueError("Snapshot timestamp должен иметь timezone")
        return parsed.isoformat(timespec="microseconds").replace("+00:00", "Z")
    raise TypeError(f"Unsupported projection value: {type(value).__name__}")


def _make_snapshot(
    events: tuple[ProjectEvent, ...],
    designations: tuple[ConfirmedEventDesignation, ...],
    conflicts: tuple[EventConflictOverlay, ...],
    *,
    registry_schema_version: int,
    projection_schema_version: int,
    policy_version: str,
    normalization_version: str,
) -> EventIdentitySnapshot:
    events = tuple(sorted(events, key=lambda item: item.id))
    designations = tuple(
        sorted(
            designations,
            key=lambda item: (
                item.source,
                item.kind,
                item.scope,
                item.value_kind,
                item.raw_value,
                item.entity_id or "",
                item.state,
                item.valid_from or "",
                item.valid_until or "",
            ),
        )
    )
    conflicts = tuple(
        sorted(
            conflicts,
            key=lambda item: (
                item.designation_id,
                item.peer_designation_id,
                item.valid_from or "",
                item.valid_until or "",
                item.state,
                item.selected_entity_id or "",
            ),
        )
    )
    projection_json = _snapshot_projection(
        events,
        designations,
        conflicts,
        registry_schema_version=registry_schema_version,
        projection_schema_version=projection_schema_version,
        policy_version=policy_version,
        normalization_version=normalization_version,
    )
    projection_sha256 = hashlib.sha256(projection_json.encode("utf-8")).hexdigest()
    return EventIdentitySnapshot(
        snapshot_id=f"ev1:{projection_sha256}",
        events=events,
        designations=designations,
        conflicts=conflicts,
        projection_sha256=projection_sha256,
        projection_json=projection_json,
        registry_schema_version=registry_schema_version,
        projection_schema_version=projection_schema_version,
        policy_version=policy_version,
        normalization_version=normalization_version,
    )


def _validate_snapshot(snapshot: EventIdentitySnapshot) -> None:
    expected_json = _snapshot_projection(
        snapshot.events,
        snapshot.designations,
        snapshot.conflicts,
        registry_schema_version=snapshot.registry_schema_version,
        projection_schema_version=snapshot.projection_schema_version,
        policy_version=snapshot.policy_version,
        normalization_version=snapshot.normalization_version,
    )
    digest = hashlib.sha256(expected_json.encode("utf-8")).hexdigest()
    if (
        snapshot.projection_json != expected_json
        or snapshot.projection_sha256 != digest
        or snapshot.snapshot_id != f"ev1:{digest}"
    ):
        raise ValueError("Snapshot content не соответствует content-derived snapshot ID")
    if snapshot.normalization_version not in _SUPPORTED_NORMALIZATION_VERSIONS:
        raise ValueError("Unsupported normalization version в frozen event projection")
    if snapshot.projection_schema_version != PROJECTION_SCHEMA_VERSION:
        raise ValueError("Unsupported event projection schema version")


def load_event_snapshot(session: Session, *, snapshot_id: str) -> EventIdentitySnapshot:
    """Загрузить frozen projection из server DB без доступа к изменяемому registry."""
    header = session.get(RegistryIdentitySnapshot, snapshot_id)
    if header is None:
        raise KeyError(snapshot_id)
    payload = json.loads(header.projection_json)
    events = tuple(
        ProjectEvent(
            id=item["id"],
            sport=item["sport"],
            tournament_id=item["tournament_id"],
            home_team_id=item["home_team_id"],
            away_team_id=item["away_team_id"],
            scheduled_at=_parse_utc(item["scheduled_at"]),
            source_keys=tuple(EventSourceKey(**key) for key in item["source_keys"]),
        )
        for item in payload["events"]
    )
    designations = tuple(
        ConfirmedEventDesignation(
            designation_id=item["designation_id"],
            source=item["source"],
            kind=item["kind"],
            scope=tuple(tuple(pair) for pair in item["scope"]),
            value_kind=item["value_kind"],
            raw_value=item["raw_value"],
            entity_id=item["entity_id"],
            state=item["state"],
            valid_from=item["valid_from"],
            valid_until=item["valid_until"],
        )
        for item in payload["designations"]
    )
    conflicts = tuple(EventConflictOverlay(**item) for item in payload["conflicts"])
    snapshot = EventIdentitySnapshot(
        snapshot_id=header.snapshot_id,
        events=events,
        designations=designations,
        conflicts=conflicts,
        projection_sha256=header.projection_sha256,
        projection_json=header.projection_json,
        registry_schema_version=payload["registry_schema_version"],
        projection_schema_version=header.projection_schema_version,
        policy_version=header.policy_version,
        normalization_version=header.normalization_version,
    )
    _validate_snapshot(snapshot)
    if header.snapshot_kind != "event_projection":
        raise ValueError("Snapshot header kind не соответствует event_projection")
    return snapshot


def _parse_utc(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _interval_contains(valid_from: str | None, valid_until: str | None, at: datetime) -> bool:
    """Проверить полуоткрытый UTC интервал designation/overlay."""
    start = _parse_utc(valid_from)
    end = _parse_utc(valid_until)
    return (start is None or start <= at) and (end is None or at < end)


def _interval_is_bounded(valid_from: str | None, valid_until: str | None) -> bool:
    return valid_from is not None or valid_until is not None


class RegistryEventResolver:
    """Resolver по confirmed aliases/relation одного pinned snapshot."""

    def __init__(
        self, snapshot: EventIdentitySnapshot, *, policy_version: str | None = None
    ) -> None:
        _validate_snapshot(snapshot)
        if policy_version is not None and not policy_version.strip():
            raise ValueError("policy_version обязателен")
        selected_policy = policy_version or snapshot.policy_version
        if selected_policy != snapshot.policy_version:
            raise ValueError("Policy version не соответствует frozen event projection")
        self.snapshot = snapshot
        self.policy_version = selected_policy

    def _designation(
        self,
        source: str,
        kind: str,
        scope: dict[str, str],
        raw_value: str,
        *,
        at: datetime | None,
    ) -> tuple[EventResolutionStatus, str | None]:
        matches = [
            item
            for item in self.snapshot.designations
            if item.source == source
            and item.kind == kind
            and dict(item.scope) == scope
            and item.value_kind in ("name", "external_id")
            and _normalize(item.raw_value, item.value_kind)
            == _normalize(raw_value, item.value_kind)
        ]
        if not matches:
            return "unresolved", None
        designation_ids = {item.designation_id for item in matches}
        overlays = [
            overlay
            for overlay in self.snapshot.conflicts
            if overlay.state != "dismissed"
            and (
                overlay.designation_id in designation_ids
                or overlay.peer_designation_id in designation_ids
            )
        ]
        if at is None:
            if any(
                overlay.state == "open"
                and not _interval_is_bounded(overlay.valid_from, overlay.valid_until)
                for overlay in overlays
            ):
                return "conflict", None
            if any(
                _interval_is_bounded(overlay.valid_from, overlay.valid_until)
                for overlay in overlays
            ):
                return "ambiguous", None
            selected = {
                overlay.selected_entity_id for overlay in overlays if overlay.state == "resolved"
            }
            selected.discard(None)
            if len(selected) == 1:
                return "resolved", next(iter(selected))
            if len(selected) > 1:
                return "conflict", None
        else:
            active_overlays = [
                overlay
                for overlay in overlays
                if _interval_contains(overlay.valid_from, overlay.valid_until, at)
            ]
            if any(overlay.state == "open" for overlay in active_overlays):
                return "conflict", None
            selected = {
                overlay.selected_entity_id
                for overlay in active_overlays
                if overlay.state == "resolved"
            }
            selected.discard(None)
            if len(selected) == 1:
                return "resolved", next(iter(selected))
            if len(selected) > 1:
                return "conflict", None

        eligible = [
            item
            for item in matches
            if item.state not in {"rejected", "superseded"}
            and (at is None or _interval_contains(item.valid_from, item.valid_until, at))
        ]
        if at is None and any(
            item.state == "confirmed" and _interval_is_bounded(item.valid_from, item.valid_until)
            for item in eligible
        ):
            return "ambiguous", None
        entities = {item.entity_id for item in eligible if item.state == "confirmed"}
        entities.discard(None)
        if len(entities) > 1:
            return "conflict", None
        if len(entities) == 1:
            return "resolved", next(iter(entities))
        return "unresolved", None

    def _resolve_alias(
        self,
        source: str,
        kind: str,
        scope: dict[str, str],
        raw: str | None,
        *,
        at: datetime | None,
    ) -> tuple[EventResolutionStatus, str | None]:
        if not raw:
            return "unresolved", None
        return self._designation(source, kind, scope, raw, at=at)

    def resolve(self, ref: CanonicalEventRef) -> EventResolution:
        """Resolve confirmed exact aliases and unique exact-time event candidates."""
        base: _ResolutionMetadata = {
            "snapshot_id": self.snapshot.snapshot_id,
            "policy_version": self.policy_version,
        }
        if (
            not ref.source.strip()
            or not ref.sport.strip()
            or not ref.tournament.strip()
            or not ref.source_event_id.strip()
        ):
            return EventResolution("unresolved", None, "Неполный source key", **base)
        event_time = _parse_utc(ref.scheduled_at)
        tournament_status, tournament_id = self._resolve_alias(
            ref.source,
            "tournament",
            {"sport": ref.sport},
            ref.tournament,
            at=event_time,
        )
        if tournament_status == "conflict":
            return EventResolution("conflict", None, "Tournament designation конфликтует", **base)
        if tournament_status == "ambiguous":
            return EventResolution(
                "ambiguous", None, "Нужна дата для tournament designation", **base
            )
        if tournament_id is None:
            return EventResolution(
                "unresolved", None, "Tournament designation не подтверждён", **base
            )
        scope = {"sport": ref.sport, "tournament": tournament_id}
        home_status, home_id = self._resolve_alias(
            ref.source, "team", scope, ref.home_participant, at=event_time
        )
        away_status, away_id = self._resolve_alias(
            ref.source, "team", scope, ref.away_participant, at=event_time
        )
        if "conflict" in (home_status, away_status):
            return EventResolution("conflict", None, "Team designation конфликтует", **base)
        if "ambiguous" in (home_status, away_status):
            return EventResolution("ambiguous", None, "Нужна дата для team designation", **base)
        event_status, source_project_event_id = self._resolve_alias(
            ref.source, "event", scope, ref.source_event_id, at=event_time
        )
        if event_status == "conflict":
            return EventResolution("conflict", None, "Source event designation конфликтует", **base)
        if event_status == "ambiguous":
            return EventResolution("ambiguous", None, "Нужна дата для source event ID", **base)
        source_matches = [
            event for event in self.snapshot.events if event.id == source_project_event_id
        ]
        if len(source_matches) > 1:
            return EventResolution(
                "conflict",
                None,
                "Source event ID подтверждён для нескольких project events",
                **base,
                candidate_ids=tuple(sorted(event.id for event in source_matches)),
            )
        if source_matches:
            event = source_matches[0]
            if (
                event.tournament_id != tournament_id
                or home_id is not None
                and event.home_team_id != home_id
                or away_id is not None
                and event.away_team_id != away_id
            ):
                return EventResolution(
                    "conflict",
                    None,
                    "Подтверждённый source key противоречит tournament/team",
                    **base,
                )
            return EventResolution(
                "resolved", event.id, "Точное подтверждённое source event ID", **base
            )
        if home_id is None or away_id is None:
            return EventResolution(
                "unresolved", None, "Home/away team designation не подтверждены", **base
            )
        scheduled_at = event_time
        if scheduled_at is None:
            return EventResolution("unresolved", None, "Точное UTC время отсутствует", **base)
        candidates = [
            event
            for event in self.snapshot.events
            if event.sport == ref.sport
            and event.tournament_id == tournament_id
            and event.home_team_id == home_id
            and event.away_team_id == away_id
            and _parse_utc(event.scheduled_at) == scheduled_at
        ]
        candidate_ids = tuple(sorted(event.id for event in candidates))
        if len(candidates) == 1:
            return EventResolution(
                "resolved",
                candidates[0].id,
                "Уникальное точное время и подтверждённые участники",
                **base,
            )
        if candidates:
            return EventResolution(
                "ambiguous",
                None,
                "Несколько project events совпали точно",
                **base,
                candidate_ids=candidate_ids,
            )
        return EventResolution("unresolved", None, "Подтверждённого точного совпадения нет", **base)

    def resolve_many(
        self,
        refs: tuple[CanonicalEventRef, ...],
        *,
        pinned_claims: tuple[tuple[str, str, str, str, str], ...] = (),
    ) -> tuple[EventResolution, ...]:
        """Применить reverse uniqueness к auto-match кандидатам в одном batch."""
        results = [self.resolve(ref) for ref in refs]
        claims: dict[tuple[str, str, str, str], list[tuple[int | None, str]]] = {}
        for source, sport, tournament_id, event_id, source_event_id in pinned_claims:
            key = (source, sport, tournament_id, event_id)
            claims.setdefault(key, []).append((None, source_event_id))
        for index, (ref, result) in enumerate(zip(refs, results, strict=True)):
            if result.status != "resolved" or result.project_event_id is None:
                continue
            tournament_status, tournament_id = self._resolve_alias(
                ref.source,
                "tournament",
                {"sport": ref.sport},
                ref.tournament,
                at=_parse_utc(ref.scheduled_at),
            )
            if tournament_status != "resolved" or tournament_id is None:
                continue
            key = (ref.source, ref.sport, tournament_id, result.project_event_id)
            claims.setdefault(key, []).append((index, ref.source_event_id))

        for (_source, _sport, _tournament_id, event_id), matches in claims.items():
            source_ids = {source_id for _, source_id in matches}
            if len(source_ids) < 2:
                continue
            for index, _ in matches:
                if index is None:
                    continue
                result = results[index]
                if result.reason != "Уникальное точное время и подтверждённые участники":
                    continue
                results[index] = EventResolution(
                    status="ambiguous",
                    project_event_id=None,
                    reason=(
                        "Несколько source event IDs одного source/scope претендуют "
                        "на один project event"
                    ),
                    snapshot_id=result.snapshot_id,
                    policy_version=result.policy_version,
                    candidate_ids=(event_id,),
                )
        return tuple(results)


def put_event_mapping(
    session: Session,
    *,
    snapshot: EventIdentitySnapshot,
    canonical_event_id: int,
    project_event_id: str | None,
    status: EventResolutionStatus,
    reason: str,
    policy_version: str,
    decision_id: str | None = None,
) -> EventRegistryMapping:
    """Идемпотентно добавить immutable mapping для exact snapshot/event pair."""
    _validate_snapshot(snapshot)
    if not reason.strip() or not policy_version.strip():
        raise ValueError("snapshot, основание и версия policy обязательны")
    if policy_version != snapshot.policy_version:
        raise ValueError("Mapping policy не соответствует frozen event projection")
    if (status == "resolved") != (project_event_id is not None):
        raise ValueError("Только resolved mapping должен содержать project_event_id")
    if status not in {"resolved", "unresolved", "ambiguous", "conflict"}:
        raise ValueError("Неизвестный mapping status")
    if status == "resolved" and project_event_id not in {event.id for event in snapshot.events}:
        raise ValueError("Resolved project_event_id отсутствует в frozen projection")
    with session.begin_nested():
        _register_snapshot(session, snapshot)
        existing = session.get(EventRegistryMapping, (snapshot.snapshot_id, canonical_event_id))
        values = (project_event_id, status, reason, policy_version, decision_id)
        if existing is not None:
            prior = (
                existing.project_event_id,
                existing.status,
                existing.reason,
                existing.policy_version,
                existing.decision_id,
            )
            if prior != values:
                raise ValueError("Mapping закреплённого snapshot неизменяем")
            return cast(EventRegistryMapping, existing)
        mapping = EventRegistryMapping(
            snapshot_id=snapshot.snapshot_id,
            canonical_event_id=canonical_event_id,
            project_event_id=project_event_id,
            status=status,
            reason=reason,
            policy_version=policy_version,
            decision_id=decision_id,
        )
        session.add(mapping)
        session.flush()
        return cast(EventRegistryMapping, mapping)


def _register_snapshot(session: Session, snapshot: EventIdentitySnapshot) -> None:
    """Создать или проверить immutable server projection header."""
    existing = session.get(RegistryIdentitySnapshot, snapshot.snapshot_id)
    expected = (
        "event_projection",
        snapshot.projection_sha256,
        snapshot.projection_schema_version,
        snapshot.policy_version,
        snapshot.normalization_version,
        snapshot.projection_json,
    )
    if existing is not None:
        actual = (
            existing.snapshot_kind,
            existing.projection_sha256,
            existing.projection_schema_version,
            existing.policy_version,
            existing.normalization_version,
            existing.projection_json,
        )
        if actual != expected:
            raise ValueError("Snapshot ID уже закреплён за другим содержимым")
        return
    session.add(
        RegistryIdentitySnapshot(
            snapshot_id=snapshot.snapshot_id,
            snapshot_kind="event_projection",
            projection_sha256=snapshot.projection_sha256,
            projection_schema_version=snapshot.projection_schema_version,
            policy_version=snapshot.policy_version,
            normalization_version=snapshot.normalization_version,
            projection_json=snapshot.projection_json,
        )
    )
    session.flush()


def get_event_mapping(
    session: Session, *, snapshot_id: str, canonical_event_id: int
) -> EventRegistryMapping:
    """Прочитать mapping только для явно закреплённого snapshot ID."""
    if not snapshot_id:
        raise ValueError("Resolver обязан передать pinned snapshot_id")
    mapping = session.get(EventRegistryMapping, (snapshot_id, canonical_event_id))
    if mapping is None:
        raise KeyError((snapshot_id, canonical_event_id))
    return cast(EventRegistryMapping, mapping)


def backfill_event_bridge(
    session: Session,
    *,
    snapshot: EventIdentitySnapshot,
    apply: bool = False,
) -> EventBackfillPlan:
    """Построить dry-run canonical bridge; apply добавляет только отсутствующие mappings."""
    resolver = RegistryEventResolver(snapshot)
    rows = session.scalars(select(CanonicalEvent).order_by(CanonicalEvent.__table__.c.id)).all()
    refs_by_id = {
        row.id: CanonicalEventRef(
            canonical_event_id=row.id,
            sport=row.sport,
            tournament=row.tournament,
            source=row.source,
            source_event_id=row.source_event_id,
            scheduled_at=(
                row.scheduled_at.replace(tzinfo=UTC)
                if row.scheduled_at.tzinfo is None
                else row.scheduled_at
            ),
            home_participant=row.home_participant,
            away_participant=row.away_participant,
        )
        for row in rows
    }
    existing_rows = session.scalars(
        select(EventRegistryMapping).where(
            EventRegistryMapping.__table__.c.snapshot_id == snapshot.snapshot_id
        )
    ).all()
    existing_by_event_id = {item.canonical_event_id: item for item in existing_rows}
    new_refs = tuple(refs_by_id[row.id] for row in rows if row.id not in existing_by_event_id)
    pinned_claims: list[tuple[str, str, str, str, str]] = []
    for mapping in existing_rows:
        if mapping.status != "resolved" or mapping.project_event_id is None:
            continue
        ref = refs_by_id.get(mapping.canonical_event_id)
        if ref is None:
            continue
        tournament_status, tournament_id = resolver._resolve_alias(
            ref.source,
            "tournament",
            {"sport": ref.sport},
            ref.tournament,
            at=_parse_utc(ref.scheduled_at),
        )
        if tournament_status == "resolved" and tournament_id is not None:
            pinned_claims.append(
                (
                    ref.source,
                    ref.sport,
                    tournament_id,
                    mapping.project_event_id,
                    ref.source_event_id,
                )
            )
    new_results = iter(resolver.resolve_many(new_refs, pinned_claims=tuple(pinned_claims)))
    mappings = tuple(
        EventResolution(
            status=cast(EventResolutionStatus, existing_by_event_id[row.id].status),
            project_event_id=existing_by_event_id[row.id].project_event_id,
            reason=existing_by_event_id[row.id].reason,
            snapshot_id=snapshot.snapshot_id,
            policy_version=snapshot.policy_version,
        )
        if row.id in existing_by_event_id
        else next(new_results)
        for row in rows
    )
    counts = {
        state: sum(result.status == state for result in mappings)
        for state in ("resolved", "unresolved", "ambiguous", "conflict")
    }
    if apply:
        with session.begin_nested():
            _register_snapshot(session, snapshot)
            for row, result in zip(rows, mappings, strict=True):
                if row.id in existing_by_event_id:
                    continue
                put_event_mapping(
                    session,
                    snapshot=snapshot,
                    canonical_event_id=row.id,
                    project_event_id=result.project_event_id,
                    status=result.status,
                    reason=result.reason,
                    policy_version=result.policy_version,
                )
    return EventBackfillPlan(snapshot.snapshot_id, not apply, mappings, counts)
