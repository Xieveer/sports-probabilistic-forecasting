"""Проверка и идемпотентный импорт server candidate batches в локальную очередь."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from sports_forecast.identity.publication import ConditionalWriteConflictError, StorageObject
from sports_forecast.identity.registry import EntityRegistry
from sports_forecast.identity.review_service import CandidateObservation, ReviewQueueService


_MAX_BATCH_BYTES = 1024 * 1024
_MAX_BATCH_ROWS = 100
_OBSERVATION_FIELDS = frozenset(
    {
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
)


class CandidateFeedbackError(RuntimeError):
    """Candidate batch или ack не соответствует безопасному контракту."""


class CandidateFeedbackStorage(Protocol):
    """Ограниченный Object Storage API для кандидатов и ack."""

    def list_keys(
        self,
        prefix: str,
        *,
        continuation_token: str | None = None,
        start_after: str | None = None,
        max_keys: int = 1000,
    ) -> tuple[tuple[str, ...], str | None]: ...

    def get(self, key: str, *, max_bytes: int | None = None) -> StorageObject: ...

    def put(self, key: str, body: bytes, *, if_none_match: bool = False) -> str: ...


@dataclass(frozen=True)
class CandidateImportResult:
    """Результат одной попытки локального импорта/подтверждения доставки."""

    installation_id: str
    batch_id: str
    imported_candidates: int
    acknowledged: bool
    acknowledgement_created: bool


@dataclass(frozen=True)
class CandidateImportSummary:
    """Счётчики пакетной проверки Object Storage."""

    scanned_batches: int
    imported_candidates: int
    acknowledged_batches: int


def _canonical_json(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        + b"\n"
    )


def _validate_uuid(value: str, field: str) -> None:
    try:
        canonical = str(UUID(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise CandidateFeedbackError(f"Некорректный {field}") from exc
    if canonical != value:
        raise CandidateFeedbackError(f"Неканонический {field}")


def _normalize_prefix(prefix: str) -> str:
    parts = prefix.strip("/").split("/")
    if not parts or any(not part or part in {".", ".."} for part in parts):
        raise CandidateFeedbackError("Некорректный Object Storage prefix")
    return "/".join(parts)


def _batch_sequence(batch_id: str) -> int:
    parts = batch_id.split("-", 1)
    if len(parts) != 2 or len(parts[0]) != 20 or not parts[0].isdigit():
        raise CandidateFeedbackError("batch_id не содержит 20-значный sequence")
    sequence = int(parts[0])
    if sequence < 1 or str(sequence).zfill(20) != parts[0]:
        raise CandidateFeedbackError("Candidate batch sequence некорректен")
    _validate_uuid(parts[1], "batch UUID")
    return sequence


def _batch_key(prefix: str, installation_id: str, batch_id: str) -> str:
    return f"{prefix}/candidates/{installation_id}/{batch_id}.jsonl"


def _ack_key(prefix: str, installation_id: str, batch_id: str) -> str:
    return f"{prefix}/candidate-acks/{installation_id}/{batch_id}.json"


def _validate_ack(body: bytes, installation_id: str, batch_id: str) -> None:
    try:
        value = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CandidateFeedbackError("Candidate ack повреждён") from exc
    if (
        not isinstance(value, dict)
        or set(value) != {"schema_version", "installation_id", "batch_id", "received_at"}
        or value.get("schema_version") != 1
        or isinstance(value.get("schema_version"), bool)
        or value.get("installation_id") != installation_id
        or value.get("batch_id") != batch_id
        or body != _canonical_json(value)
    ):
        raise CandidateFeedbackError("Candidate ack имеет неверную форму или identity")
    timestamp = value.get("received_at")
    if not isinstance(timestamp, str):
        raise CandidateFeedbackError("Candidate ack не содержит received_at")
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CandidateFeedbackError("Candidate ack содержит неверный received_at") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CandidateFeedbackError("Candidate ack timestamp должен содержать timezone")


def _parse_batch(body: bytes, installation_id: str) -> tuple[CandidateObservation, ...]:
    if not body or len(body) > _MAX_BATCH_BYTES:
        raise CandidateFeedbackError("Candidate batch пуст или превышает 1 MiB")
    if not body.endswith(b"\n"):
        raise CandidateFeedbackError("Candidate JSONL должен завершаться LF")
    lines = body.splitlines(keepends=True)
    if len(lines) > _MAX_BATCH_ROWS:
        raise CandidateFeedbackError("Candidate batch превышает 100 записей")
    parsed: list[CandidateObservation] = []
    idempotency_keys: set[str] = set()
    expected_origin = f"server:{installation_id}"
    for line in lines:
        try:
            value = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CandidateFeedbackError("Candidate JSONL содержит повреждённую строку") from exc
        if (
            not isinstance(value, dict)
            or set(value) != _OBSERVATION_FIELDS
            or line != _canonical_json(value)
        ):
            raise CandidateFeedbackError("Candidate row не соответствует canonical schema")
        if value.get("origin") != expected_origin:
            raise CandidateFeedbackError("Candidate origin не соответствует installation")
        key = value.get("idempotency_key")
        if not isinstance(key, str) or key in idempotency_keys:
            raise CandidateFeedbackError("Candidate batch содержит повторный idempotency key")
        idempotency_keys.add(key)
        if not isinstance(value.get("scope"), dict):
            raise CandidateFeedbackError("Candidate scope должен быть объектом")
        if not isinstance(value.get("facts"), dict):
            raise CandidateFeedbackError("Candidate facts должны быть объектом")
        if not isinstance(value.get("proposed_entity_ids"), list):
            raise CandidateFeedbackError("Candidate proposed_entity_ids должен быть массивом")
        observation = CandidateObservation(
            source=value["source"],
            kind=value["kind"],
            scope=value["scope"],
            value_kind=value["value_kind"],
            raw_value=value["raw_value"],
            origin=value["origin"],
            idempotency_key=value["idempotency_key"],
            observed_at=value["observed_at"],
            facts=value["facts"],
            proposed_entity_ids=tuple(value["proposed_entity_ids"]),
            basis=value["basis"],
        )
        try:
            ReviewQueueService.validate_observation(observation)
        except (TypeError, ValueError) as exc:
            raise CandidateFeedbackError(
                "Candidate row не прошёл проверку локальной очереди"
            ) from exc
        parsed.append(observation)
    if not parsed:
        raise CandidateFeedbackError("Candidate batch не содержит записей")
    return tuple(parsed)


def _acknowledge(
    storage: CandidateFeedbackStorage,
    *,
    key: str,
    installation_id: str,
    batch_id: str,
) -> bool:
    try:
        existing = storage.get(key, max_bytes=16_384)
    except FileNotFoundError:
        existing = None
    if existing is not None:
        _validate_ack(existing.body, installation_id, batch_id)
        return False
    body = _canonical_json(
        {
            "schema_version": 1,
            "installation_id": installation_id,
            "batch_id": batch_id,
            "received_at": datetime.now(UTC)
            .isoformat(timespec="microseconds")
            .replace("+00:00", "Z"),
        }
    )
    try:
        storage.put(key, body, if_none_match=True)
        stored = storage.get(key, max_bytes=16_384)
        if stored.body != body:
            raise CandidateFeedbackError("Candidate ack bytes после PUT отличаются")
        _validate_ack(stored.body, installation_id, batch_id)
        return True
    except ConditionalWriteConflictError:
        existing = storage.get(key, max_bytes=16_384)
        _validate_ack(existing.body, installation_id, batch_id)
        return False


def _advance_cursor_after_ack(
    registry: EntityRegistry, installation_id: str, *, expected: int, sequence: int
) -> None:
    try:
        registry.advance_candidate_feedback_cursor(
            installation_id, expected_sequence=expected, new_sequence=sequence
        )
    except ValueError:
        # Параллельный importer мог подтвердить тот же batch после нашего read.
        if registry.candidate_feedback_cursor(installation_id) < sequence:
            raise


def import_candidate_batch(
    storage: CandidateFeedbackStorage,
    registry: EntityRegistry,
    *,
    prefix: str,
    installation_id: str,
    batch_id: str,
) -> CandidateImportResult:
    """Импортировать весь batch до публикации подтверждения локальной доставки."""
    _validate_uuid(installation_id, "installation_id")
    sequence = _batch_sequence(batch_id)
    root = _normalize_prefix(prefix)
    candidate_key = _batch_key(root, installation_id, batch_id)
    ack_key = _ack_key(root, installation_id, batch_id)
    cursor = registry.candidate_feedback_cursor(installation_id)
    if sequence > cursor + 1:
        raise CandidateFeedbackError("Candidate batch sequence содержит пропуск")
    try:
        stored = storage.get(candidate_key, max_bytes=_MAX_BATCH_BYTES)
    except FileNotFoundError as exc:
        raise CandidateFeedbackError("Candidate batch отсутствует в Object Storage") from exc
    observations = _parse_batch(stored.body, installation_id)
    queue = ReviewQueueService(registry)
    batch_sequence = _batch_sequence(batch_id)
    imported = queue.observe_batch(
        observations,
        installation_id=installation_id,
        batch_sequence=batch_sequence,
        batch_id=batch_id,
        body_sha256=hashlib.sha256(stored.body).hexdigest(),
    )
    created = _acknowledge(
        storage,
        key=ack_key,
        installation_id=installation_id,
        batch_id=batch_id,
    )
    if sequence == cursor + 1:
        _advance_cursor_after_ack(registry, installation_id, expected=cursor, sequence=sequence)
    return CandidateImportResult(
        installation_id=installation_id,
        batch_id=batch_id,
        imported_candidates=len(imported),
        acknowledged=True,
        acknowledgement_created=created,
    )


def import_pending_candidate_batches(
    storage: CandidateFeedbackStorage,
    registry: EntityRegistry,
    *,
    prefix: str,
    installation_id: str,
    max_batches: int = 100,
) -> CandidateImportSummary:
    """Импортировать ограниченное число доступных candidate batches."""
    if not 1 <= max_batches <= 10_000:
        raise ValueError("max_batches должен быть в диапазоне 1..10000")
    _validate_uuid(installation_id, "installation_id")
    root = _normalize_prefix(prefix)
    list_prefix = f"{root}/candidates/{installation_id}/"
    cursor = registry.candidate_feedback_cursor(installation_id)
    start_after = f"{list_prefix}{cursor:020d}-g"
    continuation: str | None = None
    scanned = imported = acknowledged = 0
    while scanned < max_batches:
        page, continuation = storage.list_keys(
            list_prefix,
            continuation_token=continuation,
            start_after=start_after if continuation is None else None,
            max_keys=min(1000, max_batches - scanned),
        )
        if not page:
            break
        for key in page:
            if not key.startswith(list_prefix) or not key.endswith(".jsonl"):
                continue
            batch_id = key[len(list_prefix) : -len(".jsonl")]
            sequence = _batch_sequence(batch_id)
            if sequence <= cursor:
                continue
            if sequence != cursor + 1:
                raise CandidateFeedbackError("Candidate batch sequence содержит пропуск")
            result = import_candidate_batch(
                storage,
                registry,
                prefix=root,
                installation_id=installation_id,
                batch_id=batch_id,
            )
            if not result.acknowledged:
                raise CandidateFeedbackError("Candidate batch не получил ack")
            cursor = sequence
            scanned += 1
            imported += result.imported_candidates
            acknowledged += 1
            if scanned >= max_batches:
                break
        if continuation is None:
            break
    return CandidateImportSummary(scanned, imported, acknowledged)
