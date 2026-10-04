"""Durable outbox и Object Storage transport для registry candidate feedback."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from sports_forecast.identity.publication import (
    ConditionalWriteConflictError,
    StorageObject,
)
from sports_forecast.service.db.models import (
    RegistryCandidateBatchSequence,
    RegistryCandidateOutbox,
)


_MAX_BATCH_ROWS = 100
_MAX_BATCH_BYTES = 1024 * 1024


class FeedbackStorage(Protocol):
    """Минимальные Object Storage операции в собственном candidates prefix."""

    def get(self, key: str, *, max_bytes: int | None = None) -> StorageObject: ...

    def put(
        self,
        key: str,
        body: bytes,
        *,
        if_match: str | None = None,
        if_none_match: bool = False,
    ) -> str: ...


class RegistryFeedbackError(RuntimeError):
    """Ошибка проверки, публикации или acknowledgement candidate batch."""


def installation_id_from_environment() -> str:
    """Прочитать обязательный стабильный UUID установки server feedback."""
    value = os.environ.get("SF_ENTITY_REGISTRY_INSTALLATION_ID", "")
    if not value:
        raise RegistryFeedbackError("SF_ENTITY_REGISTRY_INSTALLATION_ID не задан")
    try:
        return _uuid(value, "installation_id")
    except ValueError as exc:
        raise RegistryFeedbackError("SF_ENTITY_REGISTRY_INSTALLATION_ID должен быть UUID") from exc


@dataclass(frozen=True)
class CandidateObservation:
    """Portable evidence row совместимая с локальным ReviewQueue importer."""

    source: str
    kind: str
    scope: dict[str, str]
    value_kind: str
    raw_value: str
    origin: str
    idempotency_key: str
    observed_at: str
    facts: dict[str, str]
    proposed_entity_ids: tuple[str, ...]
    basis: str


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _object_key(prefix: str, *parts: str) -> str:
    return "/".join((prefix, *parts))


def _uuid(value: str, label: str) -> str:
    try:
        normalized = str(UUID(value))
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"{label} должен быть UUID") from exc
    if normalized != value:
        raise ValueError(f"{label} должен быть каноническим UUID")
    return normalized


def _canonical_time(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError) as exc:
        raise ValueError("observed_at должен содержать ISO timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("observed_at должен содержать timezone")
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _payload(observation: CandidateObservation, *, installation_id: str) -> dict[str, Any]:
    bounds = {
        "source": (observation.source, 128),
        "kind": (observation.kind, 40),
        "value_kind": (observation.value_kind, 40),
        "raw_value": (observation.raw_value, 500),
        "idempotency_key": (observation.idempotency_key, 200),
        "basis": (observation.basis, 2000),
    }
    if any(
        not isinstance(value, str) or not value.strip() or len(value) > maximum
        for value, maximum in bounds.values()
    ):
        raise ValueError("Candidate содержит пустое или недопустимое строковое поле")
    if (
        not isinstance(observation.scope, dict)
        or not observation.scope
        or len(observation.scope) > 20
    ):
        raise ValueError("Candidate scope пуст или превышает лимит")
    if any(
        not isinstance(key, str)
        or not isinstance(value, str)
        or not key.strip()
        or len(key) > 50
        or len(value) > 200
        for key, value in observation.scope.items()
    ):
        raise ValueError("Candidate scope содержит недопустимые поля")
    if (
        not isinstance(observation.facts, dict)
        or len(observation.facts) > 40
        or any(
            not isinstance(key, str)
            or not isinstance(value, str)
            or len(key) > 100
            or len(value) > 1000
            for key, value in observation.facts.items()
        )
    ):
        raise ValueError("Candidate facts содержат недопустимые поля")
    if (
        not isinstance(observation.proposed_entity_ids, (tuple, list))
        or len(observation.proposed_entity_ids) > 20
        or any(
            not isinstance(item, str) or not item or len(item) > 80
            for item in observation.proposed_entity_ids
        )
    ):
        raise ValueError("Candidate proposed_entity_ids превышают лимит")
    return {
        "source": observation.source.strip(),
        "kind": observation.kind.strip(),
        "scope": dict(sorted(observation.scope.items())),
        "value_kind": observation.value_kind.strip(),
        "raw_value": observation.raw_value.strip(),
        "origin": f"server:{installation_id}",
        "idempotency_key": observation.idempotency_key.strip(),
        "observed_at": _canonical_time(observation.observed_at),
        "facts": dict(sorted(observation.facts.items())),
        "proposed_entity_ids": sorted(set(observation.proposed_entity_ids)),
        "basis": observation.basis.strip(),
    }


class RegistryCandidateFeedback:
    """Транзакционный outbox и идемпотентный publisher candidate batch-ей."""

    def __init__(
        self,
        session: Session,
        storage: FeedbackStorage | None = None,
        *,
        prefix: str,
        installation_id: str,
        max_rows: int = _MAX_BATCH_ROWS,
        max_bytes: int = _MAX_BATCH_BYTES,
    ) -> None:
        normalized_prefix = prefix.strip("/")
        if not normalized_prefix or any(
            part in {"", ".", ".."} for part in normalized_prefix.split("/")
        ):
            raise ValueError("Некорректный Object Storage prefix")
        if not 1 <= max_rows <= _MAX_BATCH_ROWS or not 1 <= max_bytes <= _MAX_BATCH_BYTES:
            raise ValueError("Feedback batch limits превышают установленные пределы")
        self._session = session
        self._storage = storage
        self._prefix = normalized_prefix
        self._installation_id = _uuid(installation_id, "installation_id")
        self._max_rows = max_rows
        self._max_bytes = max_bytes

    def _require_storage(self) -> FeedbackStorage:
        if self._storage is None:
            raise RegistryFeedbackError("Feedback Object Storage transport не настроен")
        return self._storage

    def enqueue(self, observation: CandidateObservation) -> RegistryCandidateOutbox:
        """Добавить occurrence в той же DB транзакции без схлопывания наблюдений."""
        payload = _payload(observation, installation_id=self._installation_id)
        if payload["idempotency_key"] != observation.idempotency_key.strip():
            raise ValueError("Невалидный idempotency key")
        row = RegistryCandidateOutbox(
            installation_id=self._installation_id,
            idempotency_key=payload["idempotency_key"],
            payload_json=_canonical_json(payload).decode("utf-8"),
            status="pending",
        )
        self._session.add(row)
        self._session.flush()
        return row

    def publish_next_batch(self) -> str | None:
        """Публиковать durable batch или возобновить staged immutable batch."""
        storage = self._require_storage()
        rows = self._load_staged_batch()
        if not rows:
            rows = self._stage_pending_batch()
        if not rows:
            return None
        batch_id = rows[0].batch_id
        assert batch_id is not None
        body = self._batch_bytes(rows)
        if len(body) > self._max_bytes:
            raise RegistryFeedbackError("Staged candidate batch превышает byte limit")
        key = _object_key(self._prefix, "candidates", self._installation_id, f"{batch_id}.jsonl")
        put_error: Exception | None = None
        try:
            storage.put(key, body, if_none_match=True)
        except Exception as exc:
            put_error = exc
        try:
            remote = storage.get(key, max_bytes=self._max_bytes)
        except Exception as exc:
            self._record_attempt(rows, "upload_failed")
            raise RegistryFeedbackError(
                "Candidate batch upload не подтверждён; batch сохранён"
            ) from (put_error or exc)
        if remote.body != body:
            self._record_attempt(rows, "upload_failed")
            reason = "Remote candidate batch не совпадает с outbox bytes"
            if put_error is not None and isinstance(put_error, ConditionalWriteConflictError):
                reason = "Immutable candidate key уже содержит другие bytes"
            raise RegistryFeedbackError(reason) from put_error
        now = datetime.now(UTC).replace(tzinfo=None)
        for row in rows:
            row.status = "awaiting_ack"
            row.published_at = now
            row.last_error_code = None
        self._session.commit()
        return batch_id

    def collect_acknowledgements(self, *, max_batches: int = 100) -> int:
        """Применить ack не более заданного числа локально импортированных batch-ей."""
        storage = self._require_storage()
        if not 1 <= max_batches <= 1000:
            raise ValueError("max_batches должен быть от 1 до 1000")
        batch_ids = list(
            self._session.scalars(
                select(RegistryCandidateOutbox.__table__.c.batch_id)
                .where(
                    RegistryCandidateOutbox.__table__.c.installation_id == self._installation_id,
                    RegistryCandidateOutbox.__table__.c.status == "awaiting_ack",
                )
                .group_by(RegistryCandidateOutbox.__table__.c.batch_id)
                .order_by(RegistryCandidateOutbox.__table__.c.batch_id)
                .limit(max_batches)
            )
        )
        acknowledged = 0
        for batch_id in batch_ids:
            if not isinstance(batch_id, str):
                continue
            key = _object_key(
                self._prefix, "candidate-acks", self._installation_id, f"{batch_id}.json"
            )
            try:
                body = storage.get(key, max_bytes=4096).body
            except FileNotFoundError:
                continue
            self._validate_ack(body, batch_id)
            now = datetime.now(UTC).replace(tzinfo=None)
            batch_rows = list(
                self._session.scalars(
                    select(RegistryCandidateOutbox).where(
                        RegistryCandidateOutbox.__table__.c.installation_id
                        == self._installation_id,
                        RegistryCandidateOutbox.__table__.c.batch_id == batch_id,
                        RegistryCandidateOutbox.__table__.c.status == "awaiting_ack",
                    )
                )
            )
            for row in batch_rows:
                row.status = "acknowledged"
                row.acknowledged_at = now
            acknowledged += 1
        if acknowledged:
            self._session.commit()
        return acknowledged

    def _stage_pending_batch(self) -> list[RegistryCandidateOutbox]:
        rows = list(
            self._session.scalars(
                select(RegistryCandidateOutbox)
                .where(
                    RegistryCandidateOutbox.__table__.c.installation_id == self._installation_id,
                    RegistryCandidateOutbox.__table__.c.status == "pending",
                )
                .order_by(RegistryCandidateOutbox.__table__.c.id)
                .limit(self._max_rows + 1)
                .with_for_update(skip_locked=True)
            )
        )
        if not rows:
            return []
        selected: list[RegistryCandidateOutbox] = []
        selected_keys: set[str] = set()
        size = 0
        for row in rows:
            if row.idempotency_key in selected_keys:
                continue
            line_size = len(row.payload_json.encode("utf-8")) + 1
            if not selected and line_size > self._max_bytes:
                raise RegistryFeedbackError("Candidate превышает batch byte limit")
            if len(selected) >= self._max_rows or size + line_size > self._max_bytes:
                break
            selected.append(row)
            selected_keys.add(row.idempotency_key)
            size += line_size
        sequence = self._allocate_batch_sequence()
        batch_id = f"{sequence:020d}-{uuid4()}"
        for row in selected:
            row.status = "staged"
            row.batch_id = batch_id
        self._session.commit()
        return selected

    def _allocate_batch_sequence(self) -> int:
        dialect = self._session.get_bind().dialect.name
        if dialect == "postgresql":
            from sqlalchemy.dialects.postgresql import insert as pg_insert

            insert_statement: Any = pg_insert(RegistryCandidateBatchSequence)
        elif dialect == "sqlite":
            from sqlalchemy.dialects.sqlite import insert as sqlite_insert

            insert_statement = sqlite_insert(RegistryCandidateBatchSequence)
        else:
            raise RegistryFeedbackError("Feedback outbox поддерживает только PostgreSQL и SQLite")
        self._session.execute(
            insert_statement.values(
                installation_id=self._installation_id, last_sequence=0
            ).on_conflict_do_nothing(index_elements=["installation_id"])
        )
        counter = self._session.scalar(
            select(RegistryCandidateBatchSequence)
            .where(
                RegistryCandidateBatchSequence.__table__.c.installation_id == self._installation_id
            )
            .with_for_update()
        )
        if counter is None:
            raise RegistryFeedbackError("Не удалось создать counter candidate batch")
        counter.last_sequence += 1
        self._session.flush()
        return int(counter.last_sequence)

    def _load_staged_batch(self) -> list[RegistryCandidateOutbox]:
        first = self._session.scalar(
            select(RegistryCandidateOutbox)
            .where(
                RegistryCandidateOutbox.__table__.c.installation_id == self._installation_id,
                RegistryCandidateOutbox.__table__.c.status == "staged",
            )
            .order_by(RegistryCandidateOutbox.__table__.c.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if first is None or first.batch_id is None:
            return []
        return list(
            self._session.scalars(
                select(RegistryCandidateOutbox)
                .where(
                    RegistryCandidateOutbox.__table__.c.installation_id == self._installation_id,
                    RegistryCandidateOutbox.__table__.c.batch_id == first.batch_id,
                    RegistryCandidateOutbox.__table__.c.status == "staged",
                )
                .order_by(RegistryCandidateOutbox.__table__.c.id)
                .with_for_update(skip_locked=True)
            )
        )

    @staticmethod
    def _batch_bytes(rows: list[RegistryCandidateOutbox]) -> bytes:
        ordered = sorted(rows, key=lambda row: row.idempotency_key)
        if len({row.idempotency_key for row in ordered}) != len(ordered):
            raise RegistryFeedbackError("Batch содержит повторный idempotency key")
        body = b"".join(row.payload_json.encode("utf-8") + b"\n" for row in ordered)
        if len(ordered) > _MAX_BATCH_ROWS or len(body) > _MAX_BATCH_BYTES:
            raise RegistryFeedbackError("Batch превышает опубликованные пределы")
        return body

    def _record_attempt(self, rows: list[RegistryCandidateOutbox], code: str) -> None:
        for row in rows:
            row.attempts += 1
            row.last_error_code = code
        self._session.commit()

    def _validate_ack(self, body: bytes, batch_id: str) -> None:
        if len(body) > 16_384:
            raise RegistryFeedbackError("Candidate acknowledgement превышает 16 KiB")
        try:
            ack = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RegistryFeedbackError("Candidate acknowledgement повреждён") from exc
        if not isinstance(ack, dict) or set(ack) != {
            "schema_version",
            "installation_id",
            "batch_id",
            "received_at",
        }:
            raise RegistryFeedbackError("Candidate acknowledgement имеет неверную схему")
        if body != _canonical_json(ack) + b"\n":
            raise RegistryFeedbackError("Candidate acknowledgement неканоничен")
        received_at = ack["received_at"]
        try:
            if not isinstance(received_at, str):
                raise ValueError
            timestamp = datetime.fromisoformat(received_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise RegistryFeedbackError("Candidate acknowledgement timestamp неверен") from exc
        if (
            ack["schema_version"] != 1
            or isinstance(ack["schema_version"], bool)
            or ack["installation_id"] != self._installation_id
            or ack["batch_id"] != batch_id
            or timestamp.tzinfo is None
            or timestamp.utcoffset() is None
            or timestamp.utcoffset() != timedelta(0)
        ):
            raise RegistryFeedbackError("Candidate acknowledgement не соответствует batch")


def enqueue_registry_candidate(
    session: Session,
    observation: CandidateObservation,
    *,
    installation_id: str,
) -> RegistryCandidateOutbox:
    """Сохранить candidate без подключения к Object Storage и его credentials."""
    service = RegistryCandidateFeedback(
        session,
        prefix="entity-registry/v1",
        installation_id=installation_id,
    )
    return service.enqueue(observation)
