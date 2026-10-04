"""Очередь локального подтверждения связей с аудитом и идемпотентностью."""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from sports_forecast.identity.registry import Entity, EntityRegistry, _canonical_utc, _timestamp


CandidateStatus = Literal["pending", "confirmed", "rejected", "deferred"]
CandidateAction = Literal["confirm", "reject", "defer", "create_entity"]


@dataclass(frozen=True)
class CandidateObservation:
    """Новое наблюдение источника для внешнего обозначения."""

    source: str
    kind: str
    scope: dict[str, str]
    value_kind: str
    raw_value: str
    origin: str = "local:import"
    idempotency_key: str = "default"
    observed_at: str = ""
    facts: dict[str, str] | None = None
    proposed_entity_ids: tuple[str, ...] = ()
    basis: str = ""


@dataclass(frozen=True)
class NewProjectEntity:
    """Минимальные поля создаваемой проектной сущности."""

    kind: Literal["tournament", "team"]
    project_name: str
    sport: str


@dataclass(frozen=True)
class CandidateDecision:
    """Решение по кандидату с optimistic revision checks."""

    candidate_id: str
    expected_revision: int
    expected_designation_revision: int
    action: CandidateAction
    reason: str
    entity_id: str | None = None
    new_entity: NewProjectEntity | None = None


@dataclass(frozen=True)
class CandidateEvidenceRevision:
    """Сохранённая предыдущая редакция evidence для owner review."""

    revision: int
    observed_at: str
    facts: dict[str, str]
    proposed_entity_ids: tuple[str, ...]
    basis: str
    status: str


@dataclass(frozen=True)
class ReviewCandidate:
    """Кандидат очереди вместе с исходным evidence и revision designation."""

    id: str
    designation_id: str
    source: str
    kind: str
    scope: dict[str, str]
    value_kind: str
    raw_value: str
    origin: str
    observed_at: str
    facts: dict[str, str]
    proposed_entity_ids: tuple[str, ...]
    basis: str
    revision: int
    designation_revision: int
    designation_state: str
    confirmed_entity_id: str | None
    status: CandidateStatus
    history: tuple[CandidateEvidenceRevision, ...]
    history_count: int


class ReviewQueueService:
    """Сервис локальной очереди поверх SQLite master registry."""

    def __init__(self, registry: EntityRegistry) -> None:
        self.registry = registry

    @staticmethod
    def _candidate(connection: sqlite3.Connection, item: sqlite3.Row) -> ReviewCandidate:
        """Собрать доменную запись из joined SQLite rows."""
        designation = connection.execute(
            "SELECT * FROM designations WHERE id=?", (item["designation_id"],)
        ).fetchone()
        if designation is None:
            raise KeyError(item["designation_id"])
        history_rows = connection.execute(
            "SELECT * FROM review_candidate_history WHERE candidate_id=? ORDER BY revision DESC LIMIT 5",
            (item["id"],),
        ).fetchall()
        history_rows = list(reversed(history_rows))
        history_count = connection.execute(
            "SELECT count(*) FROM review_candidate_history WHERE candidate_id=?",
            (item["id"],),
        ).fetchone()[0]
        return ReviewCandidate(
            item["id"],
            item["designation_id"],
            designation["source"],
            designation["kind"],
            json.loads(designation["scope_json"]),
            designation["value_kind"],
            designation["raw_value"],
            item["origin"],
            item["observed_at"],
            json.loads(item["facts_json"]),
            tuple(json.loads(item["proposed_entity_ids_json"])),
            item["basis"],
            item["revision"],
            designation["revision"],
            designation["state"],
            designation["entity_id"],
            item["status"],
            tuple(
                CandidateEvidenceRevision(
                    entry["revision"],
                    entry["observed_at"],
                    json.loads(entry["facts_json"]),
                    tuple(json.loads(entry["proposed_entity_ids_json"])),
                    entry["basis"],
                    entry["status"],
                )
                for entry in history_rows
            ),
            history_count,
        )

    def observe(self, observation: CandidateObservation) -> ReviewCandidate:
        """Сохранить новое evidence, идентичное наблюдение сделать no-op."""
        required_strings = (
            observation.source,
            observation.kind,
            observation.value_kind,
            observation.origin,
            observation.idempotency_key,
            observation.raw_value,
            observation.basis,
        )
        if any(not isinstance(value, str) or not value.strip() for value in required_strings):
            raise ValueError(
                "Источник, тип, origin, ключ идемпотентности, значение и основание обязательны"
            )
        string_bounds = {
            "source": (observation.source, 128),
            "kind": (observation.kind, 40),
            "value_kind": (observation.value_kind, 40),
            "raw_value": (observation.raw_value, 500),
            "origin": (observation.origin, 120),
            "idempotency_key": (observation.idempotency_key, 200),
            "basis": (observation.basis, 2000),
        }
        if any(len(value) > maximum for value, maximum in string_bounds.values()):
            raise ValueError("Строковое поле кандидата превышает допустимую длину")
        if not isinstance(observation.observed_at, str) or len(observation.observed_at) > 40:
            raise ValueError("Время наблюдения превышает допустимую длину")
        if (
            not isinstance(observation.proposed_entity_ids, (tuple, list))
            or len(observation.proposed_entity_ids) > 20
        ):
            raise ValueError("Слишком много предложенных сущностей")
        if (
            not isinstance(observation.scope, dict)
            or not observation.scope
            or len(observation.scope) > 20
            or any(
                not isinstance(key, str)
                or not isinstance(value, str)
                or not key.strip()
                or len(key) > 50
                or len(value) > 200
                for key, value in observation.scope.items()
            )
        ):
            raise ValueError("Scope кандидата превышает допустимый размер")
        if any(
            not isinstance(entity_id, str) or not entity_id or len(entity_id) > 80
            for entity_id in observation.proposed_entity_ids
        ):
            raise ValueError("ID предложенной сущности превышает допустимую длину")
        if observation.facts is not None and not isinstance(observation.facts, dict):
            raise ValueError("Факты кандидата должны быть словарём строк")
        facts = observation.facts or {}
        if len(facts) > 40 or any(
            not isinstance(key, str)
            or not isinstance(value, str)
            or len(key) > 100
            or len(value) > 1000
            for key, value in facts.items()
        ):
            raise ValueError("Факты кандидата превышают допустимый размер")
        observed_at = _canonical_utc(observation.observed_at or datetime.now(UTC).isoformat())
        assert observed_at is not None
        facts_json = json.dumps(facts, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        proposed_json = json.dumps(
            sorted(set(observation.proposed_entity_ids)), separators=(",", ":")
        )
        with self.registry._connect() as connection:
            prior = connection.execute(
                "SELECT * FROM review_candidates WHERE origin=? AND idempotency_key=?",
                (observation.origin, observation.idempotency_key),
            ).fetchone()
            now = _timestamp()
            if prior is None:
                designation = self.registry._insert_designation(
                    connection,
                    entity_id=None,
                    source=observation.source,
                    kind=observation.kind,
                    scope=observation.scope,
                    value_kind=observation.value_kind,
                    raw_value=observation.raw_value,
                    state="pending",
                    valid_from=None,
                    valid_until=None,
                )
                candidate_id = str(uuid.uuid4())
                connection.execute(
                    "INSERT INTO review_candidates VALUES (?,?,?,?,?,?,?,?,1,'pending',?,?)",
                    (
                        candidate_id,
                        designation["id"],
                        observation.origin,
                        observation.idempotency_key,
                        observed_at,
                        facts_json,
                        proposed_json,
                        observation.basis,
                        now,
                        now,
                    ),
                )
                row = connection.execute(
                    "SELECT * FROM review_candidates WHERE id=?", (candidate_id,)
                ).fetchone()
            else:
                designation = connection.execute(
                    "SELECT * FROM designations WHERE id=?", (prior["designation_id"],)
                ).fetchone()
                if designation is None or (
                    designation["source"],
                    designation["kind"],
                    designation["scope_json"],
                    designation["value_kind"],
                    designation["raw_value"],
                ) != (
                    observation.source,
                    observation.kind,
                    self.registry._scope_json(observation.scope),
                    observation.value_kind,
                    observation.raw_value,
                ):
                    raise ValueError("Ключ идемпотентности уже занят другим scope или обозначением")
                same = (
                    prior["facts_json"],
                    prior["proposed_entity_ids_json"],
                    prior["basis"],
                ) == (facts_json, proposed_json, observation.basis)
                if same:
                    row = prior
                else:
                    connection.execute(
                        "INSERT INTO review_candidate_history VALUES (?,?,?,?,?,?,?,?)",
                        (
                            prior["id"],
                            prior["revision"],
                            prior["observed_at"],
                            prior["facts_json"],
                            prior["proposed_entity_ids_json"],
                            prior["basis"],
                            prior["status"],
                            now,
                        ),
                    )
                    connection.execute(
                        "UPDATE review_candidates SET observed_at=?,facts_json=?,proposed_entity_ids_json=?,basis=?,revision=revision+1,status='pending',updated_at=? WHERE id=?",
                        (
                            observed_at,
                            facts_json,
                            proposed_json,
                            observation.basis,
                            now,
                            prior["id"],
                        ),
                    )
                    if designation["state"] != "confirmed":
                        connection.execute(
                            "UPDATE designations SET state='pending',entity_id=NULL,revision=revision+1 WHERE id=?",
                            (prior["designation_id"],),
                        )
                    row = connection.execute(
                        "SELECT * FROM review_candidates WHERE id=?", (prior["id"],)
                    ).fetchone()
            assert row is not None
            return self._candidate(connection, row)

    def get(self, candidate_id: str) -> ReviewCandidate:
        """Получить кандидата по UUID."""
        with self.registry._connect(write=False) as connection:
            row = connection.execute(
                "SELECT * FROM review_candidates WHERE id=?", (candidate_id,)
            ).fetchone()
            if row is None:
                raise KeyError(candidate_id)
            return self._candidate(connection, row)

    def list_history(
        self, candidate_id: str, *, limit: int = 20, offset: int = 0
    ) -> list[CandidateEvidenceRevision]:
        """Вернуть ограниченную страницу прежних редакций evidence."""
        if not 1 <= limit <= 100 or offset < 0:
            raise ValueError("Недопустимые параметры пагинации истории")
        with self.registry._connect(write=False) as connection:
            exists = connection.execute(
                "SELECT 1 FROM review_candidates WHERE id=?", (candidate_id,)
            ).fetchone()
            if exists is None:
                raise KeyError(candidate_id)
            rows = connection.execute(
                "SELECT * FROM review_candidate_history WHERE candidate_id=? ORDER BY revision LIMIT ? OFFSET ?",
                (candidate_id, limit, offset),
            ).fetchall()
        return [
            CandidateEvidenceRevision(
                row["revision"],
                row["observed_at"],
                json.loads(row["facts_json"]),
                tuple(json.loads(row["proposed_entity_ids_json"])),
                row["basis"],
                row["status"],
            )
            for row in rows
        ]

    def list_candidates(
        self,
        *,
        status: str = "pending",
        query: str = "",
        source: str = "",
        tournament: str = "",
        limit: int = 50,
        offset: int = 0,
    ) -> list[ReviewCandidate]:
        """Вернуть ограниченную очередь с поиском по обозначению и источнику."""
        if not 1 <= limit <= 100 or offset < 0:
            raise ValueError("Недопустимые параметры пагинации")
        with self.registry._connect(write=False) as connection:
            rows = connection.execute(
                "SELECT c.* FROM review_candidates c JOIN designations d ON d.id=c.designation_id WHERE (?='' OR c.status=?) AND (?='' OR d.raw_value LIKE ? OR d.source LIKE ? OR c.basis LIKE ?) AND (?='' OR d.source=?) AND (?='' OR json_extract(d.scope_json,'$.tournament')=?) ORDER BY c.observed_at,c.id LIMIT ? OFFSET ?",
                (
                    "" if status == "all" else status,
                    "" if status == "all" else status,
                    query,
                    f"%{query}%",
                    f"%{query}%",
                    f"%{query}%",
                    source,
                    source,
                    tournament,
                    tournament,
                    limit,
                    offset,
                ),
            ).fetchall()
            return [self._candidate(connection, row) for row in rows]

    def search_entities(self, *, kind: str, query: str, limit: int = 50) -> list[Entity]:
        """Искать проектные сущности для выбора цели в review форме."""
        if not 1 <= limit <= 100 or len(query) > 100:
            raise ValueError("Недопустимые параметры поиска сущностей")
        if not query.strip():
            return []
        with self.registry._connect(write=False) as connection:
            rows = connection.execute(
                "SELECT * FROM entities WHERE state='active' AND kind=? AND project_name LIKE ? ORDER BY project_name,id LIMIT ?",
                (kind, f"%{query}%", limit),
            ).fetchall()
        return [
            Entity(row["id"], row["kind"], row["sport"], row["project_name"], row["revision"])
            for row in rows
        ]

    def decide_batch(
        self, decisions: list[CandidateDecision], *, actor: str
    ) -> list[ReviewCandidate]:
        """Применить до 20 решений в одной транзакции после полного preflight."""
        if not actor.strip() or not decisions or len(decisions) > 20:
            raise ValueError("Нужен автор и пакет от 1 до 20 решений")
        if len({item.candidate_id for item in decisions}) != len(decisions):
            raise ValueError("Пакет содержит повторный candidate_id")
        with self.registry._connect() as connection:
            validated: list[tuple[CandidateDecision, sqlite3.Row, sqlite3.Row]] = []
            for item in decisions:
                row = connection.execute(
                    "SELECT * FROM review_candidates WHERE id=?", (item.candidate_id,)
                ).fetchone()
                if row is None:
                    raise KeyError(item.candidate_id)
                designation = connection.execute(
                    "SELECT * FROM designations WHERE id=?", (row["designation_id"],)
                ).fetchone()
                if (
                    row["revision"] != item.expected_revision
                    or designation["revision"] != item.expected_designation_revision
                ):
                    raise ValueError("candidate/designation revision устарела; перечитайте очередь")
                if row["status"] != "pending" or not item.reason.strip():
                    raise ValueError("Кандидат уже закрыт или отсутствует основание решения")
                if item.action == "create_entity":
                    if item.new_entity is None or item.new_entity.kind not in (
                        "team",
                        "tournament",
                    ):
                        raise ValueError("Создание разрешено только для team или tournament")
                elif item.action == "confirm":
                    if item.entity_id is None:
                        raise ValueError("Подтверждение требует entity_id")
                    entity = connection.execute(
                        "SELECT kind FROM entities WHERE id=?", (item.entity_id,)
                    ).fetchone()
                    if entity is None or entity["kind"] != designation["kind"]:
                        raise ValueError("Тип целевой сущности не совпадает с designation")
                validated.append((item, row, designation))
            results: list[ReviewCandidate] = []
            for item, row, designation in validated:
                entity_id = item.entity_id
                action = item.action
                if action == "create_entity":
                    assert item.new_entity is not None
                    if item.new_entity.kind != designation["kind"]:
                        raise ValueError("Тип создаваемой сущности не совпадает с designation")
                    entity_id = str(uuid.uuid4())
                    now = _timestamp()
                    name = item.new_entity.project_name.strip()
                    if not name or not item.new_entity.sport.strip():
                        raise ValueError("Имя и sport обязательны")
                    connection.execute(
                        "INSERT INTO entities (id,kind,sport,project_name,revision,state,created_at,updated_at) VALUES (?,?,?, ?,1,'active',?,?)",
                        (
                            entity_id,
                            item.new_entity.kind,
                            item.new_entity.sport.strip(),
                            name,
                            now,
                            now,
                        ),
                    )
                    connection.execute(
                        "INSERT INTO entity_audit VALUES (?,?,?,?,?,?,?,?)",
                        (str(uuid.uuid4()), entity_id, actor, "create", item.reason, "", name, now),
                    )
                    action = "confirm"
                if action == "confirm":
                    peers = connection.execute(
                        "SELECT * FROM designations WHERE source=? AND kind=? AND scope_json=? AND value_kind=? AND normalized_value=? AND id<>?",
                        (
                            designation["source"],
                            designation["kind"],
                            designation["scope_json"],
                            designation["value_kind"],
                            designation["normalized_value"],
                            designation["id"],
                        ),
                    ).fetchall()
                    if designation["state"] == "conflict" or any(
                        peer["state"] in ("pending", "conflict", "confirmed")
                        and peer["entity_id"] != entity_id
                        and self.registry._intervals_overlap(
                            designation["valid_from"],
                            designation["valid_until"],
                            peer["valid_from"],
                            peer["valid_until"],
                        )
                        for peer in peers
                    ):
                        raise ValueError(
                            "Нельзя подтвердить designation с пересекающимся конфликтом"
                        )
                    target = "confirmed"
                elif action == "reject":
                    target = "rejected"
                elif action == "defer":
                    target = "deferred"
                else:
                    raise ValueError("Неизвестное действие")
                now = _timestamp()
                if target == "confirmed":
                    connection.execute(
                        "UPDATE designations SET state='confirmed',entity_id=?,revision=revision+1 WHERE id=?",
                        (entity_id, row["designation_id"]),
                    )
                elif designation["state"] == "confirmed":
                    # Решение по новым evidence не отзывает уже подтверждённую связь.
                    connection.execute(
                        "UPDATE designations SET revision=revision+1 WHERE id=?",
                        (row["designation_id"],),
                    )
                else:
                    connection.execute(
                        "UPDATE designations SET state=?,entity_id=NULL,revision=revision+1 WHERE id=?",
                        (target, row["designation_id"]),
                    )
                connection.execute(
                    "INSERT INTO decisions (id,designation_id,actor,action,reason,prior_state,prior_revision,decided_at) VALUES (?,?,?,?,?,?,?,?)",
                    (
                        str(uuid.uuid4()),
                        row["designation_id"],
                        actor,
                        action,
                        item.reason,
                        designation["state"],
                        designation["revision"],
                        now,
                    ),
                )
                connection.execute(
                    "UPDATE review_candidates SET status=?,updated_at=? WHERE id=?",
                    (target, now, item.candidate_id),
                )
                fresh = connection.execute(
                    "SELECT * FROM review_candidates WHERE id=?", (item.candidate_id,)
                ).fetchone()
                assert fresh is not None
                results.append(self._candidate(connection, fresh))
            return results
