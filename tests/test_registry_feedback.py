"""Локальный импорт server candidate batches и подтверждение durable ack."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from sports_forecast.identity.feedback import (
    CandidateFeedbackError,
    import_candidate_batch,
    import_pending_candidate_batches,
)
from sports_forecast.identity.publication import (
    ConditionalWriteConflictError,
    StorageObject,
)
from sports_forecast.identity.registry import EntityRegistry
from sports_forecast.identity.review_service import ReviewQueueService
from sports_forecast.service.db.models import Base, RegistryCandidateOutbox
from sports_forecast.service.db.registry_feedback import (
    CandidateObservation as ServerCandidateObservation,
)
from sports_forecast.service.db.registry_feedback import (
    RegistryCandidateFeedback,
)


class MemoryFeedbackStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.fail_ack_after_write = False
        self.fail_ack_before_write = False

    def list_keys(
        self,
        prefix: str,
        *,
        continuation_token: str | None = None,
        start_after: str | None = None,
        max_keys: int = 1000,
    ) -> tuple[tuple[str, ...], str | None]:
        keys = sorted(
            key
            for key in self.objects
            if key.startswith(prefix) and (start_after is None or key > start_after)
        )
        start = int(continuation_token or 0)
        page = keys[start : start + max_keys]
        next_token = str(start + len(page)) if start + len(page) < len(keys) else None
        return tuple(page), next_token

    def get(self, key: str, *, max_bytes: int | None = None) -> StorageObject:
        if key not in self.objects:
            raise FileNotFoundError(key)
        body = self.objects[key]
        if max_bytes is not None and len(body) > max_bytes:
            raise CandidateFeedbackError("Object exceeds max_bytes")
        return StorageObject(body, hashlib.sha256(body).hexdigest())

    def put(
        self,
        key: str,
        body: bytes,
        *,
        if_match: str | None = None,
        if_none_match: bool = False,
    ) -> str:
        if self.fail_ack_before_write and "/candidate-acks/" in key:
            self.fail_ack_before_write = False
            raise TimeoutError("ack PUT outcome unknown")
        if if_none_match and key in self.objects:
            raise ConditionalWriteConflictError("precondition conflict")
        if if_match is not None and (
            key not in self.objects or hashlib.sha256(self.objects[key]).hexdigest() != if_match
        ):
            raise ConditionalWriteConflictError("etag conflict")
        self.objects[key] = body
        etag = hashlib.sha256(body).hexdigest()
        if self.fail_ack_after_write and "/candidate-acks/" in key:
            self.fail_ack_after_write = False
            raise TimeoutError("ack PUT response lost")
        return etag


def _line(value: dict[str, object]) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        + b"\n"
    )


def _observation(installation_id: str, key: str = "event-1") -> dict[str, object]:
    return {
        "source": "sports-feed",
        "kind": "team",
        "scope": {"sport": "hockey", "tournament": str(uuid4())},
        "value_kind": "name",
        "raw_value": "North Stars",
        "origin": f"server:{installation_id}",
        "idempotency_key": key,
        "observed_at": "2026-10-04T12:00:00Z",
        "facts": {"source_event_id": "event-123"},
        "proposed_entity_ids": [],
        "basis": "No confirmed designation matched",
    }


def _batch_id(sequence: int) -> str:
    return f"{sequence:020d}-{uuid4()}"


def _batch(
    storage: MemoryFeedbackStorage,
    installation_id: str,
    batch_id: str,
    rows: list[dict[str, object]],
) -> str:
    key = f"entity-registry/v1/candidates/{installation_id}/{batch_id}.jsonl"
    storage.objects[key] = b"".join(_line(row) for row in rows)
    return key


def test_import_commits_candidate_before_ack_and_lost_ack_retries_idempotently(
    tmp_path: Path,
) -> None:
    installation_id, batch_id = str(uuid4()), _batch_id(1)
    storage = MemoryFeedbackStorage()
    _batch(storage, installation_id, batch_id, [_observation(installation_id)])
    storage.fail_ack_after_write = True
    registry = EntityRegistry(tmp_path / "registry.sqlite3")
    registry.initialize()

    with pytest.raises(TimeoutError):
        import_candidate_batch(
            storage,
            registry,
            prefix="entity-registry/v1",
            installation_id=installation_id,
            batch_id=batch_id,
        )
    queue = ReviewQueueService(registry)
    assert len(queue.list_candidates(source="sports-feed")) == 1
    retry = import_candidate_batch(
        storage,
        registry,
        prefix="entity-registry/v1",
        installation_id=installation_id,
        batch_id=batch_id,
    )
    assert retry.acknowledged
    assert len(queue.list_candidates(source="sports-feed")) == 1


def test_bad_batch_is_rejected_before_any_candidate_is_persisted(tmp_path: Path) -> None:
    installation_id, batch_id = str(uuid4()), _batch_id(1)
    storage = MemoryFeedbackStorage()
    valid = _observation(installation_id, "one")
    invalid = {**_observation(installation_id, "two"), "unexpected": "field"}
    _batch(storage, installation_id, batch_id, [valid, invalid])
    registry = EntityRegistry(tmp_path / "registry.sqlite3")
    registry.initialize()

    with pytest.raises(CandidateFeedbackError):
        import_candidate_batch(
            storage,
            registry,
            prefix="entity-registry/v1",
            installation_id=installation_id,
            batch_id=batch_id,
        )
    assert ReviewQueueService(registry).list_candidates(source="sports-feed") == []
    assert not any("candidate-acks" in key for key in storage.objects)


def test_batch_retry_and_listing_do_not_duplicate_candidates(tmp_path: Path) -> None:
    installation_id = str(uuid4())
    storage = MemoryFeedbackStorage()
    batch_one, batch_two = _batch_id(1), _batch_id(2)
    _batch(storage, installation_id, batch_one, [_observation(installation_id, "one")])
    _batch(storage, installation_id, batch_two, [_observation(installation_id, "two")])
    registry = EntityRegistry(tmp_path / "registry.sqlite3")
    registry.initialize()

    first = import_pending_candidate_batches(
        storage,
        registry,
        prefix="entity-registry/v1",
        installation_id=installation_id,
        max_batches=1,
    )
    second = import_pending_candidate_batches(
        storage,
        registry,
        prefix="entity-registry/v1",
        installation_id=installation_id,
        max_batches=10,
    )
    assert first.acknowledged_batches == 1
    assert second.scanned_batches == 1
    assert second.acknowledged_batches == 1
    assert second.imported_candidates == 1
    assert len(ReviewQueueService(registry).list_candidates(source="sports-feed")) == 2


def test_ack_failure_does_not_advance_cursor_and_retry_reuses_candidate(tmp_path: Path) -> None:
    installation_id = str(uuid4())
    batch_id = _batch_id(1)
    storage = MemoryFeedbackStorage()
    _batch(storage, installation_id, batch_id, [_observation(installation_id)])
    storage.fail_ack_before_write = True
    registry = EntityRegistry(tmp_path / "registry.sqlite3")
    registry.initialize()

    with pytest.raises(TimeoutError):
        import_pending_candidate_batches(
            storage,
            registry,
            prefix="entity-registry/v1",
            installation_id=installation_id,
            max_batches=1,
        )
    assert registry.candidate_feedback_cursor(installation_id) == 0
    assert len(ReviewQueueService(registry).list_candidates(source="sports-feed")) == 1

    result = import_pending_candidate_batches(
        storage,
        registry,
        prefix="entity-registry/v1",
        installation_id=installation_id,
        max_batches=1,
    )
    assert result.acknowledged_batches == 1
    assert registry.candidate_feedback_cursor(installation_id) == 1
    assert len(ReviewQueueService(registry).list_candidates(source="sports-feed")) == 1


def test_missing_batch_sequence_stops_without_skipping_cursor(tmp_path: Path) -> None:
    installation_id = str(uuid4())
    storage = MemoryFeedbackStorage()
    _batch(storage, installation_id, _batch_id(2), [_observation(installation_id)])
    registry = EntityRegistry(tmp_path / "registry.sqlite3")
    registry.initialize()

    with pytest.raises(CandidateFeedbackError, match="пропуск"):
        import_pending_candidate_batches(
            storage,
            registry,
            prefix="entity-registry/v1",
            installation_id=installation_id,
        )
    assert registry.candidate_feedback_cursor(installation_id) == 0
    assert ReviewQueueService(registry).list_candidates(source="sports-feed") == []


def test_local_registry_v9_migrates_candidate_cursor_table(tmp_path: Path) -> None:
    registry = EntityRegistry(tmp_path / "registry.sqlite3")
    registry.initialize()
    with registry._connect() as connection:
        connection.execute("DROP TABLE candidate_feedback_import_batches")
        connection.execute("DROP TABLE candidate_feedback_cursors")
        connection.execute("ALTER TABLE review_candidates DROP COLUMN observation_count")
        connection.execute("ALTER TABLE review_candidates DROP COLUMN last_seen_at")
        connection.execute("ALTER TABLE review_candidates DROP COLUMN first_seen_at")
        connection.execute("PRAGMA user_version = 9")
    registry.initialize()
    assert registry.candidate_feedback_cursor(str(uuid4())) == 0
    with registry._connect(write=False) as connection:
        columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(review_candidates)")
        }
    assert {"first_seen_at", "last_seen_at", "observation_count"} <= columns


def test_server_outbox_local_import_ack_round_trip(tmp_path: Path) -> None:
    installation_id = str(uuid4())
    storage = MemoryFeedbackStorage()
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    registry = EntityRegistry(tmp_path / "registry.sqlite3")
    registry.initialize()

    with Session(engine) as session:
        publisher = RegistryCandidateFeedback(
            session,
            storage,
            prefix="entity-registry/v1",
            installation_id=installation_id,
        )
        publisher.enqueue(
            ServerCandidateObservation(
                source="sports-feed",
                kind="team",
                scope={"sport": "hockey", "tournament": str(uuid4())},
                value_kind="name",
                raw_value="North Stars",
                origin="ignored",
                idempotency_key="event-1",
                observed_at="2026-10-04T12:00:00Z",
                facts={"source_event_id": "event-123"},
                proposed_entity_ids=(),
                basis="No confirmed designation matched",
            )
        )
        batch_id = publisher.publish_next_batch()
        assert batch_id is not None
        result = import_candidate_batch(
            storage,
            registry,
            prefix="entity-registry/v1",
            installation_id=installation_id,
            batch_id=batch_id,
        )
        assert result.acknowledged
        assert publisher.collect_acknowledgements() == 1
        outbox = session.scalar(select(RegistryCandidateOutbox))
        assert outbox is not None and outbox.status == "acknowledged"

    candidate = ReviewQueueService(registry).list_candidates(source="sports-feed")
    assert len(candidate) == 1
    assert candidate[0].origin == f"server:{installation_id}"
    with registry._connect(write=False) as connection:
        row = connection.execute(
            "SELECT idempotency_key FROM review_candidates WHERE id=?", (candidate[0].id,)
        ).fetchone()
    assert row is not None and row[0] == "event-1"
    engine.dispose()


def test_new_batch_occurrence_updates_seen_count_but_same_batch_retry_does_not(
    tmp_path: Path,
) -> None:
    installation_id = str(uuid4())
    storage = MemoryFeedbackStorage()
    first_id, second_id = _batch_id(1), _batch_id(2)
    first_row = _observation(installation_id, "stable-idempotency")
    second_row = {**first_row, "observed_at": "2026-10-05T12:00:00Z"}
    _batch(storage, installation_id, first_id, [first_row])
    _batch(storage, installation_id, second_id, [second_row])
    registry = EntityRegistry(tmp_path / "registry.sqlite3")
    registry.initialize()

    result = import_pending_candidate_batches(
        storage,
        registry,
        prefix="entity-registry/v1",
        installation_id=installation_id,
        max_batches=10,
    )
    candidates = ReviewQueueService(registry).list_candidates(source="sports-feed")
    assert result.scanned_batches == 2
    assert result.imported_candidates == 2
    assert len(candidates) == 1
    assert candidates[0].observation_count == 2
    assert candidates[0].observed_at == "2026-10-05T12:00:00.000000Z"
    first_seen = candidates[0].first_seen_at
    last_seen = candidates[0].last_seen_at

    ack_key = f"entity-registry/v1/candidate-acks/{installation_id}/{second_id}.json"
    del storage.objects[ack_key]
    replay = import_candidate_batch(
        storage,
        registry,
        prefix="entity-registry/v1",
        installation_id=installation_id,
        batch_id=second_id,
    )
    assert replay.imported_candidates == 0
    refreshed = ReviewQueueService(registry).list_candidates(source="sports-feed")[0]
    assert refreshed.observation_count == 2
    assert refreshed.first_seen_at == first_seen
    assert refreshed.last_seen_at == last_seen


def test_feedback_import_transaction_rolls_back_rows_and_ledger_on_write_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installation_id, batch_id = str(uuid4()), _batch_id(1)
    storage = MemoryFeedbackStorage()
    _batch(
        storage,
        installation_id,
        batch_id,
        [_observation(installation_id, "one"), _observation(installation_id, "two")],
    )
    registry = EntityRegistry(tmp_path / "registry.sqlite3")
    registry.initialize()
    original = ReviewQueueService._observe_connection
    calls = 0

    def fail_after_one(self, connection, observation):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("injected local commit failure")
        return original(self, connection, observation)

    monkeypatch.setattr(ReviewQueueService, "_observe_connection", fail_after_one)
    with pytest.raises(RuntimeError, match="injected"):
        import_candidate_batch(
            storage,
            registry,
            prefix="entity-registry/v1",
            installation_id=installation_id,
            batch_id=batch_id,
        )
    assert ReviewQueueService(registry).list_candidates(source="sports-feed") == []
    assert not any("candidate-acks" in key for key in storage.objects)
    with registry._connect(write=False) as connection:
        assert (
            connection.execute("SELECT count(*) FROM candidate_feedback_import_batches").fetchone()[
                0
            ]
            == 0
        )
