"""Проверки переносимого полного снимка локального registry."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from sports_forecast.identity import EntityRegistry
from sports_forecast.identity.events import CanonicalEventRef
from sports_forecast.identity.review_service import (
    CandidateDecision,
    CandidateObservation,
    ReviewQueueService,
)
from sports_forecast.identity.snapshot import (
    RegistrySnapshotReader,
    export_registry_snapshot,
    install_registry_snapshot,
    verify_registry_snapshot,
)


def _registry(path: Path) -> EntityRegistry:
    registry = EntityRegistry(path)
    registry.initialize()
    tournament = registry.create_entity("tournament", "North league", sport="ice_hockey")
    home = registry.create_entity("team", "North", sport="ice_hockey")
    away = registry.create_entity("team", "South", sport="ice_hockey")
    event = registry.create_entity("event", "North v South", sport="ice_hockey")
    player = registry.create_entity("player", "Sample player", sport="ice_hockey")
    registry.add_membership(
        player.id,
        away.id,
        "roster",
        "2026-01-01T00:00:00Z",
        None,
    )
    scope = {"sport": "ice_hockey", "tournament": tournament.id}
    registry.add_designation(
        entity_id=tournament.id,
        source="fixture-feed",
        kind="tournament",
        scope={"sport": "ice_hockey"},
        value_kind="name",
        raw_value="League",
        state="confirmed",
    )
    for entity, raw, kind, value_kind in (
        (home, "NTH", "team", "external_id"),
        (away, "STH", "team", "external_id"),
        (event, "fixture-101", "event", "external_id"),
    ):
        registry.add_designation(
            entity_id=entity.id,
            source="fixture-feed",
            kind=kind,
            scope=scope,
            value_kind=value_kind,
            raw_value=raw,
            state="confirmed",
        )
    registry.set_event_relation(
        event.id,
        tournament_id=tournament.id,
        home_team_id=home.id,
        away_team_id=away.id,
        scheduled_at="2026-10-04T17:00:00Z",
        actor="owner",
        reason="Фикстура локального снимка",
    )
    return registry


def test_snapshot_export_is_content_deterministic_and_contains_full_records(
    tmp_path: Path,
) -> None:
    registry = _registry(tmp_path / "master.sqlite3")

    first = export_registry_snapshot(registry, tmp_path / "snapshots")
    second = export_registry_snapshot(registry, tmp_path / "snapshots")
    verified = verify_registry_snapshot(first.path)

    assert first.snapshot_id.startswith("ir1:")
    assert first.snapshot_id == second.snapshot_id == verified.snapshot_id
    assert set(verified.manifest["files"]) == {
        "entities.jsonl",
        "designations.jsonl",
        "decisions.jsonl",
        "events.jsonl",
        "memberships.jsonl",
    }
    assert all(
        entry["sha256"] and entry["bytes"] > 0 and entry["count"] >= 0
        for entry in verified.manifest["files"].values()
    )
    event_records = [
        json.loads(line)
        for line in (verified.path / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    expected_event_id = registry.list_entities(kind="event")[0].id
    assert any(record["event_id"] == expected_event_id for record in event_records)
    decision_records = [
        json.loads(line)
        for line in (verified.path / "decisions.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert any(record["record_type"] == "event_relation_audit" for record in decision_records)
    event_entity = registry.list_entities(kind="event")[0]
    registry.rename_entity(
        event_entity.id,
        "Changed after export",
        actor="owner",
        reason="Изменение аудита меняет состояние snapshot",
    )
    changed = export_registry_snapshot(registry, tmp_path / "snapshots")
    assert changed.snapshot_id != first.snapshot_id


def test_snapshot_reader_is_pinned_after_master_changes(tmp_path: Path) -> None:
    registry = _registry(tmp_path / "master.sqlite3")
    snapshot = export_registry_snapshot(registry, tmp_path / "snapshots")
    reader = RegistrySnapshotReader(verify_registry_snapshot(snapshot.path))
    event = next(entity for entity in registry.list_entities(kind="event"))
    tournament = next(entity for entity in registry.list_entities(kind="tournament"))
    reference = CanonicalEventRef(
        canonical_event_id=1,
        sport="ice_hockey",
        tournament="League",
        source="fixture-feed",
        source_event_id="not-in-registry",
        scheduled_at=datetime(2026, 10, 4, 17, tzinfo=UTC),
        home_participant="NTH",
        away_participant="STH",
    )
    assert reader.resolve_event(reference).project_event_id == event.id

    registry.rename_entity(event.id, "Renamed after pin", actor="owner", reason="Изменилось имя")
    home_designation = registry.find_designation(
        "fixture-feed",
        "team",
        {"sport": "ice_hockey", "tournament": tournament.id},
        "external_id",
        "NTH",
    )
    registry.decide_designation(
        home_designation.id,
        action="reject",
        entity_id=None,
        actor="owner",
        reason="Изменение после фиксации snapshot",
        expected_revision=home_designation.revision,
    )

    assert reader.snapshot_id == snapshot.snapshot_id
    assert reader.get_entity(event.id).project_name == "North v South"
    assert reader.resolve_event(reference).project_event_id == event.id
    changed = export_registry_snapshot(registry, tmp_path / "snapshots")
    changed_reader = RegistrySnapshotReader(verify_registry_snapshot(changed.path))
    assert changed.snapshot_id != snapshot.snapshot_id
    assert changed_reader.resolve_event(reference).project_event_id is None


def test_selected_snapshot_switch_is_verified_and_failed_install_preserves_current(
    tmp_path: Path,
) -> None:
    registry = _registry(tmp_path / "master.sqlite3")
    first = export_registry_snapshot(registry, tmp_path / "snapshots")
    selected = tmp_path / "data" / "registry" / "current" / "package"
    installed = install_registry_snapshot(first.path, selected)
    assert installed.snapshot_id == first.snapshot_id

    event = registry.list_entities(kind="event")[0]
    registry.rename_entity(event.id, "Changed event", actor="owner", reason="New revision")
    second = export_registry_snapshot(registry, tmp_path / "snapshots")
    selected_again = install_registry_snapshot(second.path, selected)
    assert selected_again.snapshot_id == second.snapshot_id
    assert first.path.is_dir()

    corrupt_package = tmp_path / "corrupt"
    import shutil

    shutil.copytree(first.path, corrupt_package)
    (corrupt_package / "entities.jsonl").write_bytes(b"tampered\n")
    with pytest.raises(ValueError):
        install_registry_snapshot(corrupt_package, selected)
    assert verify_registry_snapshot(selected).snapshot_id == second.snapshot_id


def test_offline_reader_resolves_confirmed_designation_at_event_time(tmp_path: Path) -> None:
    registry = _registry(tmp_path / "master.sqlite3")
    tournament = next(entity for entity in registry.list_entities(kind="tournament"))
    team = next(entity for entity in registry.list_entities(kind="team"))
    registry.add_designation(
        entity_id=team.id,
        source="fixture-feed",
        kind="team",
        scope={"sport": "ice_hockey", "tournament": tournament.id},
        value_kind="external_id",
        raw_value="OLD-ALIAS",
        state="confirmed",
        valid_from="2020-01-01T00:00:00Z",
        valid_until="2022-01-01T00:00:00Z",
    )
    snapshot = export_registry_snapshot(registry, tmp_path / "snapshots")
    reader = RegistrySnapshotReader(verify_registry_snapshot(snapshot.path))

    assert (
        reader.resolve_designation(
            source="fixture-feed",
            kind="team",
            scope={"sport": "ice_hockey", "tournament": tournament.id},
            value_kind="external_id",
            raw_value="OLD-ALIAS",
            at="2021-04-01T00:00:00Z",
        ).entity_id
        == team.id
    )
    assert (
        reader.resolve_designation(
            source="fixture-feed",
            kind="team",
            scope={"sport": "ice_hockey", "tournament": tournament.id},
            value_kind="external_id",
            raw_value="OLD-ALIAS",
            at="2023-04-01T00:00:00Z",
        ).entity_id
        is None
    )


@pytest.mark.parametrize("tamper", ["truncate", "mutate", "missing", "extra"])
def test_snapshot_verifier_rejects_incomplete_or_changed_files(tmp_path: Path, tamper: str) -> None:
    registry = _registry(tmp_path / "master.sqlite3")
    snapshot = export_registry_snapshot(registry, tmp_path / "snapshots")
    target = snapshot.path / "entities.jsonl"
    if tamper == "truncate":
        target.write_bytes(target.read_bytes()[:-1])
    elif tamper == "mutate":
        target.write_bytes(target.read_bytes() + b"{}\n")
    elif tamper == "missing":
        target.unlink()
    else:
        (snapshot.path / "unexpected.jsonl").write_text("{}\n", encoding="utf-8")

    with pytest.raises(ValueError):
        verify_registry_snapshot(snapshot.path)


def test_snapshot_exports_finalized_candidate_evidence_but_not_pending_queue(
    tmp_path: Path,
) -> None:
    registry = _registry(tmp_path / "master.sqlite3")
    team = registry.create_entity("team", "Evidence team", sport="ice_hockey")
    queue = ReviewQueueService(registry)
    accepted = queue.observe(
        CandidateObservation(
            source="fixture-feed",
            kind="team",
            scope={"sport": "ice_hockey"},
            value_kind="external_id",
            raw_value="EVIDENCE-1",
            origin="local:history",
            idempotency_key="accepted-1",
            observed_at="2026-10-04T12:00:00Z",
            facts={"team": "Evidence team"},
            proposed_entity_ids=(team.id,),
            basis="Confirmed source key and schedule",
        )
    )
    queue.decide_batch(
        [
            CandidateDecision(
                candidate_id=accepted.id,
                expected_revision=accepted.revision,
                expected_designation_revision=accepted.designation_revision,
                action="confirm",
                entity_id=team.id,
                reason="Owner verified evidence",
            )
        ],
        actor="owner",
    )
    initially_finalized = export_registry_snapshot(registry, tmp_path / "snapshots")
    reopened = queue.observe(
        CandidateObservation(
            source="fixture-feed",
            kind="team",
            scope={"sport": "ice_hockey"},
            value_kind="external_id",
            raw_value="EVIDENCE-1",
            origin="local:history",
            idempotency_key="accepted-1",
            observed_at="2026-10-04T13:00:00Z",
            facts={"team": "Revised unreviewed evidence"},
            proposed_entity_ids=(team.id,),
            basis="New unreviewed revision",
        )
    )
    reopened_snapshot = export_registry_snapshot(registry, tmp_path / "snapshots")
    assert reopened_snapshot.snapshot_id == initially_finalized.snapshot_id
    queue.decide_batch(
        [
            CandidateDecision(
                candidate_id=reopened.id,
                expected_revision=reopened.revision,
                expected_designation_revision=reopened.designation_revision,
                action="reject",
                reason="Новые сведения не подтвердили alias",
            )
        ],
        actor="owner",
    )[0]
    rejected_snapshot = export_registry_snapshot(registry, tmp_path / "snapshots")
    assert rejected_snapshot.snapshot_id != reopened_snapshot.snapshot_id
    reopened_again = queue.observe(
        CandidateObservation(
            source="fixture-feed",
            kind="team",
            scope={"sport": "ice_hockey"},
            value_kind="external_id",
            raw_value="EVIDENCE-1",
            origin="local:history",
            idempotency_key="accepted-1",
            observed_at="2026-10-04T14:00:00Z",
            facts={"team": "Evidence team final"},
            proposed_entity_ids=(team.id,),
            basis="Second owner review",
        )
    )
    pending_again_snapshot = export_registry_snapshot(registry, tmp_path / "snapshots")
    assert pending_again_snapshot.snapshot_id == rejected_snapshot.snapshot_id
    queue.decide_batch(
        [
            CandidateDecision(
                candidate_id=reopened_again.id,
                expected_revision=reopened_again.revision,
                expected_designation_revision=reopened_again.designation_revision,
                action="confirm",
                entity_id=team.id,
                reason="Owner reconfirmed after correction",
            )
        ],
        actor="owner",
    )
    reconfirmed_snapshot = export_registry_snapshot(registry, tmp_path / "snapshots")
    assert reconfirmed_snapshot.snapshot_id != rejected_snapshot.snapshot_id
    queue.observe(
        CandidateObservation(
            source="fixture-feed",
            kind="team",
            scope={"sport": "ice_hockey"},
            value_kind="external_id",
            raw_value="PENDING-ONLY",
            origin="local:history",
            idempotency_key="pending-1",
            observed_at="2026-10-04T13:00:00Z",
            facts={"team": "Pending team"},
            basis="Not yet reviewed",
        )
    )

    artifact = export_registry_snapshot(registry, tmp_path / "snapshots")
    assert artifact.snapshot_id == reconfirmed_snapshot.snapshot_id
    snapshot = verify_registry_snapshot(artifact.path)
    evidence = [
        item
        for item in snapshot.records["decisions.jsonl"]
        if item.get("record_type") == "candidate_evidence"
    ]

    assert len(evidence) == 3
    by_revision = {item["revision"]: item for item in evidence}
    assert by_revision[1]["status"] == "confirmed"
    assert by_revision[1]["facts"] == {"team": "Evidence team"}
    assert by_revision[1]["basis"] == "Confirmed source key and schedule"
    assert by_revision[2]["status"] == "rejected"
    assert by_revision[2]["facts"] == {"team": "Revised unreviewed evidence"}
    decisions = [
        item for item in snapshot.records["decisions.jsonl"] if item["record_type"] == "decisions"
    ]
    linked = [item for item in decisions if item.get("evidence_candidate_id") == accepted.id]
    assert sorted(item["evidence_revision"] for item in linked) == [1, 2, 3]
    for decision in linked:
        evidence_item = by_revision[decision["evidence_revision"]]
        assert decision["id"] in evidence_item["decision_ids"]
    pending_only_snapshot = export_registry_snapshot(registry, tmp_path / "snapshots")
    assert pending_only_snapshot.snapshot_id == reconfirmed_snapshot.snapshot_id


def test_snapshot_preserves_maximum_length_confirmed_candidate_fact(tmp_path: Path) -> None:
    registry = _registry(tmp_path / "master.sqlite3")
    queue = ReviewQueueService(registry)
    team = registry.list_entities(kind="team")[0]
    candidate = queue.observe(
        CandidateObservation(
            source="fixture-feed",
            kind="team",
            scope={"sport": "ice_hockey"},
            value_kind="external_id",
            raw_value="LONG-FACT",
            origin="local:history",
            idempotency_key="long-fact-1",
            observed_at="2026-10-04T13:00:00Z",
            facts={"description": "x" * 1000},
            proposed_entity_ids=(team.id,),
            basis="Проверка граничной длины факта",
        )
    )
    queue.decide_batch(
        [
            CandidateDecision(
                candidate_id=candidate.id,
                expected_revision=candidate.revision,
                expected_designation_revision=candidate.designation_revision,
                action="confirm",
                entity_id=team.id,
                reason="Подтверждён допустимый факт максимальной длины",
            )
        ],
        actor="owner",
    )

    artifact = export_registry_snapshot(registry, tmp_path / "snapshots")
    verified = verify_registry_snapshot(artifact.path)
    evidence = next(
        item
        for item in verified.records["decisions.jsonl"]
        if item.get("record_type") == "candidate_evidence"
    )
    assert len(evidence["facts"]["description"]) == 1000


def test_snapshot_preserves_rejected_invalid_proposed_entity_id_as_evidence(
    tmp_path: Path,
) -> None:
    registry = _registry(tmp_path / "master.sqlite3")
    queue = ReviewQueueService(registry)
    candidate = queue.observe(
        CandidateObservation(
            source="fixture-feed",
            kind="team",
            scope={"sport": "ice_hockey"},
            value_kind="external_id",
            raw_value="BAD-PROPOSAL",
            origin="local:history",
            idempotency_key="bad-proposal-1",
            observed_at="2026-10-04T13:00:00Z",
            facts={"provider_name": "Unknown proposal"},
            proposed_entity_ids=("invalid-or-not-yet-created",),
            basis="Предложенный ID был отвергнут владельцем",
        )
    )
    queue.decide_batch(
        [
            CandidateDecision(
                candidate_id=candidate.id,
                expected_revision=candidate.revision,
                expected_designation_revision=candidate.designation_revision,
                action="reject",
                reason="Предложенная сущность не существует",
            )
        ],
        actor="owner",
    )

    artifact = export_registry_snapshot(registry, tmp_path / "snapshots")
    verified = verify_registry_snapshot(artifact.path)
    evidence = next(
        item
        for item in verified.records["decisions.jsonl"]
        if item.get("record_type") == "candidate_evidence"
    )
    assert evidence["status"] == "rejected"
    assert evidence["proposed_entity_ids"] == ["invalid-or-not-yet-created"]


def test_snapshot_verifier_rejects_decision_link_to_unrelated_evidence(tmp_path: Path) -> None:
    import shutil

    registry = _registry(tmp_path / "master.sqlite3")
    team = registry.list_entities(kind="team")[0]
    queue = ReviewQueueService(registry)
    candidate = queue.observe(
        CandidateObservation(
            source="fixture-feed",
            kind="team",
            scope={"sport": "ice_hockey"},
            value_kind="external_id",
            raw_value="FORGED-EVIDENCE",
            origin="local:review",
            idempotency_key="forged-evidence",
            observed_at="2026-10-04T12:00:00Z",
            facts={"event": "evt-1"},
            proposed_entity_ids=(team.id,),
            basis="Reviewed source event",
        )
    )
    queue.decide_batch(
        [
            CandidateDecision(
                candidate_id=candidate.id,
                expected_revision=candidate.revision,
                expected_designation_revision=candidate.designation_revision,
                action="confirm",
                entity_id=team.id,
                reason="Owner confirms exact source key",
            )
        ],
        actor="owner",
    )
    package = export_registry_snapshot(registry, tmp_path / "snapshots")
    forged = tmp_path / "forged-package"
    shutil.copytree(package.path, forged)
    decisions_path = forged / "decisions.jsonl"
    decision_rows = [json.loads(line) for line in decisions_path.read_text().splitlines()]
    owner_decision = next(
        row
        for row in decision_rows
        if row.get("record_type") == "decisions"
        and row.get("evidence_candidate_id") == candidate.id
    )
    owner_decision["evidence_revision"] = 99
    encoded_decisions = b"".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode() + b"\n"
        for row in decision_rows
    )
    decisions_path.write_bytes(encoded_decisions)
    manifest_path = forged / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.pop("snapshot_id")
    manifest["files"]["decisions.jsonl"] = {
        "sha256": hashlib.sha256(encoded_decisions).hexdigest(),
        "bytes": len(encoded_decisions),
        "count": len(decision_rows),
    }
    digest = hashlib.sha256(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    manifest["snapshot_id"] = f"ir1:{digest}"
    manifest_path.write_bytes(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        + b"\n"
    )

    with pytest.raises(ValueError, match="evidence|Decision|decision"):
        verify_registry_snapshot(forged)


def test_pending_only_observation_does_not_change_resolver_snapshot_id(tmp_path: Path) -> None:
    registry = _registry(tmp_path / "master.sqlite3")
    before = export_registry_snapshot(registry, tmp_path / "snapshots")
    ReviewQueueService(registry).observe(
        CandidateObservation(
            source="fixture-feed",
            kind="team",
            scope={"sport": "ice_hockey"},
            value_kind="external_id",
            raw_value="NOT-IN-SNAPSHOT",
            origin="local:history",
            idempotency_key="irrelevant-pending",
            observed_at="2026-10-04T15:00:00Z",
            facts={"team": "Unknown"},
            basis="Awaiting owner review",
        )
    )
    after = export_registry_snapshot(registry, tmp_path / "snapshots")

    assert after.snapshot_id == before.snapshot_id


def test_pending_conflict_that_changes_resolver_remains_in_snapshot(tmp_path: Path) -> None:
    registry = _registry(tmp_path / "master.sqlite3")
    before = export_registry_snapshot(registry, tmp_path / "snapshots")
    tournament = registry.list_entities(kind="tournament")[0]
    other_team = registry.create_entity("team", "Other North", sport="ice_hockey")
    ReviewQueueService(registry).observe(
        CandidateObservation(
            source="fixture-feed",
            kind="team",
            scope={"sport": "ice_hockey", "tournament": tournament.id},
            value_kind="external_id",
            raw_value="NTH",
            origin="local:history",
            idempotency_key="conflicting-pending",
            observed_at="2026-10-04T16:00:00Z",
            facts={"team": "Other North"},
            proposed_entity_ids=(other_team.id,),
            basis="Possible alias conflict",
        )
    )

    after = export_registry_snapshot(registry, tmp_path / "snapshots")
    reader = RegistrySnapshotReader(verify_registry_snapshot(after.path))
    result = reader.resolve_designation(
        source="fixture-feed",
        kind="team",
        scope={"sport": "ice_hockey", "tournament": tournament.id},
        value_kind="external_id",
        raw_value="NTH",
        at="2026-10-04T16:00:00Z",
    )

    assert after.snapshot_id != before.snapshot_id
    assert result.status == "conflict"
