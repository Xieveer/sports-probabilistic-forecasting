"""Локальное SQLite-хранилище сущностей и внешних обозначений."""

from __future__ import annotations

import contextlib
import json
import sqlite3
import unicodedata
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)

EntityKind = Literal["tournament", "team", "event", "player"]
DesignationState = Literal["pending", "confirmed", "conflict", "rejected", "deferred", "superseded"]
ResolutionStatus = Literal["resolved", "unresolved", "ambiguous", "conflict"]


class RegistryNotInitializedError(RuntimeError):
    """Реестр не был явно создан миграцией."""


@dataclass(frozen=True)
class Entity:
    """Проектная сущность с неизменяемым UUID."""

    id: str
    kind: str
    sport: str
    project_name: str
    revision: int


@dataclass(frozen=True)
class Designation:
    """Обозначение сущности в одном внешнем источнике и scope."""

    id: str
    source: str
    kind: str
    scope: dict[str, str]
    value_kind: str
    raw_value: str
    entity_id: str | None
    state: str
    valid_from: str | None
    valid_until: str | None
    revision: int


@dataclass(frozen=True)
class Decision:
    """Неизменяемая запись действия владельца."""

    id: str
    designation_id: str
    actor: str
    action: str
    reason: str
    prior_state: str
    prior_revision: int
    decided_at: str


@dataclass(frozen=True)
class EntityAudit:
    """Аудит изменения проектного имени сущности."""

    id: str
    entity_id: str
    actor: str
    action: str
    reason: str
    prior_name: str
    project_name: str
    decided_at: str


@dataclass(frozen=True)
class EventRelation:
    """Подтверждённые tournament/team relations проектного события."""

    event_id: str
    tournament_id: str
    home_team_id: str
    away_team_id: str
    scheduled_at: str | None
    revision: int


@dataclass(frozen=True)
class EventRelationAudit:
    """Неизменяемая история правки состава или времени project event."""

    id: str
    event_id: str
    actor: str
    reason: str
    prior_revision: int
    revision: int
    prior_tournament_id: str | None
    tournament_id: str
    prior_home_team_id: str | None
    home_team_id: str
    prior_away_team_id: str | None
    away_team_id: str
    prior_scheduled_at: str | None
    scheduled_at: str | None
    decided_at: str


@dataclass(frozen=True)
class Resolution:
    """Результат точного разрешения обозначения."""

    status: ResolutionStatus
    entity_id: str | None
    reason: str


def _normalize(value: str, value_kind: str) -> str:
    if value_kind == "external_id":
        return value
    normalized = unicodedata.normalize("NFKC", value).strip().casefold()
    return "".join(character for character in normalized if character.isalnum())


def _timestamp() -> str:
    return datetime.now(UTC).isoformat()


def _canonical_utc(value: str | None) -> str | None:
    """Проверить timezone и привести значение к каноническому UTC для сравнения."""
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Ожидается ISO-8601 timestamp с timezone") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Для временного значения обязательна timezone")
    return parsed.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


class EntityRegistry:
    """Явно мигрируемый локальный registry на SQLite."""

    schema_version = 8

    def __init__(self, path: Path) -> None:
        """Создать фасад для файла БД, не создавая файл и таблицы."""
        self.path = Path(path)

    @contextlib.contextmanager
    def _connect(self, *, write: bool = True) -> Iterator[sqlite3.Connection]:
        if not self.path.exists():
            raise RegistryNotInitializedError("Registry SQLite ещё не инициализирован")
        connection = sqlite3.connect(self.path, timeout=10)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version != self.schema_version:
                raise RegistryNotInitializedError(
                    "Версия схемы registry отсутствует или не поддерживается"
                )
            connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield connection
            connection.commit()
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        """Создать или явно обновить локальную схему registry."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=10)
        try:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version == self.schema_version:
                return
            if version in (1, 2):
                connection.executescript(self._upgrade_script(version))
                version = 3
            if version == 3:
                self._upgrade_v3(connection)
                version = 4
            if version == 4:
                self._upgrade_v4(connection)
                version = 5
            if version == 5:
                self._upgrade_v5(connection)
                version = 6
            if version == 6:
                self._upgrade_v6(connection)
                version = 7
            if version == 7:
                self._upgrade_v7(connection)
                return
            if version != 0:
                raise RegistryNotInitializedError(f"Неизвестная версия схемы registry: {version}")
            connection.execute("PRAGMA foreign_keys = ON")
            connection.executescript(
                """
                BEGIN IMMEDIATE;
                CREATE TABLE entities (
                    id TEXT PRIMARY KEY, kind TEXT NOT NULL,
                    sport TEXT NOT NULL, project_name TEXT NOT NULL,
                    seed_key TEXT, seed_entity_key TEXT,
                    revision INTEGER NOT NULL DEFAULT 1,
                    state TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    CHECK(kind IN ('tournament','team','event','player'))
                );
                CREATE UNIQUE INDEX seeded_entity_identity ON entities(seed_key,seed_entity_key)
                    WHERE seed_key IS NOT NULL;
                CREATE TABLE designations (
                    id TEXT PRIMARY KEY, source TEXT NOT NULL, kind TEXT NOT NULL,
                    scope_json TEXT NOT NULL, value_kind TEXT NOT NULL,
                    raw_value TEXT NOT NULL, normalized_value TEXT NOT NULL,
                    entity_id TEXT REFERENCES entities(id), state TEXT NOT NULL,
                    valid_from TEXT, valid_until TEXT,
                    seed_key TEXT, revision INTEGER NOT NULL DEFAULT 1,
                    CHECK(state IN ('pending','confirmed','conflict','rejected','deferred','superseded')),
                    CHECK(valid_from IS NULL OR valid_until IS NULL OR valid_from < valid_until)
                );
                CREATE INDEX designation_lookup ON designations
                    (source,kind,scope_json,value_kind,normalized_value,state);
                CREATE TABLE designation_conflicts (
                    id TEXT PRIMARY KEY,
                    designation_id TEXT NOT NULL REFERENCES designations(id),
                    peer_designation_id TEXT NOT NULL REFERENCES designations(id),
                    valid_from TEXT, valid_until TEXT,
                    state TEXT NOT NULL CHECK(state IN ('open','resolved','dismissed')),
                    selected_entity_id TEXT REFERENCES entities(id),
                    created_at TEXT NOT NULL, resolved_at TEXT,
                    CHECK(valid_from IS NULL OR valid_until IS NULL OR valid_from < valid_until)
                );
                CREATE INDEX designation_conflict_interval ON designation_conflicts
                    (state,valid_from,valid_until);
                CREATE TABLE decisions (
                    id TEXT PRIMARY KEY, designation_id TEXT NOT NULL REFERENCES designations(id),
                    actor TEXT NOT NULL, action TEXT NOT NULL, reason TEXT NOT NULL,
                    prior_state TEXT NOT NULL, prior_revision INTEGER NOT NULL,
                    decided_at TEXT NOT NULL
                );
                CREATE TABLE entity_audit (
                    id TEXT PRIMARY KEY, entity_id TEXT NOT NULL REFERENCES entities(id),
                    actor TEXT NOT NULL, action TEXT NOT NULL, reason TEXT NOT NULL,
                    prior_name TEXT NOT NULL, project_name TEXT NOT NULL,
                    decided_at TEXT NOT NULL
                );
                CREATE TABLE memberships (
                    id TEXT PRIMARY KEY,
                    player_id TEXT NOT NULL REFERENCES entities(id),
                    team_id TEXT NOT NULL REFERENCES entities(id),
                    relation_kind TEXT NOT NULL, valid_from TEXT NOT NULL,
                    valid_until TEXT,
                    CHECK(valid_until IS NULL OR valid_from < valid_until)
                );
                CREATE INDEX membership_lookup ON memberships
                    (player_id,relation_kind,valid_from,valid_until);
                CREATE TABLE imports (
                    seed_key TEXT PRIMARY KEY, content_hash TEXT NOT NULL,
                    imported_at TEXT NOT NULL
                );
                CREATE TABLE review_candidates (
                    id TEXT PRIMARY KEY,
                    designation_id TEXT NOT NULL REFERENCES designations(id),
                    origin TEXT NOT NULL, idempotency_key TEXT NOT NULL,
                    observed_at TEXT NOT NULL, facts_json TEXT NOT NULL,
                    proposed_entity_ids_json TEXT NOT NULL, basis TEXT NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 1,
                    status TEXT NOT NULL CHECK(status IN ('pending','confirmed','rejected','deferred')),
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    UNIQUE(origin,idempotency_key)
                );
                CREATE INDEX review_candidate_queue ON review_candidates(status,observed_at,id);
                CREATE TABLE review_candidate_history (
                    candidate_id TEXT NOT NULL REFERENCES review_candidates(id),
                    revision INTEGER NOT NULL,
                    observed_at TEXT NOT NULL, facts_json TEXT NOT NULL,
                    proposed_entity_ids_json TEXT NOT NULL, basis TEXT NOT NULL,
                    status TEXT NOT NULL, saved_at TEXT NOT NULL,
                    PRIMARY KEY(candidate_id,revision)
                );
                CREATE TABLE event_relations (
                    event_id TEXT PRIMARY KEY REFERENCES entities(id),
                    tournament_id TEXT NOT NULL REFERENCES entities(id),
                    home_team_id TEXT NOT NULL REFERENCES entities(id),
                    away_team_id TEXT NOT NULL REFERENCES entities(id),
                    scheduled_at TEXT,
                    revision INTEGER NOT NULL,
                    updated_at TEXT NOT NULL,
                    CHECK(home_team_id <> away_team_id)
                );
                CREATE TABLE event_relation_audit (
                    id TEXT PRIMARY KEY,
                    event_id TEXT NOT NULL REFERENCES entities(id),
                    actor TEXT NOT NULL, reason TEXT NOT NULL,
                    prior_revision INTEGER NOT NULL, revision INTEGER NOT NULL,
                    prior_tournament_id TEXT, tournament_id TEXT NOT NULL,
                    prior_home_team_id TEXT, home_team_id TEXT NOT NULL,
                    prior_away_team_id TEXT, away_team_id TEXT NOT NULL,
                    prior_scheduled_at TEXT, scheduled_at TEXT,
                    decided_at TEXT NOT NULL
                );
                CREATE INDEX event_relation_tournament ON event_relations(tournament_id,event_id);
                PRAGMA user_version = 8;
                COMMIT;
                """
            )
            logger.info("Локальная схема registry создана: %s", self.path)
        finally:
            connection.close()

    @classmethod
    def _upgrade_v3(cls, connection: sqlite3.Connection) -> None:
        """Добавить интервальные конфликты, сохранив известные прежние интервалы."""
        connection.execute("BEGIN IMMEDIATE")
        try:
            connection.execute(
                "CREATE TABLE designation_conflicts (id TEXT PRIMARY KEY, designation_id TEXT NOT NULL REFERENCES designations(id), peer_designation_id TEXT NOT NULL REFERENCES designations(id), valid_from TEXT, valid_until TEXT, state TEXT NOT NULL CHECK(state IN ('open','resolved')), selected_entity_id TEXT REFERENCES entities(id), created_at TEXT NOT NULL, resolved_at TEXT, CHECK(valid_from IS NULL OR valid_until IS NULL OR valid_from < valid_until))"
            )
            connection.execute(
                "CREATE INDEX designation_conflict_interval ON designation_conflicts(state,valid_from,valid_until)"
            )
            rows = connection.execute(
                "SELECT * FROM designations WHERE state IN ('confirmed','conflict') ORDER BY id"
            ).fetchall()
            grouped: dict[tuple[str, ...], list[sqlite3.Row]] = {}
            for row in rows:
                key = tuple(
                    row[name]
                    for name in ("source", "kind", "scope_json", "value_kind", "normalized_value")
                )
                grouped.setdefault(key, []).append(row)
            restore_ids: set[str] = set()
            now = _timestamp()
            for peers in grouped.values():
                for index, first in enumerate(peers):
                    for second in peers[index + 1 :]:
                        if first["entity_id"] == second["entity_id"]:
                            continue
                        if "conflict" not in (first["state"], second["state"]):
                            continue
                        start, end = cls._interval_intersection(
                            first["valid_from"],
                            first["valid_until"],
                            second["valid_from"],
                            second["valid_until"],
                        )
                        if not cls._intervals_overlap(
                            first["valid_from"],
                            first["valid_until"],
                            second["valid_from"],
                            second["valid_until"],
                        ):
                            continue
                        connection.execute(
                            "INSERT INTO designation_conflicts (id,designation_id,peer_designation_id,valid_from,valid_until,state,created_at) VALUES (?,?,?,?,?,'open',?)",
                            (str(uuid.uuid4()), first["id"], second["id"], start, end, now),
                        )
                        if first["state"] == second["state"] == "conflict":
                            if cls._strictly_contains(first, second):
                                restore_ids.add(first["id"])
                            elif cls._strictly_contains(second, first):
                                restore_ids.add(second["id"])
            for designation_id in restore_ids:
                connection.execute(
                    "UPDATE designations SET state='confirmed',revision=revision+1 WHERE id=?",
                    (designation_id,),
                )
            connection.execute("PRAGMA user_version = 4")
            connection.commit()
        except Exception:
            connection.rollback()
            raise

    @classmethod
    def _upgrade_v4(cls, connection: sqlite3.Connection) -> None:
        """Добавить состояние dismissed для закрытых owner-ом конфликтов."""
        connection.execute("BEGIN IMMEDIATE")
        try:
            connection.execute(
                "ALTER TABLE designation_conflicts RENAME TO designation_conflicts_v4"
            )
            connection.execute("DROP INDEX designation_conflict_interval")
            connection.execute(
                "CREATE TABLE designation_conflicts (id TEXT PRIMARY KEY, designation_id TEXT NOT NULL REFERENCES designations(id), peer_designation_id TEXT NOT NULL REFERENCES designations(id), valid_from TEXT, valid_until TEXT, state TEXT NOT NULL CHECK(state IN ('open','resolved','dismissed')), selected_entity_id TEXT REFERENCES entities(id), created_at TEXT NOT NULL, resolved_at TEXT, CHECK(valid_from IS NULL OR valid_until IS NULL OR valid_from < valid_until))"
            )
            connection.execute(
                "INSERT INTO designation_conflicts SELECT * FROM designation_conflicts_v4"
            )
            connection.execute("DROP TABLE designation_conflicts_v4")
            connection.execute(
                "CREATE INDEX designation_conflict_interval ON designation_conflicts(state,valid_from,valid_until)"
            )
            connection.execute("PRAGMA user_version = 5")
            connection.commit()
        except Exception:
            connection.rollback()
            raise

    @classmethod
    def _upgrade_v5(cls, connection: sqlite3.Connection) -> None:
        """Добавить локальную очередь evidence-кандидатов."""
        connection.execute("BEGIN IMMEDIATE")
        try:
            connection.execute(
                """CREATE TABLE review_candidates (
                    id TEXT PRIMARY KEY,
                    designation_id TEXT NOT NULL REFERENCES designations(id),
                    origin TEXT NOT NULL, idempotency_key TEXT NOT NULL,
                    observed_at TEXT NOT NULL, facts_json TEXT NOT NULL,
                    proposed_entity_ids_json TEXT NOT NULL, basis TEXT NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 1,
                    status TEXT NOT NULL CHECK(status IN ('pending','confirmed','rejected','deferred')),
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    UNIQUE(origin,idempotency_key)
                )"""
            )
            connection.execute(
                "CREATE INDEX review_candidate_queue ON review_candidates(status,observed_at,id)"
            )
            connection.execute("PRAGMA user_version = 6")
            connection.commit()
        except Exception:
            connection.rollback()
            raise

    @classmethod
    def _upgrade_v6(cls, connection: sqlite3.Connection) -> None:
        """Сохранить прошлые evidence revisions кандидатов."""
        connection.execute("BEGIN IMMEDIATE")
        try:
            connection.execute(
                """CREATE TABLE review_candidate_history (
                    candidate_id TEXT NOT NULL REFERENCES review_candidates(id),
                    revision INTEGER NOT NULL,
                    observed_at TEXT NOT NULL, facts_json TEXT NOT NULL,
                    proposed_entity_ids_json TEXT NOT NULL, basis TEXT NOT NULL,
                    status TEXT NOT NULL, saved_at TEXT NOT NULL,
                    PRIMARY KEY(candidate_id,revision)
                )"""
            )
            connection.execute("PRAGMA user_version = 7")
            connection.commit()
        except Exception:
            connection.rollback()
            raise

    @classmethod
    def _upgrade_v7(cls, connection: sqlite3.Connection) -> None:
        """Добавить проектные связи tournament/home/away для событий."""
        connection.execute("BEGIN IMMEDIATE")
        try:
            connection.execute(
                "CREATE TABLE event_relations (event_id TEXT PRIMARY KEY REFERENCES entities(id), tournament_id TEXT NOT NULL REFERENCES entities(id), home_team_id TEXT NOT NULL REFERENCES entities(id), away_team_id TEXT NOT NULL REFERENCES entities(id), scheduled_at TEXT, revision INTEGER NOT NULL, updated_at TEXT NOT NULL, CHECK(home_team_id <> away_team_id))"
            )
            connection.execute(
                "CREATE TABLE event_relation_audit (id TEXT PRIMARY KEY,event_id TEXT NOT NULL REFERENCES entities(id),actor TEXT NOT NULL,reason TEXT NOT NULL,prior_revision INTEGER NOT NULL,revision INTEGER NOT NULL,prior_tournament_id TEXT,tournament_id TEXT NOT NULL,prior_home_team_id TEXT,home_team_id TEXT NOT NULL,prior_away_team_id TEXT,away_team_id TEXT NOT NULL,prior_scheduled_at TEXT,scheduled_at TEXT,decided_at TEXT NOT NULL)"
            )
            connection.execute(
                "CREATE INDEX event_relation_tournament ON event_relations(tournament_id,event_id)"
            )
            connection.execute("PRAGMA user_version = 8")
            connection.commit()
        except Exception:
            connection.rollback()
            raise

    @staticmethod
    def _strictly_contains(first: sqlite3.Row, second: sqlite3.Row) -> bool:
        """Проверить, что интервал first строго охватывает second."""
        starts_before = first["valid_from"] is None or (
            second["valid_from"] is not None and first["valid_from"] < second["valid_from"]
        )
        ends_after = first["valid_until"] is None or (
            second["valid_until"] is not None and first["valid_until"] > second["valid_until"]
        )
        return starts_before and ends_after

    @staticmethod
    def _interval_intersection(
        first_start: str | None,
        first_end: str | None,
        second_start: str | None,
        second_end: str | None,
    ) -> tuple[str | None, str | None]:
        """Вернуть пересечение двух уже проверенных полуоткрытых интервалов."""
        starts = [value for value in (first_start, second_start) if value is not None]
        ends = [value for value in (first_end, second_end) if value is not None]
        return (max(starts) if starts else None, min(ends) if ends else None)

    @staticmethod
    def _upgrade_script(version: int) -> str:
        """Версионированно дополнить прежнюю локальную схему."""
        statements = ["BEGIN IMMEDIATE;"]
        if version == 1:
            statements.append(
                "CREATE TABLE entity_audit (id TEXT PRIMARY KEY, entity_id TEXT NOT NULL REFERENCES entities(id), actor TEXT NOT NULL, action TEXT NOT NULL, reason TEXT NOT NULL, prior_name TEXT NOT NULL, project_name TEXT NOT NULL, decided_at TEXT NOT NULL);"
            )
            version = 2
        if version == 2:
            statements.extend(
                [
                    "ALTER TABLE designations ADD COLUMN revision INTEGER NOT NULL DEFAULT 1;",
                    "ALTER TABLE decisions ADD COLUMN prior_revision INTEGER NOT NULL DEFAULT 1;",
                    "ALTER TABLE imports ADD COLUMN content_hash TEXT NOT NULL DEFAULT '';",
                ]
            )
        statements.extend(["PRAGMA user_version = 3;", "COMMIT;"])
        return "\n".join(statements)

    def create_entity(self, kind: EntityKind, project_name: str, *, sport: str) -> Entity:
        """Создать проектную сущность и выдать ей UUID."""
        if not project_name.strip() or not sport.strip():
            raise ValueError("Имя сущности и вид спорта обязательны")
        entity = Entity(str(uuid.uuid4()), kind, sport, project_name.strip(), 1)
        with self._connect() as connection:
            now = _timestamp()
            connection.execute(
                "INSERT INTO entities (id,kind,sport,project_name,revision,state,created_at,updated_at) VALUES (?,?,?, ?,1,'active',?,?)",
                (entity.id, kind, sport, entity.project_name, now, now),
            )
        return entity

    def get_entity(self, entity_id: str) -> Entity:
        """Получить сущность по project UUID."""
        with self._connect(write=False) as connection:
            row = connection.execute("SELECT * FROM entities WHERE id=?", (entity_id,)).fetchone()
        if row is None:
            raise KeyError(entity_id)
        return Entity(row["id"], row["kind"], row["sport"], row["project_name"], row["revision"])

    def list_entities(self, *, kind: str | None = None) -> list[Entity]:
        """Вернуть активные сущности, при необходимости выбранного типа."""
        with self._connect(write=False) as connection:
            rows = connection.execute(
                "SELECT * FROM entities WHERE state='active' AND (? IS NULL OR kind=?) ORDER BY project_name,id",
                (kind, kind),
            ).fetchall()
        return [
            Entity(r["id"], r["kind"], r["sport"], r["project_name"], r["revision"]) for r in rows
        ]

    def count_designations(self) -> int:
        """Вернуть число сохранённых внешних обозначений."""
        with self._connect(write=False) as connection:
            return int(connection.execute("SELECT count(*) FROM designations").fetchone()[0])

    def rename_entity(
        self,
        entity_id: str,
        project_name: str,
        *,
        actor: str = "owner",
        reason: str = "Переименование проектного имени",
    ) -> Entity:
        """Изменить отображаемое имя с сохранением UUID."""
        if not project_name.strip() or not actor.strip() or not reason.strip():
            raise ValueError("Имя, автор и основание обязательны")
        with self._connect() as connection:
            entity = connection.execute(
                "SELECT project_name FROM entities WHERE id=?", (entity_id,)
            ).fetchone()
            if entity is None:
                raise KeyError(entity_id)
            prior_name = entity["project_name"]
            now = _timestamp()
            result = connection.execute(
                "UPDATE entities SET project_name=?,revision=revision+1,updated_at=? WHERE id=?",
                (project_name.strip(), now, entity_id),
            )
            if result.rowcount != 1:
                raise KeyError(entity_id)
            connection.execute(
                "INSERT INTO entity_audit VALUES (?,?,?,?,?,?,?,?)",
                (
                    str(uuid.uuid4()),
                    entity_id,
                    actor,
                    "rename",
                    reason,
                    prior_name,
                    project_name.strip(),
                    now,
                ),
            )
        return self.get_entity(entity_id)

    def list_entity_audit(self, entity_id: str) -> list[EntityAudit]:
        """Вернуть аудит переименований project-сущности."""
        with self._connect(write=False) as connection:
            rows = connection.execute(
                "SELECT * FROM entity_audit WHERE entity_id=? ORDER BY decided_at,id", (entity_id,)
            ).fetchall()
        return [
            EntityAudit(
                row["id"],
                row["entity_id"],
                row["actor"],
                row["action"],
                row["reason"],
                row["prior_name"],
                row["project_name"],
                row["decided_at"],
            )
            for row in rows
        ]

    @staticmethod
    def _scope_json(scope: dict[str, str]) -> str:
        if not scope:
            raise ValueError("Scope обязателен и не может быть пустым")
        return json.dumps(scope, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def add_designation(
        self,
        *,
        entity_id: str | None,
        source: str,
        kind: str,
        scope: dict[str, str],
        value_kind: str,
        raw_value: str,
        state: DesignationState | None = None,
        valid_from: str | None = None,
        valid_until: str | None = None,
        seed_key: str | None = None,
    ) -> Designation:
        """Добавить внешнее обозначение; коллизии фиксируются как конфликт."""
        if not all((source.strip(), kind.strip(), value_kind.strip(), raw_value.strip())):
            raise ValueError("Источник, тип, вид значения и исходное значение обязательны")
        start = _canonical_utc(valid_from)
        end = _canonical_utc(valid_until)
        if start is not None and end is not None and start >= end:
            raise ValueError("Начало интервала должно быть раньше конца")
        with self._connect() as connection:
            row = self._insert_designation(
                connection,
                entity_id=entity_id,
                source=source,
                kind=kind,
                scope=scope,
                value_kind=value_kind,
                raw_value=raw_value,
                state=state or "pending",
                valid_from=start,
                valid_until=end,
                seed_key=seed_key,
            )
        return self._designation(row)

    def _insert_designation(
        self,
        connection: sqlite3.Connection,
        *,
        entity_id: str | None,
        source: str,
        kind: str,
        scope: dict[str, str],
        value_kind: str,
        raw_value: str,
        state: DesignationState,
        valid_from: str | None,
        valid_until: str | None,
        seed_key: str | None = None,
    ) -> sqlite3.Row:
        """Вставить designation в текущую write transaction."""
        if entity_id is None and state == "confirmed":
            raise ValueError("Подтверждённое обозначение должно ссылаться на сущность")
        if entity_id is not None:
            entity = connection.execute(
                "SELECT kind FROM entities WHERE id=?", (entity_id,)
            ).fetchone()
            if entity is None or entity["kind"] != kind:
                raise ValueError("Тип связанной сущности не совпадает с designation")
        scope_json = self._scope_json(scope)
        normalized = _normalize(raw_value, value_kind)
        matches: list[sqlite3.Row] = connection.execute(
            "SELECT * FROM designations WHERE source=? AND kind=? AND scope_json=? AND value_kind=? AND normalized_value=?",
            (source, kind, scope_json, value_kind, normalized),
        ).fetchall()
        active_states = ("pending", "deferred", "confirmed", "conflict")
        overlapping = [
            row
            for row in matches
            if state in active_states
            and row["state"] in active_states
            and row["entity_id"] is not None
            and row["entity_id"] != entity_id
            and self._intervals_overlap(
                valid_from, valid_until, row["valid_from"], row["valid_until"]
            )
        ]
        # Base state records the intended designation; open conflict overlays
        # block resolution only during their shared interval.
        actual_state = state
        for row in matches:
            if (
                row["entity_id"] == entity_id
                and row["state"] == actual_state
                and row["valid_from"] == valid_from
                and row["valid_until"] == valid_until
                and row["seed_key"] == seed_key
            ):
                return row
        designation_id = str(uuid.uuid4())
        connection.execute(
            "INSERT INTO designations (id,source,kind,scope_json,value_kind,raw_value,normalized_value,entity_id,state,valid_from,valid_until,seed_key,revision) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,1)",
            (
                designation_id,
                source,
                kind,
                scope_json,
                value_kind,
                raw_value,
                normalized,
                entity_id,
                actual_state,
                valid_from,
                valid_until,
                seed_key,
            ),
        )
        for peer in overlapping:
            conflict_start, conflict_end = self._interval_intersection(
                valid_from,
                valid_until,
                peer["valid_from"],
                peer["valid_until"],
            )
            connection.execute(
                "INSERT INTO designation_conflicts (id,designation_id,peer_designation_id,valid_from,valid_until,state,created_at) VALUES (?,?,?,?,?,'open',?)",
                (
                    str(uuid.uuid4()),
                    designation_id,
                    peer["id"],
                    conflict_start,
                    conflict_end,
                    _timestamp(),
                ),
            )
        inserted_rows: list[sqlite3.Row] = connection.execute(
            "SELECT * FROM designations WHERE id=?", (designation_id,)
        ).fetchall()
        if not inserted_rows:
            raise RuntimeError("Созданное designation не найдено в локальной базе")
        return inserted_rows[0]

    @staticmethod
    def _intervals_overlap(
        a_start: str | None, a_end: str | None, b_start: str | None, b_end: str | None
    ) -> bool:
        return (a_end is None or b_start is None or a_end > b_start) and (
            b_end is None or a_start is None or b_end > a_start
        )

    @staticmethod
    def _designation(row: sqlite3.Row) -> Designation:
        return Designation(
            row["id"],
            row["source"],
            row["kind"],
            json.loads(row["scope_json"]),
            row["value_kind"],
            row["raw_value"],
            row["entity_id"],
            row["state"],
            row["valid_from"],
            row["valid_until"],
            row["revision"],
        )

    def get_designation(self, designation_id: str) -> Designation:
        """Получить designation по внутреннему ID."""
        with self._connect(write=False) as connection:
            row = connection.execute(
                "SELECT * FROM designations WHERE id=?", (designation_id,)
            ).fetchone()
        if row is None:
            raise KeyError(designation_id)
        return self._designation(row)

    def find_designation(
        self, source: str, kind: str, scope: dict[str, str], value_kind: str, raw_value: str
    ) -> Designation:
        """Найти точное нормализованное обозначение в заданном scope."""
        with self._connect(write=False) as connection:
            rows = connection.execute(
                "SELECT * FROM designations WHERE source=? AND kind=? AND scope_json=? AND value_kind=? AND normalized_value=? ORDER BY id",
                (
                    source,
                    kind,
                    self._scope_json(scope),
                    value_kind,
                    _normalize(raw_value, value_kind),
                ),
            ).fetchall()
        if len(rows) != 1:
            raise KeyError(raw_value)
        return self._designation(rows[0])

    def resolve(
        self,
        source: str,
        kind: str,
        scope: dict[str, str],
        value_kind: str,
        raw_value: str,
        *,
        at: str | None = None,
    ) -> Resolution:
        """Разрешить только точную подтверждённую привязку, без similarity fallback."""
        instant = _canonical_utc(at)
        with self._connect(write=False) as connection:
            rows = connection.execute(
                "SELECT * FROM designations WHERE source=? AND kind=? AND scope_json=? AND value_kind=? AND normalized_value=?",
                (
                    source,
                    kind,
                    self._scope_json(scope),
                    value_kind,
                    _normalize(raw_value, value_kind),
                ),
            ).fetchall()
            if not rows:
                return Resolution("unresolved", None, "Обозначение не зарегистрировано")
            designation_ids = [row["id"] for row in rows]
            placeholders = ",".join("?" for _ in designation_ids)
            conflicts = connection.execute(
                f"SELECT * FROM designation_conflicts WHERE designation_id IN ({placeholders}) OR peer_designation_id IN ({placeholders})",
                (*designation_ids, *designation_ids),
            ).fetchall()
        effective_conflicts = [
            conflict for conflict in conflicts if conflict["state"] != "dismissed"
        ]
        if instant is None:
            if any(conflict["state"] == "open" for conflict in effective_conflicts):
                return Resolution("conflict", None, "Обозначение имеет временной конфликт")
            if effective_conflicts:
                if all(
                    conflict["valid_from"] is None and conflict["valid_until"] is None
                    for conflict in effective_conflicts
                ):
                    selected = {conflict["selected_entity_id"] for conflict in effective_conflicts}
                    selected.discard(None)
                    if len(selected) == 1:
                        return Resolution(
                            "resolved", next(iter(selected)), "Владелец разрешил конфликт"
                        )
                return Resolution(
                    "ambiguous", None, "Для разрешённого конфликта требуется дата события"
                )
        else:
            active_conflicts = [
                conflict
                for conflict in effective_conflicts
                if (conflict["valid_from"] is None or conflict["valid_from"] <= instant)
                and (conflict["valid_until"] is None or instant < conflict["valid_until"])
            ]
            open_conflicts = [
                conflict for conflict in active_conflicts if conflict["state"] == "open"
            ]
            if open_conflicts:
                return Resolution(
                    "conflict", None, "Обозначение имеет конфликтующую привязку в этот период"
                )
            resolved_ids = {conflict["selected_entity_id"] for conflict in active_conflicts}
            resolved_ids.discard(None)
            if len(resolved_ids) == 1:
                return Resolution(
                    "resolved",
                    next(iter(resolved_ids)),
                    "Конфликт разрешён владельцем для этого периода",
                )
            if len(resolved_ids) > 1:
                return Resolution(
                    "conflict", None, "Владелец принял противоречащие решения для периода"
                )
        if instant is not None:
            rows = [
                row
                for row in rows
                if (row["valid_from"] is None or row["valid_from"] <= instant)
                and (row["valid_until"] is None or instant < row["valid_until"])
            ]
        confirmed = [row for row in rows if row["state"] == "confirmed"]
        if instant is None and any(
            r["valid_from"] is not None or r["valid_until"] is not None for r in confirmed
        ):
            return Resolution("ambiguous", None, "Для временной привязки требуется дата события")
        ids = {row["entity_id"] for row in confirmed}
        if len(ids) == 1 and confirmed:
            return Resolution("resolved", next(iter(ids)), "Точное подтверждённое обозначение")
        if len(ids) > 1:
            return Resolution("conflict", None, "Несколько подтверждённых project ID")
        return Resolution("unresolved", None, "Нет подтверждённой привязки")

    def decide_designation(
        self,
        designation_id: str,
        *,
        action: Literal["confirm", "reject", "defer", "resolve_conflict"],
        entity_id: str | None,
        actor: str,
        reason: str,
        expected_revision: int,
        conflict_period: tuple[str | None, str | None] | None = None,
    ) -> Decision:
        """Применить решение владельца и атомарно записать его аудит."""
        if not actor.strip() or not reason.strip():
            raise ValueError("Автор и основание решения обязательны")
        if conflict_period is not None and action != "resolve_conflict":
            raise ValueError("conflict_period допустим только при разрешении конфликта")
        period_start = period_end = None
        if conflict_period is not None:
            period_start = _canonical_utc(conflict_period[0])
            period_end = _canonical_utc(conflict_period[1])
            if period_start is not None and period_end is not None and period_start >= period_end:
                raise ValueError("Начало conflict_period должно быть раньше конца")
        target_state = {
            "confirm": "confirmed",
            "reject": "rejected",
            "defer": "deferred",
            "resolve_conflict": "confirmed",
        }[action]
        if target_state == "confirmed" and entity_id is None:
            raise ValueError("Подтверждение требует целевую сущность")
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM designations WHERE id=?", (designation_id,)
            ).fetchone()
            if row is None:
                raise KeyError(designation_id)
            if row["revision"] != expected_revision:
                raise ValueError("Версия designation устарела; перечитайте решение")
            target = None
            if entity_id is not None:
                target = connection.execute(
                    "SELECT kind FROM entities WHERE id=?", (entity_id,)
                ).fetchone()
                if target is None or target["kind"] != row["kind"]:
                    raise ValueError("Тип целевой сущности не совпадает с designation")
            peers = connection.execute(
                "SELECT * FROM designations WHERE source=? AND kind=? AND scope_json=? AND value_kind=? AND normalized_value=? AND id<>?",
                (
                    row["source"],
                    row["kind"],
                    row["scope_json"],
                    row["value_kind"],
                    row["normalized_value"],
                    designation_id,
                ),
            ).fetchall()
            overlapping_peers = [
                peer
                for peer in peers
                if self._intervals_overlap(
                    row["valid_from"], row["valid_until"], peer["valid_from"], peer["valid_until"]
                )
            ]
            if action == "confirm" and (
                row["state"] == "conflict"
                or any(
                    peer["state"] == "conflict"
                    or (peer["state"] == "confirmed" and peer["entity_id"] != entity_id)
                    for peer in overlapping_peers
                )
            ):
                raise ValueError("Нельзя подтвердить designation с пересекающимся конфликтом")
            decision = Decision(
                str(uuid.uuid4()),
                designation_id,
                actor,
                action,
                reason,
                row["state"],
                row["revision"],
                _timestamp(),
            )
            if action == "resolve_conflict":
                conflicts = connection.execute(
                    "SELECT * FROM designation_conflicts WHERE state='open' AND (designation_id=? OR peer_designation_id=?)",
                    (designation_id, designation_id),
                ).fetchall()
                if not conflicts:
                    raise ValueError("У designation нет открытого интервала конфликта")
                audited_peer_ids: set[str] = set()
                resolved_intervals = 0
                for conflict in conflicts:
                    resolved_start = conflict["valid_from"]
                    resolved_end = conflict["valid_until"]
                    if conflict_period is not None:
                        if not self._intervals_overlap(
                            resolved_start, resolved_end, period_start, period_end
                        ):
                            continue
                        resolved_start, resolved_end = self._interval_intersection(
                            resolved_start, resolved_end, period_start, period_end
                        )
                    peer_id = (
                        conflict["peer_designation_id"]
                        if conflict["designation_id"] == designation_id
                        else conflict["designation_id"]
                    )
                    peer = next(item for item in overlapping_peers if item["id"] == peer_id)
                    connection.execute(
                        "UPDATE designation_conflicts SET valid_from=?,valid_until=?,state='resolved',selected_entity_id=?,resolved_at=? WHERE id=?",
                        (
                            resolved_start,
                            resolved_end,
                            entity_id,
                            decision.decided_at,
                            conflict["id"],
                        ),
                    )
                    resolved_intervals += 1
                    if conflict["valid_from"] != resolved_start and resolved_start is not None:
                        connection.execute(
                            "INSERT INTO designation_conflicts (id,designation_id,peer_designation_id,valid_from,valid_until,state,created_at) VALUES (?,?,?,?,?,'open',?)",
                            (
                                str(uuid.uuid4()),
                                conflict["designation_id"],
                                conflict["peer_designation_id"],
                                conflict["valid_from"],
                                resolved_start,
                                conflict["created_at"],
                            ),
                        )
                    if conflict["valid_until"] != resolved_end and resolved_end is not None:
                        connection.execute(
                            "INSERT INTO designation_conflicts (id,designation_id,peer_designation_id,valid_from,valid_until,state,created_at) VALUES (?,?,?,?,?,'open',?)",
                            (
                                str(uuid.uuid4()),
                                conflict["designation_id"],
                                conflict["peer_designation_id"],
                                resolved_end,
                                conflict["valid_until"],
                                conflict["created_at"],
                            ),
                        )
                    if peer_id not in audited_peer_ids:
                        self._audit_peer_conflict_decision(
                            connection,
                            peer,
                            actor,
                            "overlap_conflict_resolved",
                            reason,
                            decision.decided_at,
                        )
                        audited_peer_ids.add(peer_id)
                if not resolved_intervals:
                    raise ValueError("У designation нет открытого конфликта в указанном интервале")
            elif action == "reject":
                conflicts = connection.execute(
                    "SELECT * FROM designation_conflicts WHERE state IN ('open','resolved') AND (designation_id=? OR peer_designation_id=?)",
                    (designation_id, designation_id),
                ).fetchall()
                affected_peer_actions: dict[str, str] = {}
                for conflict in conflicts:
                    peer_id = (
                        conflict["peer_designation_id"]
                        if conflict["designation_id"] == designation_id
                        else conflict["designation_id"]
                    )
                    connection.execute(
                        "UPDATE designation_conflicts SET state='dismissed',resolved_at=? WHERE id=?",
                        (decision.decided_at, conflict["id"]),
                    )
                    audit_action = (
                        "overlap_conflict_invalidated"
                        if conflict["state"] == "resolved"
                        else "overlap_conflict_dismissed"
                    )
                    if (
                        peer_id not in affected_peer_actions
                        or audit_action == "overlap_conflict_invalidated"
                    ):
                        affected_peer_actions[peer_id] = audit_action
                for peer_id, audit_action in affected_peer_actions.items():
                    peer = connection.execute(
                        "SELECT * FROM designations WHERE id=?", (peer_id,)
                    ).fetchone()
                    assert peer is not None
                    self._audit_peer_conflict_decision(
                        connection, peer, actor, audit_action, reason, decision.decided_at
                    )
            if action == "resolve_conflict":
                # Выбор действует только на временные overlays; base designation
                # остаётся прежним в том числе за пределами conflict interval.
                connection.execute(
                    "UPDATE designations SET revision=revision+1 WHERE id=?", (designation_id,)
                )
            else:
                connection.execute(
                    "UPDATE designations SET entity_id=?,state=?,revision=revision+1 WHERE id=?",
                    (entity_id, target_state, designation_id),
                )
            connection.execute(
                "INSERT INTO decisions (id,designation_id,actor,action,reason,prior_state,prior_revision,decided_at) VALUES (?,?,?,?,?,?,?,?)",
                (
                    decision.id,
                    designation_id,
                    actor,
                    action,
                    reason,
                    row["state"],
                    row["revision"],
                    decision.decided_at,
                ),
            )
        return Decision(
            decision.id,
            designation_id,
            actor,
            action,
            reason,
            row["state"],
            row["revision"],
            decision.decided_at,
        )

    @staticmethod
    def _audit_peer_conflict_decision(
        connection: sqlite3.Connection,
        peer: sqlite3.Row,
        actor: str,
        action: str,
        reason: str,
        decided_at: str,
    ) -> None:
        """Записать изменение revision и аудит peer без смены его base state."""
        connection.execute("UPDATE designations SET revision=revision+1 WHERE id=?", (peer["id"],))
        connection.execute(
            "INSERT INTO decisions (id,designation_id,actor,action,reason,prior_state,prior_revision,decided_at) VALUES (?,?,?,?,?,?,?,?)",
            (
                str(uuid.uuid4()),
                peer["id"],
                actor,
                action,
                reason,
                peer["state"],
                peer["revision"],
                decided_at,
            ),
        )

    def list_decisions(self, designation_id: str) -> list[Decision]:
        """Вернуть историю решений обозначения в хронологическом порядке."""
        with self._connect(write=False) as connection:
            rows = connection.execute(
                "SELECT * FROM decisions WHERE designation_id=? ORDER BY decided_at,id",
                (designation_id,),
            ).fetchall()
        return [
            Decision(
                r["id"],
                r["designation_id"],
                r["actor"],
                r["action"],
                r["reason"],
                r["prior_state"],
                r["prior_revision"],
                r["decided_at"],
            )
            for r in rows
        ]

    def _seed_entity_in_transaction(
        self,
        connection: sqlite3.Connection,
        kind: str,
        name: str,
        sport: str,
        seed_key: str,
        *,
        stable_key: str | None = None,
    ) -> Entity:
        """Найти или создать стабильную seed-сущность внутри текущей транзакции."""
        identity_key = stable_key or name
        row = connection.execute(
            "SELECT * FROM entities WHERE seed_key=? AND seed_entity_key=?",
            (seed_key, identity_key),
        ).fetchone()
        if row is not None:
            return Entity(
                row["id"], row["kind"], row["sport"], row["project_name"], row["revision"]
            )
        entity = Entity(str(uuid.uuid4()), kind, sport, name, 1)
        now = _timestamp()
        connection.execute(
            "INSERT INTO entities (id,kind,sport,project_name,seed_key,seed_entity_key,revision,state,created_at,updated_at) VALUES (?,?,?,?,?,?,1,'active',?,?)",
            (entity.id, kind, sport, name, seed_key, identity_key, now, now),
        )
        return entity

    def add_membership(
        self,
        player_id: str,
        team_id: str,
        relation_kind: str,
        valid_from: str,
        valid_until: str | None,
    ) -> str:
        """Добавить полуоткрытый временной интервал принадлежности игрока."""
        start = _canonical_utc(valid_from)
        end = _canonical_utc(valid_until)
        assert start is not None
        if end is not None and start >= end:
            raise ValueError("Начало интервала должно быть раньше конца")
        with self._connect() as connection:
            for entity_id, expected in ((player_id, "player"), (team_id, "team")):
                row = connection.execute(
                    "SELECT kind FROM entities WHERE id=?", (entity_id,)
                ).fetchone()
                if row is None or row["kind"] != expected:
                    raise ValueError(f"{entity_id} должен иметь тип {expected}")
            rows = connection.execute(
                "SELECT * FROM memberships WHERE player_id=? AND relation_kind=?",
                (player_id, relation_kind),
            ).fetchall()
            if any(
                self._intervals_overlap(start, end, r["valid_from"], r["valid_until"]) for r in rows
            ):
                raise ValueError("Интервалы принадлежности пересекаются")
            membership_id = str(uuid.uuid4())
            connection.execute(
                "INSERT INTO memberships VALUES (?,?,?,?,?,?)",
                (membership_id, player_id, team_id, relation_kind, start, end),
            )
        return membership_id

    def memberships_for_player(self, player_id: str) -> list[tuple[str, str, str, str | None]]:
        """Вернуть историю команд игрока по времени начала."""
        with self._connect(write=False) as connection:
            rows = connection.execute(
                "SELECT team_id,relation_kind,valid_from,valid_until FROM memberships WHERE player_id=? ORDER BY valid_from,id",
                (player_id,),
            ).fetchall()
        return [(r["team_id"], r["relation_kind"], r["valid_from"], r["valid_until"]) for r in rows]

    def set_event_relation(
        self,
        event_id: str,
        *,
        tournament_id: str,
        home_team_id: str,
        away_team_id: str,
        scheduled_at: datetime | str | None,
        actor: str,
        reason: str,
        expected_revision: int = 0,
    ) -> EventRelation:
        """Создать или скорректировать audited project event relation."""
        if not actor.strip() or not reason.strip():
            raise ValueError("Автор и основание изменения обязательны")
        if home_team_id == away_team_id:
            raise ValueError("Home и away team должны быть разными сущностями")
        timestamp = scheduled_at.isoformat() if isinstance(scheduled_at, datetime) else scheduled_at
        normalized_time = _canonical_utc(timestamp)
        with self._connect() as connection:
            expected_kinds = (
                (event_id, "event"),
                (tournament_id, "tournament"),
                (home_team_id, "team"),
                (away_team_id, "team"),
            )
            entities: list[sqlite3.Row] = []
            for entity_id, expected_kind in expected_kinds:
                row = connection.execute(
                    "SELECT id,kind,sport FROM entities WHERE id=? AND state='active'",
                    (entity_id,),
                ).fetchone()
                if row is None or row["kind"] != expected_kind:
                    raise ValueError(f"{entity_id} должен иметь тип {expected_kind}")
                entities.append(row)
            if len({row["sport"] for row in entities}) != 1:
                raise ValueError("Событие, турнир и команды должны принадлежать одному виду спорта")
            prior = connection.execute(
                "SELECT * FROM event_relations WHERE event_id=?", (event_id,)
            ).fetchone()
            prior_revision = prior["revision"] if prior is not None else 0
            if prior_revision != expected_revision:
                raise ValueError("Revision event relation устарела; перечитайте запись")
            revision = prior_revision + 1
            now = _timestamp()
            values = (tournament_id, home_team_id, away_team_id, normalized_time)
            if prior is None:
                connection.execute(
                    "INSERT INTO event_relations VALUES (?,?,?,?,?,?,?)",
                    (event_id, *values, revision, now),
                )
            else:
                connection.execute(
                    "UPDATE event_relations SET tournament_id=?,home_team_id=?,away_team_id=?,scheduled_at=?,revision=?,updated_at=? WHERE event_id=?",
                    (*values, revision, now, event_id),
                )
            connection.execute(
                "INSERT INTO event_relation_audit VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    str(uuid.uuid4()),
                    event_id,
                    actor,
                    reason,
                    prior_revision,
                    revision,
                    prior["tournament_id"] if prior is not None else None,
                    tournament_id,
                    prior["home_team_id"] if prior is not None else None,
                    home_team_id,
                    prior["away_team_id"] if prior is not None else None,
                    away_team_id,
                    prior["scheduled_at"] if prior is not None else None,
                    normalized_time,
                    now,
                ),
            )
        return EventRelation(
            event_id, tournament_id, home_team_id, away_team_id, normalized_time, revision
        )

    def get_event_relation(self, event_id: str) -> EventRelation:
        """Получить подтверждённые relations проектного события."""
        with self._connect(write=False) as connection:
            row = connection.execute(
                "SELECT * FROM event_relations WHERE event_id=?", (event_id,)
            ).fetchone()
        if row is None:
            raise KeyError(event_id)
        return EventRelation(
            row["event_id"],
            row["tournament_id"],
            row["home_team_id"],
            row["away_team_id"],
            row["scheduled_at"],
            row["revision"],
        )

    def list_event_relation_audit(self, event_id: str) -> list[EventRelationAudit]:
        """Вернуть полную историю решений по отношениям project event."""
        with self._connect(write=False) as connection:
            rows = connection.execute(
                "SELECT * FROM event_relation_audit WHERE event_id=? ORDER BY revision,id",
                (event_id,),
            ).fetchall()
        return [
            EventRelationAudit(
                row["id"],
                row["event_id"],
                row["actor"],
                row["reason"],
                row["prior_revision"],
                row["revision"],
                row["prior_tournament_id"],
                row["tournament_id"],
                row["prior_home_team_id"],
                row["home_team_id"],
                row["prior_away_team_id"],
                row["away_team_id"],
                row["prior_scheduled_at"],
                row["scheduled_at"],
                row["decided_at"],
            )
            for row in rows
        ]
