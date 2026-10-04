"""Проверки server outbox, immutable feedback batch и ack."""

from __future__ import annotations

import json
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from sports_forecast.identity.publication import ConditionalWriteConflictError, StorageObject
from sports_forecast.service.db.models import Base, RegistryCandidateOutbox
from sports_forecast.service.db.registry_feedback import (
    CandidateObservation,
    RegistryCandidateFeedback,
    RegistryFeedbackError,
    enqueue_registry_candidate,
    installation_id_from_environment,
)


def test_postgres_batch_column_fits_sortable_sequence_and_uuid() -> None:
    """Длина sortable batch ID должна помещаться в PostgreSQL VARCHAR."""
    batch_column = RegistryCandidateOutbox.__table__.c.batch_id
    assert batch_column.type.length is not None
    assert batch_column.type.length >= len(f"{1:020d}-{uuid4()}")


class MemoryStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.put_keys: list[str] = []
        self.fail_after_put = False

    def get(self, key: str, *, max_bytes: int | None = None) -> StorageObject:
        if key not in self.objects:
            raise FileNotFoundError(key)
        body = self.objects[key]
        if max_bytes is not None and len(body) > max_bytes:
            raise RuntimeError("max_bytes exceeded")
        return StorageObject(body, "etag")

    def put(
        self,
        key: str,
        body: bytes,
        *,
        if_match: str | None = None,
        if_none_match: bool = False,
    ) -> str:
        self.put_keys.append(key)
        if if_none_match and key in self.objects:
            raise ConditionalWriteConflictError("already exists")
        self.objects[key] = body
        if self.fail_after_put:
            self.fail_after_put = False
            raise TimeoutError("response lost")
        return "etag"


def _engine():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return engine


def _candidate(key: str = "sports-feed:event:evt-1") -> CandidateObservation:
    return CandidateObservation(
        source="sports-feed",
        kind="event",
        scope={"sport": "ice_hockey", "tournament": "cup-1"},
        value_kind="external_id",
        raw_value="evt-1",
        origin="ignored",
        idempotency_key=key,
        observed_at="2026-10-04T10:00:00Z",
        facts={"home": "North", "away": "South"},
        proposed_entity_ids=(),
        basis="Unresolved source event identity",
    )


def _publisher(
    session: Session, storage: MemoryStorage, installation_id: str
) -> RegistryCandidateFeedback:
    return RegistryCandidateFeedback(
        session,
        storage,
        prefix="entity-registry/v1",
        installation_id=installation_id,
    )


def test_enqueue_retains_each_occurrence_for_local_seen_count() -> None:
    engine = _engine()
    installation_id = str(uuid4())
    with Session(engine) as session:
        publisher = _publisher(session, MemoryStorage(), installation_id)
        first = publisher.enqueue(_candidate())
        duplicate = publisher.enqueue(_candidate())
        assert first.id != duplicate.id
        rows = list(session.scalars(select(RegistryCandidateOutbox)))
        assert len(rows) == 2
        assert {row.idempotency_key for row in rows} == {"sports-feed:event:evt-1"}
    engine.dispose()


def test_batch_is_canonical_and_ack_marks_delivery_only() -> None:
    engine = _engine()
    installation_id = str(uuid4())
    storage = MemoryStorage()
    with Session(engine) as session:
        publisher = _publisher(session, storage, installation_id)
        publisher.enqueue(_candidate())
        publisher.enqueue(_candidate())
        batch_id = publisher.publish_next_batch()
        assert batch_id is not None
        assert batch_id.startswith("00000000000000000001-")
        batch_key = f"entity-registry/v1/candidates/{installation_id}/{batch_id}.jsonl"
        body = storage.objects[batch_key]
        row = json.loads(body)
        assert set(row) == {
            "source",
            "kind",
            "scope",
            "value_kind",
            "raw_value",
            "origin",
            "idempotency_key",
            "observed_at",
            "facts",
            "proposed_entity_ids",
            "basis",
        }
        assert body.endswith(b"\n")
        assert row["origin"] == f"server:{installation_id}"
        second_batch_id = publisher.publish_next_batch()
        assert second_batch_id is not None
        assert second_batch_id.startswith("00000000000000000002-")
        second_key = f"entity-registry/v1/candidates/{installation_id}/{second_batch_id}.jsonl"
        second_rows = [json.loads(line) for line in storage.objects[second_key].splitlines()]
        assert [item["idempotency_key"] for item in second_rows] == [row["idempotency_key"]]
        assert publisher.collect_acknowledgements() == 0
        ack_key = f"entity-registry/v1/candidate-acks/{installation_id}/{batch_id}.json"
        storage.objects[ack_key] = (
            json.dumps(
                {
                    "schema_version": 1,
                    "installation_id": installation_id,
                    "batch_id": batch_id,
                    "received_at": "2026-10-04T10:02:00Z",
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode()
        assert publisher.collect_acknowledgements() == 1
        assert publisher.collect_acknowledgements() == 0
        item = session.scalar(select(RegistryCandidateOutbox))
        assert item is not None and item.status == "acknowledged"
    engine.dispose()


def test_lost_put_response_recovers_same_immutable_batch() -> None:
    engine = _engine()
    installation_id = str(uuid4())
    storage = MemoryStorage()
    storage.fail_after_put = True
    with Session(engine) as session:
        publisher = _publisher(session, storage, installation_id)
        publisher.enqueue(_candidate())
        batch_id = publisher.publish_next_batch()
        assert batch_id is not None
        item = session.scalar(select(RegistryCandidateOutbox))
        assert item is not None and item.status == "awaiting_ack"
        key = f"entity-registry/v1/candidates/{installation_id}/{batch_id}.jsonl"
        assert storage.objects[key]
        assert len(set(storage.put_keys)) == 1
        publisher.enqueue(_candidate("sports-feed:event:evt-2"))
        next_batch_id = publisher.publish_next_batch()
        assert next_batch_id is not None
        assert next_batch_id.startswith("00000000000000000002-")
    engine.dispose()


def test_invalid_ack_keeps_batch_waiting_for_owner_import() -> None:
    engine = _engine()
    installation_id = str(uuid4())
    storage = MemoryStorage()
    with Session(engine) as session:
        publisher = _publisher(session, storage, installation_id)
        publisher.enqueue(_candidate())
        batch_id = publisher.publish_next_batch()
        assert batch_id is not None
        ack_key = f"entity-registry/v1/candidate-acks/{installation_id}/{batch_id}.json"
        storage.objects[ack_key] = b'{"wrong":true}\n'
        with pytest.raises(RegistryFeedbackError):
            publisher.collect_acknowledgements()
        item = session.scalar(select(RegistryCandidateOutbox))
        assert item is not None and item.status == "awaiting_ack"
    engine.dispose()


def test_oversized_row_stays_pending() -> None:
    engine = _engine()
    installation_id = str(uuid4())
    with Session(engine) as session:
        publisher = RegistryCandidateFeedback(
            session,
            MemoryStorage(),
            prefix="entity-registry/v1",
            installation_id=installation_id,
            max_bytes=100,
        )
        publisher.enqueue(_candidate())
        with pytest.raises(RegistryFeedbackError, match="превышает|limit"):
            publisher.publish_next_batch()
        item = session.scalar(select(RegistryCandidateOutbox))
        assert item is not None and item.status == "pending" and item.batch_id is None
    engine.dispose()


def test_acquisition_enqueue_needs_no_storage_and_reads_required_installation_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _engine()
    installation_id = str(uuid4())
    monkeypatch.setenv("SF_ENTITY_REGISTRY_INSTALLATION_ID", installation_id)
    assert installation_id_from_environment() == installation_id
    with Session(engine) as session:
        row = enqueue_registry_candidate(
            session,
            _candidate(),
            installation_id=installation_id,
        )
        assert row.status == "pending"
        with pytest.raises(RegistryFeedbackError, match="transport"):
            RegistryCandidateFeedback(
                session,
                prefix="entity-registry/v1",
                installation_id=installation_id,
            ).publish_next_batch()
        assert row.status == "pending" and row.batch_id is None
    engine.dispose()


def test_missing_installation_id_is_configuration_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SF_ENTITY_REGISTRY_INSTALLATION_ID", raising=False)
    with pytest.raises(RegistryFeedbackError, match="не задан"):
        installation_id_from_environment()


def test_ack_collection_stops_at_requested_batch_limit() -> None:
    engine = _engine()
    installation_id = str(uuid4())
    storage = MemoryStorage()
    with Session(engine) as session:
        publisher = RegistryCandidateFeedback(
            session,
            storage,
            prefix="entity-registry/v1",
            installation_id=installation_id,
            max_rows=1,
        )
        publisher.enqueue(_candidate("feed:event:one"))
        publisher.enqueue(_candidate("feed:event:two"))
        batch_ids = [publisher.publish_next_batch(), publisher.publish_next_batch()]
        assert all(batch_ids)
        for batch_id in batch_ids:
            key = f"entity-registry/v1/candidate-acks/{installation_id}/{batch_id}.json"
            storage.objects[key] = (
                json.dumps(
                    {
                        "schema_version": 1,
                        "installation_id": installation_id,
                        "batch_id": batch_id,
                        "received_at": "2026-10-04T10:02:00Z",
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            ).encode()

        assert publisher.collect_acknowledgements(max_batches=1) == 1
        statuses = sorted(row.status for row in session.scalars(select(RegistryCandidateOutbox)))
        assert statuses == ["acknowledged", "awaiting_ack"]
    engine.dispose()
