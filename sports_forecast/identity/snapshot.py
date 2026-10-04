"""Полный переносимый снимок локального registry и его offline reader."""

from __future__ import annotations

import fcntl
import hashlib
import json
import shutil
import sqlite3
import tempfile
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sports_forecast.identity.events import (
    NORMALIZATION_VERSION,
    CanonicalEventRef,
    EventIdentitySnapshot,
    RegistryEventResolver,
)
from sports_forecast.identity.registry import Entity, EntityRegistry, Resolution, _canonical_utc


SNAPSHOT_FORMAT_VERSION = 1
SNAPSHOT_POLICY_VERSION = "strict-v1"
_SNAPSHOT_FILES = (
    "entities.jsonl",
    "designations.jsonl",
    "decisions.jsonl",
    "events.jsonl",
    "memberships.jsonl",
)


@dataclass(frozen=True)
class SnapshotLimits:
    """Ограничения проверки переносимого снимка."""

    max_total_bytes: int = 1024 * 1024 * 1024
    max_file_bytes: int = 512 * 1024 * 1024
    max_line_bytes: int = 1024 * 1024
    max_records_per_file: int = 2_000_000


_DEFAULT_LIMITS = SnapshotLimits()


@dataclass(frozen=True)
class RegistrySnapshotArtifact:
    """Экспортированный snapshot и его content-derived identity."""

    snapshot_id: str
    projection_sha256: str
    path: Path
    manifest: dict[str, Any]


@dataclass(frozen=True)
class VerifiedRegistrySnapshot:
    """Проверенный неизменяемый пакет полного registry."""

    snapshot_id: str
    projection_sha256: str
    path: Path
    manifest: dict[str, Any]
    records: dict[str, tuple[dict[str, Any], ...]]
    event_snapshot: EventIdentitySnapshot


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _read_table(connection: sqlite3.Connection, table: str, order_by: str) -> list[dict[str, Any]]:
    rows = connection.execute(f"SELECT * FROM {table} ORDER BY {order_by}").fetchall()
    return [dict(row) for row in rows]


def _registry_records(connection: sqlite3.Connection) -> dict[str, list[dict[str, Any]]]:
    """Считать только разрешённые данные identity из одной SQLite transaction."""
    entities = _read_table(connection, "entities", "id")
    all_designation_rows = _read_table(connection, "designations", "id")
    overlay_rows = _read_table(connection, "designation_conflicts", "id")
    decision_rows = _read_table(connection, "decisions", "id")
    decisions: list[dict[str, Any]] = []
    for row in decision_rows:
        decisions.append({"record_type": "decisions", **row})
    for table, key in (
        ("entity_audit", "id"),
        ("event_relation_audit", "id"),
        ("imports", "seed_key"),
    ):
        decisions.extend(
            {"record_type": table, **row} for row in _read_table(connection, table, key)
        )
    decision_links: dict[tuple[str, int], list[str]] = {}
    linked_designation_ids: set[str] = set()
    for row in decision_rows:
        candidate_id = row.get("evidence_candidate_id")
        revision = row.get("evidence_revision")
        if (candidate_id is None) != (revision is None):
            raise ValueError("Owner decision содержит неполную ссылку на evidence")
        if candidate_id is not None and revision is not None:
            decision_links.setdefault((str(candidate_id), int(revision)), []).append(str(row["id"]))
        linked_designation_ids.add(str(row["designation_id"]))
    designation_by_id = {str(row["id"]): row for row in all_designation_rows}
    if len(designation_by_id) != len(all_designation_rows):
        raise ValueError("Registry содержит повторный designation ID")
    linked_candidate_ids = {candidate_id for candidate_id, _revision in decision_links}
    for candidate_id in linked_candidate_ids:
        candidate = connection.execute(
            "SELECT * FROM review_candidates WHERE id=?", (candidate_id,)
        ).fetchone()
        if candidate is None:
            raise ValueError("Owner decision ссылается на отсутствующего review candidate")
        if candidate["designation_id"] not in designation_by_id:
            raise ValueError("Review candidate ссылается на отсутствующую designation")
    available_designations = {
        str(row["id"]) for row in all_designation_rows if row["state"] in {"confirmed", "conflict"}
    }
    overlay_designations = {
        str(row[key]) for row in overlay_rows for key in ("designation_id", "peer_designation_id")
    }
    retained_designations = available_designations | linked_designation_ids | overlay_designations
    designation_rows = [
        row for row in all_designation_rows if str(row["id"]) in retained_designations
    ]
    designations = [{"record_type": "designation", **row} for row in designation_rows] + [
        {"record_type": "conflict_overlay", **row} for row in overlay_rows
    ]
    for candidate in connection.execute("SELECT * FROM review_candidates ORDER BY id").fetchall():
        candidate_id = str(candidate["id"])
        candidate_links = {
            revision: linked_decision_ids
            for (linked_candidate, revision), linked_decision_ids in decision_links.items()
            if linked_candidate == candidate_id
        }
        if not candidate_links:
            continue
        evidence_rows: dict[int, dict[str, Any]] = {}
        for history in connection.execute(
            "SELECT * FROM review_candidate_history WHERE candidate_id=? ORDER BY revision",
            (candidate_id,),
        ).fetchall():
            evidence_rows[int(history["revision"])] = dict(history)
        evidence_rows[int(candidate["revision"])] = dict(candidate)
        for revision, linked_decision_ids in candidate_links.items():
            evidence = evidence_rows.get(revision)
            if evidence is None or evidence["status"] == "pending":
                raise ValueError("Owner decision ссылается на отсутствующую или pending evidence")
            candidate_designation = str(candidate["designation_id"])
            if candidate_designation not in retained_designations:
                raise ValueError("Owner evidence designation не включена в snapshot")
            decisions.append(
                {
                    "record_type": "candidate_evidence",
                    "id": f"{candidate_id}:{revision}",
                    "candidate_id": candidate_id,
                    "designation_id": candidate_designation,
                    "origin": candidate["origin"],
                    "idempotency_key": candidate["idempotency_key"],
                    "revision": revision,
                    "observed_at": evidence["observed_at"],
                    "facts": json.loads(evidence["facts_json"]),
                    "proposed_entity_ids": json.loads(evidence["proposed_entity_ids_json"]),
                    "basis": evidence["basis"],
                    "status": evidence["status"],
                    "decision_ids": sorted(linked_decision_ids),
                }
            )
    events = _read_table(connection, "event_relations", "event_id")
    memberships = _read_table(connection, "memberships", "id")
    return {
        "entities.jsonl": entities,
        "designations.jsonl": sorted(
            designations,
            key=lambda row: (
                str(row["record_type"]),
                str(row.get("id", "")),
            ),
        ),
        "decisions.jsonl": sorted(
            decisions,
            key=lambda row: (str(row["record_type"]), str(row.get("id", row.get("seed_key", "")))),
        ),
        "events.jsonl": events,
        "memberships.jsonl": memberships,
    }


def _encode_records(records: list[dict[str, Any]], limits: SnapshotLimits) -> bytes:
    if len(records) > limits.max_records_per_file:
        raise ValueError("Число записей снимка превышает допустимый предел")
    lines = [_canonical_json(record) + b"\n" for record in records]
    if any(len(line) > limits.max_line_bytes for line in lines):
        raise ValueError("Строка JSONL превышает допустимый предел")
    payload = b"".join(lines)
    if len(payload) > limits.max_file_bytes:
        raise ValueError("Файл снимка превышает допустимый предел")
    return payload


def _validate_registry_records(records: dict[str, tuple[dict[str, Any], ...]]) -> None:
    entities = {str(row["id"]): row for row in records["entities.jsonl"]}
    if len(entities) != len(records["entities.jsonl"]):
        raise ValueError("Snapshot содержит повторные UUID сущностей")
    for entity_id, entity in entities.items():
        _validate_uuid(entity_id, "entity")
        if entity.get("kind") not in {"tournament", "team", "event", "player"}:
            raise ValueError("Snapshot содержит неподдерживаемый тип сущности")
    designation_rows = [
        row for row in records["designations.jsonl"] if row.get("record_type") == "designation"
    ]
    designation_ids = {str(row.get("id", "")) for row in designation_rows}
    if len(designation_ids) != len(designation_rows):
        raise ValueError("Snapshot содержит повторный ID designation")
    for item in records["designations.jsonl"]:
        if item.get("record_type") == "designation":
            designation_id = str(item.get("id", ""))
            _validate_uuid(designation_id, "designation")
            if designation_id not in designation_ids:
                raise ValueError("Snapshot содержит неполный набор designation IDs")
            kind = item.get("kind")
            if kind not in {"tournament", "team", "event", "player"}:
                raise ValueError("Designation содержит неподдерживаемый тип сущности")
            target = item.get("entity_id")
            if target is not None and target not in entities:
                raise ValueError("Designation ссылается на отсутствующую сущность")
            if target is not None and entities[target].get("kind") != kind:
                raise ValueError("Designation ссылается на сущность неверного типа")
            if not isinstance(item.get("scope_json"), str):
                raise ValueError("Designation не содержит scope JSON")
            try:
                scope = json.loads(item["scope_json"])
            except json.JSONDecodeError as exc:
                raise ValueError("Designation содержит повреждённый scope JSON") from exc
            if not isinstance(scope, dict) or not all(
                isinstance(key, str) and isinstance(value, str) for key, value in scope.items()
            ):
                raise ValueError("Designation scope имеет неверную форму")
            if item.get("state") not in {
                "pending",
                "confirmed",
                "conflict",
                "rejected",
                "deferred",
                "superseded",
            }:
                raise ValueError("Designation содержит неизвестное состояние")
            _validate_interval(item.get("valid_from"), item.get("valid_until"))
        elif item.get("record_type") == "conflict_overlay":
            if item.get("designation_id") not in designation_ids:
                raise ValueError("Conflict overlay ссылается на отсутствующую designation")
            if item.get("peer_designation_id") not in designation_ids:
                raise ValueError("Conflict overlay ссылается на отсутствующую peer designation")
            if (
                item.get("selected_entity_id") is not None
                and item.get("selected_entity_id") not in entities
            ):
                raise ValueError("Conflict overlay ссылается на отсутствующий target")
            if item.get("state") not in {"open", "resolved", "dismissed"}:
                raise ValueError("Conflict overlay содержит неизвестное состояние")
            _validate_interval(item.get("valid_from"), item.get("valid_until"))
        else:
            raise ValueError("Неизвестный тип designation JSONL record")
    for item in records["decisions.jsonl"]:
        record_type = item.get("record_type")
        if record_type == "decisions":
            if item.get("designation_id") not in designation_ids:
                raise ValueError("Decision ссылается на отсутствующую designation")
            _validate_uuid(str(item.get("id", "")), "decision")
        elif record_type == "entity_audit":
            if item.get("entity_id") not in entities:
                raise ValueError("Entity audit ссылается на отсутствующую сущность")
            _validate_uuid(str(item.get("id", "")), "entity audit")
        elif record_type == "event_relation_audit":
            if item.get("event_id") not in entities:
                raise ValueError("Event relation audit ссылается на отсутствующую сущность")
            _validate_uuid(str(item.get("id", "")), "event audit")
        elif record_type == "imports":
            if not item.get("seed_key") or not isinstance(item.get("content_hash"), str):
                raise ValueError("Seed import provenance имеет неверную форму")
        elif record_type == "candidate_evidence":
            if (
                item.get("designation_id") not in designation_ids
                or item.get("status") not in {"confirmed", "rejected", "deferred"}
                or not isinstance(item.get("origin"), str)
                or len(item["origin"]) > 120
                or not isinstance(item.get("idempotency_key"), str)
                or len(item["idempotency_key"]) > 200
                or not isinstance(item.get("basis"), str)
                or len(item["basis"]) > 2000
                or not isinstance(item.get("facts"), dict)
                or len(item["facts"]) > 50
                or any(
                    not isinstance(key, str)
                    or len(key) > 100
                    or not isinstance(value, str)
                    or len(value) > 1000
                    for key, value in item["facts"].items()
                )
                or not isinstance(item.get("proposed_entity_ids"), list)
                or len(item["proposed_entity_ids"]) > 20
                or any(
                    not isinstance(entity_id, str) or not entity_id or len(entity_id) > 80
                    for entity_id in item["proposed_entity_ids"]
                )
                or not isinstance(item.get("decision_ids"), list)
                or not item["decision_ids"]
                or any(not isinstance(decision_id, str) for decision_id in item["decision_ids"])
                or len(item["decision_ids"]) != len(set(item["decision_ids"]))
            ):
                raise ValueError("Candidate evidence имеет неверную форму или превышает лимиты")
            _validate_uuid(str(item.get("candidate_id", "")), "candidate evidence")
            if not isinstance(item.get("revision"), int) or item["revision"] < 1:
                raise ValueError("Candidate evidence содержит неверную revision")
            if item.get("id") != f"{item['candidate_id']}:{item['revision']}":
                raise ValueError("Candidate evidence содержит неверный composite ID")
            if not isinstance(item.get("observed_at"), str) or len(item["observed_at"]) > 40:
                raise ValueError("Candidate evidence содержит неверное время")
        else:
            raise ValueError("Неизвестный тип audit JSONL record")
    decision_records = {
        str(item["id"]): item
        for item in records["decisions.jsonl"]
        if item.get("record_type") == "decisions"
    }
    evidence_records = {
        (str(item["candidate_id"]), int(item["revision"])): item
        for item in records["decisions.jsonl"]
        if item.get("record_type") == "candidate_evidence"
    }
    if len(evidence_records) != sum(
        item.get("record_type") == "candidate_evidence" for item in records["decisions.jsonl"]
    ):
        raise ValueError("Snapshot содержит повторную candidate evidence revision")
    for decision in decision_records.values():
        candidate_id = decision.get("evidence_candidate_id")
        revision = decision.get("evidence_revision")
        if (candidate_id is None) != (revision is None):
            raise ValueError("Decision содержит неполную ссылку на evidence")
        if candidate_id is None:
            continue
        _validate_uuid(str(candidate_id), "decision evidence candidate")
        if not isinstance(revision, int) or revision < 1:
            raise ValueError("Decision содержит неверную evidence revision")
        evidence = evidence_records.get((str(candidate_id), revision))
        if evidence is None or evidence["designation_id"] != decision["designation_id"]:
            raise ValueError("Decision ссылается на отсутствующую или чужую evidence revision")
        if decision["id"] not in evidence["decision_ids"]:
            raise ValueError("Candidate evidence не ссылается обратно на decision")
    for evidence in evidence_records.values():
        for decision_id in evidence["decision_ids"]:
            decision = decision_records.get(str(decision_id))
            if (
                decision is None
                or decision.get("evidence_candidate_id") != evidence["candidate_id"]
                or decision.get("evidence_revision") != evidence["revision"]
                or decision.get("designation_id") != evidence["designation_id"]
            ):
                raise ValueError("Candidate evidence ссылается на несвязанный decision")
    for event in records["events.jsonl"]:
        if (
            event.get("event_id") not in entities
            or entities[event["event_id"]].get("kind") != "event"
        ):
            raise ValueError("Event relation ссылается на отсутствующее project event")
        for key, kind in (
            ("tournament_id", "tournament"),
            ("home_team_id", "team"),
            ("away_team_id", "team"),
        ):
            target = entities.get(str(event.get(key)))
            if target is None or target.get("kind") != kind:
                raise ValueError("Event relation ссылается на сущность неверного типа")
        if event.get("scheduled_at") is not None:
            _validate_interval(event["scheduled_at"], None)
    for item in records["memberships.jsonl"]:
        player = entities.get(str(item.get("player_id")))
        team = entities.get(str(item.get("team_id")))
        if (
            player is None
            or player.get("kind") != "player"
            or team is None
            or team.get("kind") != "team"
        ):
            raise ValueError("Membership ссылается на сущность неверного типа")
        _validate_interval(item.get("valid_from"), item.get("valid_until"))


def _validate_uuid(value: str, field: str) -> None:
    try:
        if str(UUID(value)) != value:
            raise ValueError
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"Snapshot содержит некорректный UUID: {field}") from exc


def _validate_interval(valid_from: Any, valid_until: Any) -> None:
    def parse(value: Any) -> datetime | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("Snapshot interval содержит timestamp неверного типа")
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("Snapshot interval содержит неверный timestamp") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("Snapshot interval timestamp должен содержать timezone")
        return parsed

    start, end = parse(valid_from), parse(valid_until)
    if start is not None and end is not None and start >= end:
        raise ValueError("Snapshot interval должен быть полуоткрытым и непустым")


def _build_event_snapshot(
    records: dict[str, tuple[dict[str, Any], ...]],
) -> EventIdentitySnapshot:
    """Создать strict resolver projection только из проверенных строк snapshot."""
    from sports_forecast.identity.events import (
        ConfirmedEventDesignation,
        EventConflictOverlay,
        EventSourceKey,
        ProjectEvent,
        _snapshot_projection,
    )

    entities = {str(row["id"]): row for row in records["entities.jsonl"]}
    designations = tuple(
        ConfirmedEventDesignation(
            str(row["id"]),
            str(row["source"]),
            str(row["kind"]),
            tuple(sorted(json.loads(str(row["scope_json"])).items())),
            str(row["value_kind"]),
            str(row["raw_value"]),
            row.get("entity_id"),
            str(row["state"]),
            row.get("valid_from"),
            row.get("valid_until"),
        )
        for row in records["designations.jsonl"]
        if row.get("record_type") == "designation"
    )
    conflicts = tuple(
        EventConflictOverlay(
            str(row["designation_id"]),
            str(row["peer_designation_id"]),
            row.get("valid_from"),
            row.get("valid_until"),
            str(row["state"]),
            row.get("selected_entity_id"),
        )
        for row in records["designations.jsonl"]
        if row.get("record_type") == "conflict_overlay"
    )
    events: list[ProjectEvent] = []
    for relation in records["events.jsonl"]:
        event_id = str(relation["event_id"])
        event_entity = entities[event_id]
        tournament_id = str(relation["tournament_id"])
        event_keys = tuple(
            sorted(
                (
                    EventSourceKey(
                        item.source,
                        str(event_entity["sport"]),
                        tournament_id,
                        item.raw_value,
                    )
                    for item in designations
                    if item.kind == "event"
                    and item.state == "confirmed"
                    and item.entity_id == event_id
                    and dict(item.scope).get("sport") == event_entity["sport"]
                    and dict(item.scope).get("tournament") == tournament_id
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
        events.append(
            ProjectEvent(
                event_id,
                str(event_entity["sport"]),
                tournament_id,
                str(relation["home_team_id"]),
                str(relation["away_team_id"]),
                relation.get("scheduled_at"),
                event_keys,
            )
        )
    policy_version = SNAPSHOT_POLICY_VERSION
    projection_json = _snapshot_projection(
        tuple(events),
        designations,
        conflicts,
        registry_schema_version=int(records["_meta"][0]["registry_schema_version"]),
        projection_schema_version=1,
        policy_version=policy_version,
        normalization_version=NORMALIZATION_VERSION,
    )
    projection_sha256 = hashlib.sha256(projection_json.encode("utf-8")).hexdigest()
    return EventIdentitySnapshot(
        f"ev1:{projection_sha256}",
        tuple(events),
        designations,
        conflicts,
        projection_sha256,
        projection_json,
        int(records["_meta"][0]["registry_schema_version"]),
        1,
        policy_version,
        NORMALIZATION_VERSION,
    )


def export_registry_snapshot(
    registry: EntityRegistry,
    output_root: Path,
    *,
    limits: SnapshotLimits | None = None,
) -> RegistrySnapshotArtifact:
    """Экспортировать полный content-addressed JSONL snapshot без очереди кандидатов."""
    limits = limits or _DEFAULT_LIMITS
    with registry._connect(write=False) as connection:
        schema_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        tables = _registry_records(connection)
    records_with_meta: dict[str, tuple[dict[str, Any], ...]] = {
        **{name: tuple(rows) for name, rows in tables.items()},
        "_meta": ({"registry_schema_version": schema_version},),
    }
    _validate_registry_records(records_with_meta)
    encoded = {name: _encode_records(rows, limits) for name, rows in tables.items()}
    total_size = sum(len(payload) for payload in encoded.values())
    if total_size > limits.max_total_bytes:
        raise ValueError("Полный размер снимка превышает допустимый предел")
    files = {
        name: {
            "sha256": hashlib.sha256(payload).hexdigest(),
            "bytes": len(payload),
            "count": len(tables[name]),
        }
        for name, payload in encoded.items()
    }
    manifest: dict[str, Any] = {
        "format": "sports-forecast-entity-registry",
        "format_version": SNAPSHOT_FORMAT_VERSION,
        "registry_schema_version": schema_version,
        "policy_version": SNAPSHOT_POLICY_VERSION,
        "normalization_version": NORMALIZATION_VERSION,
        "files": files,
    }
    digest = hashlib.sha256(_canonical_json(manifest)).hexdigest()
    snapshot_id = f"ir1:{digest}"
    manifest["snapshot_id"] = snapshot_id
    target = Path(output_root) / digest
    Path(output_root).mkdir(parents=True, exist_ok=True)
    if target.exists():
        verified = verify_registry_snapshot(target, limits=limits)
        if verified.snapshot_id != snapshot_id:
            raise ValueError("Существующий snapshot path содержит другую версию")
        return RegistrySnapshotArtifact(snapshot_id, digest, target, verified.manifest)
    temporary = Path(tempfile.mkdtemp(prefix=f".{digest}.", dir=output_root))
    try:
        for name, payload in encoded.items():
            (temporary / name).write_bytes(payload)
        (temporary / "manifest.json").write_bytes(_canonical_json(manifest) + b"\n")
        temporary.replace(target)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    verified = verify_registry_snapshot(target, limits=limits)
    return RegistrySnapshotArtifact(snapshot_id, digest, target, verified.manifest)


def verify_registry_snapshot(
    snapshot_path: Path,
    *,
    limits: SnapshotLimits | None = None,
) -> VerifiedRegistrySnapshot:
    """Полностью проверить manifest, file hashes, limits и связи до возврата reader input."""
    limits = limits or _DEFAULT_LIMITS
    path = Path(snapshot_path)
    manifest_path = path / "manifest.json"
    if (
        path.is_symlink()
        or not path.is_dir()
        or not manifest_path.is_file()
        or manifest_path.is_symlink()
    ):
        raise ValueError("Registry snapshot не содержит обычный manifest.json")
    allowed_names = {*_SNAPSHOT_FILES, "manifest.json"}
    if {item.name for item in path.iterdir()} != allowed_names:
        raise ValueError("Snapshot содержит отсутствующий или неизвестный файл")
    manifest_max_bytes = min(limits.max_line_bytes * 4, limits.max_total_bytes)
    if manifest_path.stat().st_size > manifest_max_bytes:
        raise ValueError("Manifest превышает допустимый размер")
    with manifest_path.open("rb") as manifest_source:
        manifest_bytes = manifest_source.read(manifest_max_bytes + 1)
    if len(manifest_bytes) > manifest_max_bytes:
        raise ValueError("Manifest превышает допустимый размер")
    try:
        manifest = json.loads(manifest_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Manifest не является корректным UTF-8 JSON") from exc
    if not isinstance(manifest, dict):
        raise ValueError("Manifest имеет неверную форму")
    if manifest_bytes != _canonical_json(manifest) + b"\n":
        raise ValueError("Manifest не сериализован в каноническом виде")
    snapshot_id = manifest.get("snapshot_id")
    identity_manifest = {key: value for key, value in manifest.items() if key != "snapshot_id"}
    digest = hashlib.sha256(_canonical_json(identity_manifest)).hexdigest()
    if (
        manifest.get("format") != "sports-forecast-entity-registry"
        or manifest.get("format_version") != SNAPSHOT_FORMAT_VERSION
        or manifest.get("registry_schema_version") != EntityRegistry.schema_version
        or manifest.get("normalization_version") != NORMALIZATION_VERSION
        or manifest.get("policy_version") != SNAPSHOT_POLICY_VERSION
        or snapshot_id != f"ir1:{digest}"
        or not isinstance(manifest.get("files"), dict)
        or set(manifest["files"]) != set(_SNAPSHOT_FILES)
    ):
        raise ValueError("Manifest snapshot ID или schema/policy version не поддерживается")
    records: dict[str, tuple[dict[str, Any], ...]] = {}
    total_bytes = len(manifest_bytes)
    if total_bytes > limits.max_total_bytes:
        raise ValueError("Полный размер снимка превышает допустимый предел")
    for name in _SNAPSHOT_FILES:
        file_path = path / name
        expected = manifest["files"][name]
        if not isinstance(expected, dict) or not file_path.is_file() or file_path.is_symlink():
            raise ValueError("Snapshot содержит отсутствующий или повреждённый JSONL")
        if file_path.stat().st_size > limits.max_file_bytes:
            raise ValueError("Файл снимка превышает допустимый предел")
        total_bytes += file_path.stat().st_size
        if total_bytes > limits.max_total_bytes:
            raise ValueError("Полный размер снимка превышает допустимый предел")
        file_digest = hashlib.sha256()
        payload_records: list[dict[str, Any]] = []
        payload_bytes = 0
        with file_path.open("rb") as source:
            for line in source:
                payload_bytes += len(line)
                if len(line) > limits.max_line_bytes:
                    raise ValueError("Строка JSONL превышает допустимый предел")
                file_digest.update(line)
                try:
                    record = json.loads(line)
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise ValueError("JSONL snapshot содержит повреждённую строку") from exc
                if not isinstance(record, dict) or _canonical_json(record) + b"\n" != line:
                    raise ValueError("JSONL snapshot содержит неканоническую запись")
                payload_records.append(record)
                if len(payload_records) > limits.max_records_per_file:
                    raise ValueError("Число записей снимка превышает допустимый предел")
        if (
            payload_bytes != expected.get("bytes")
            or len(payload_records) != expected.get("count")
            or file_digest.hexdigest() != expected.get("sha256")
        ):
            raise ValueError("Hash/count/size JSONL не совпадает с manifest")
        records[name] = tuple(payload_records)
    records_with_meta = {
        **records,
        "_meta": ({"registry_schema_version": EntityRegistry.schema_version},),
    }
    _validate_registry_records(records_with_meta)
    event_snapshot = _build_event_snapshot(records_with_meta)
    from sports_forecast.identity.events import _validate_snapshot

    _validate_snapshot(event_snapshot)
    return VerifiedRegistrySnapshot(
        snapshot_id,
        digest,
        path,
        manifest,
        records,
        event_snapshot,
    )


def install_registry_snapshot(source_path: Path, selected_path: Path) -> VerifiedRegistrySnapshot:
    """Проверить пакет и атомарно переключить локальный выбранный snapshot."""
    source = verify_registry_snapshot(Path(source_path))
    selected_path = Path(selected_path)
    selected_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = selected_path.parent.parent / f".{selected_path.parent.name}.lock"
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{selected_path.name}.new.", dir=selected_path.parent)
    )
    backup = selected_path.parent.parent / f".{selected_path.parent.name}.previous.{uuid4().hex}"
    try:
        shutil.copytree(source.path, temporary, dirs_exist_ok=True)
        copied = verify_registry_snapshot(temporary)
        if copied.snapshot_id != source.snapshot_id:
            raise ValueError("Copied registry package changed during installation")
        with lock_path.open("a+b") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            if selected_path.exists():
                selected_path.replace(backup)
            try:
                temporary.replace(selected_path)
                installed = verify_registry_snapshot(selected_path)
                if installed.snapshot_id != source.snapshot_id:
                    raise ValueError("Installed registry package failed identity verification")
            except Exception:
                if selected_path.exists():
                    shutil.rmtree(selected_path)
                if backup.exists():
                    backup.replace(selected_path)
                raise
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        return verify_registry_snapshot(selected_path)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


class RegistrySnapshotReader:
    """Локальный offline reader, изолированный от изменяемой master DB."""

    def __init__(self, snapshot: VerifiedRegistrySnapshot) -> None:
        """Закрепить ранее проверенный snapshot в памяти этого reader."""
        if snapshot.snapshot_id != f"ir1:{snapshot.projection_sha256}":
            raise ValueError("Verified registry snapshot имеет неверный ID")
        self.snapshot = snapshot
        self.snapshot_id = snapshot.snapshot_id
        self._entities = {str(row["id"]): row for row in snapshot.records["entities.jsonl"]}
        self._resolver = RegistryEventResolver(snapshot.event_snapshot)

    def get_entity(self, entity_id: str) -> Entity:
        """Прочитать проектную сущность из закреплённого снимка."""
        row = self._entities.get(entity_id)
        if row is None:
            raise KeyError(entity_id)
        return Entity(
            str(row["id"]),
            str(row["kind"]),
            str(row["sport"]),
            str(row["project_name"]),
            int(row["revision"]),
        )

    def resolve_designation(
        self,
        *,
        source: str,
        kind: str,
        scope: dict[str, str],
        value_kind: str,
        raw_value: str,
        at: str | None = None,
    ) -> Resolution:
        """Разрешить designation по точному scope и активному периоду snapshot."""
        instant = _canonical_utc(at)
        normalized = (
            raw_value
            if value_kind == "external_id"
            else "".join(
                char
                for char in unicodedata.normalize("NFKC", raw_value).strip().casefold()
                if char.isalnum()
            )
        )
        matching = [
            row
            for row in self.snapshot.records["designations.jsonl"]
            if row.get("record_type") == "designation"
            and row.get("source") == source
            and row.get("kind") == kind
            and row.get("scope_json") == _canonical_json(scope).decode("utf-8")
            and row.get("value_kind") == value_kind
            and row.get("normalized_value") == normalized
        ]
        if not matching:
            return Resolution("unresolved", None, "Обозначение не зарегистрировано")
        designation_ids = {str(row["id"]) for row in matching}
        overlays = [
            row
            for row in self.snapshot.records["designations.jsonl"]
            if row.get("record_type") == "conflict_overlay"
            and (
                row.get("designation_id") in designation_ids
                or row.get("peer_designation_id") in designation_ids
            )
            and row.get("state") != "dismissed"
        ]
        if instant is None and overlays:
            return Resolution("ambiguous", None, "Для conflict overlay требуется дата события")
        if instant is not None:
            overlays = [
                row
                for row in overlays
                if (row.get("valid_from") is None or row["valid_from"] <= instant)
                and (row.get("valid_until") is None or instant < row["valid_until"])
            ]
        if any(row.get("state") == "open" for row in overlays):
            return Resolution("conflict", None, "На дату события действует открытый конфликт")
        selected = {row.get("selected_entity_id") for row in overlays}
        selected.discard(None)
        if len(selected) > 1:
            return Resolution("conflict", None, "Для даты события сохранены разные решения")
        if selected:
            return Resolution("resolved", next(iter(selected)), "Конфликт разрешён владельцем")
        active = matching
        if instant is None and any(
            row.get("valid_from") or row.get("valid_until") for row in active
        ):
            return Resolution("ambiguous", None, "Для временной designation требуется дата")
        if instant is not None:
            active = [
                row
                for row in active
                if (row.get("valid_from") is None or row["valid_from"] <= instant)
                and (row.get("valid_until") is None or instant < row["valid_until"])
            ]
        confirmed = [row for row in active if row.get("state") == "confirmed"]
        entity_ids = {row.get("entity_id") for row in confirmed}
        if len(entity_ids) == 1 and confirmed:
            return Resolution(
                "resolved", next(iter(entity_ids)), "Точное подтверждённое обозначение"
            )
        if len(entity_ids) > 1:
            return Resolution("conflict", None, "Несколько подтверждённых project ID")
        return Resolution("unresolved", None, "Нет подтверждённой привязки")

    def resolve_event(self, ref: CanonicalEventRef):
        """Разрешить событие исключительно по pinned offline projection."""
        return self._resolver.resolve(ref)
