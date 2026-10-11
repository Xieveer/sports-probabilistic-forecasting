"""Проверки словаря правил рынков и его обратной совместимости."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from sports_forecast.identity import EntityRegistry
from sports_forecast.identity.installation import (
    VerifiedPublicationRecord,
    install_registry_publication,
)
from sports_forecast.identity.nhl_market_seed import seed_nhl_pinnacle_market
from sports_forecast.identity.registry import DesignationState
from sports_forecast.identity.review_app import create_review_app
from sports_forecast.identity.review_service import ReviewQueueService
from sports_forecast.identity.snapshot import (
    RegistrySnapshotReader,
    export_registry_snapshot,
    verify_registry_snapshot,
)
from sports_forecast.service.db.models import Base, RegistryInstallationLock


def test_market_rule_is_scoped_audited_and_resolvable(tmp_path: Path) -> None:
    registry = EntityRegistry(tmp_path / "master.sqlite3")
    registry.initialize()
    tournament = registry.create_entity("tournament", "NHL", sport="ice_hockey")
    seed_nhl_pinnacle_market(registry, tournament_id=tournament.id)

    reader_snapshot = export_registry_snapshot(registry, tmp_path / "snapshots")
    reader = RegistrySnapshotReader(verify_registry_snapshot(reader_snapshot.path))
    market = reader.resolve_market(
        source="the_odds_api",
        sport="ice_hockey",
        tournament_id=tournament.id,
        bookmaker="pinnacle",
        raw_market_key="h2h",
    )
    assert market.status == "resolved"
    assert market.entity_id is not None
    rule = reader.get_market_rule(market.entity_id)
    assert (rule.period, rule.overtime, rule.shootout, rule.draw) == ("game", True, True, False)
    assert len(rule.valid_outcome_ids) == 2
    assert set(rule.valid_outcome_keys) == {"home_win", "away_win"}
    assert (
        reader.resolve_market(
            source="the_odds_api",
            sport="ice_hockey",
            tournament_id=tournament.id,
            bookmaker="other_bookmaker",
            raw_market_key="h2h",
        ).status
        == "unresolved"
    )
    assert seed_nhl_pinnacle_market(registry, tournament_id=tournament.id) == market.entity_id
    assert len(registry.list_market_rule_audit(market.entity_id)) == 1


def test_seed_does_not_apply_rule_to_owner_remapped_market(tmp_path: Path) -> None:
    registry = EntityRegistry(tmp_path / "master.sqlite3")
    registry.initialize()
    tournament = registry.create_entity("tournament", "NHL", sport="ice_hockey")
    owner_market = registry.create_entity("market", "Owner market", sport="ice_hockey")
    registry.add_designation(
        entity_id=owner_market.id,
        source="the_odds_api",
        kind="market",
        scope={"sport": "ice_hockey", "tournament": tournament.id, "bookmaker": "pinnacle"},
        value_kind="name",
        raw_value="h2h",
        state="confirmed",
    )

    with pytest.raises(ValueError, match="owner mapping"):
        seed_nhl_pinnacle_market(registry, tournament_id=tournament.id)
    with pytest.raises(KeyError):
        registry.get_market_rule(owner_market.id)


@pytest.mark.parametrize("state", ["pending", "rejected", "superseded", "conflict"])
def test_seed_requires_effective_confirmed_alias(tmp_path: Path, state: DesignationState) -> None:
    registry = EntityRegistry(tmp_path / f"{state}.sqlite3")
    registry.initialize()
    tournament = registry.create_entity("tournament", "NHL", sport="ice_hockey")
    unrelated = registry.create_entity("market", "Unrelated", sport="ice_hockey")
    with registry._connect() as connection:
        registry._insert_designation(
            connection,
            entity_id=unrelated.id,
            source="the_odds_api",
            kind="market",
            scope={"sport": "ice_hockey", "tournament": tournament.id, "bookmaker": "pinnacle"},
            value_kind="name",
            raw_value="h2h",
            state=state,
            valid_from=None,
            valid_until=None,
        )

    with pytest.raises(ValueError, match="h2h"):
        seed_nhl_pinnacle_market(registry, tournament_id=tournament.id)
    with pytest.raises(KeyError):
        registry.get_market_rule(unrelated.id)


def test_market_rule_update_has_revision_and_immutable_audit(tmp_path: Path) -> None:
    registry = EntityRegistry(tmp_path / "master.sqlite3")
    registry.initialize()
    tournament = registry.create_entity("tournament", "NHL", sport="ice_hockey")
    market_id = seed_nhl_pinnacle_market(registry, tournament_id=tournament.id)
    current = registry.get_market_rule(market_id)
    draw = registry.create_entity("outcome", "Draw", sport="ice_hockey")
    valid_ids = (*current.valid_outcome_ids, draw.id)
    valid_keys = {
        **dict(zip(current.valid_outcome_ids, current.valid_outcome_keys, strict=True)),
        draw.id: "draw",
    }

    updated = registry.set_market_rule(
        market_id,
        period="regulation",
        overtime=False,
        shootout=False,
        draw=True,
        valid_outcome_ids=valid_ids,
        valid_outcome_keys=valid_keys,
        actor="owner",
        reason="Исправлено по правилам рынка",
        expected_revision=current.revision,
    )

    assert updated.revision == current.revision + 1
    audit = registry.list_market_rule_audit(market_id)
    assert len(audit) == 2
    assert audit[-1].actor == "owner"
    assert audit[-1].reason == "Исправлено по правилам рынка"
    with pytest.raises(ValueError, match="revision"):
        registry.set_market_rule(
            market_id,
            period="game",
            overtime=True,
            shootout=True,
            draw=False,
            valid_outcome_ids=current.valid_outcome_ids,
            valid_outcome_keys=dict(
                zip(current.valid_outcome_ids, current.valid_outcome_keys, strict=True)
            ),
            actor="owner",
            reason="Устаревшая форма",
            expected_revision=current.revision,
        )
    swapped_keys = {
        outcome_id: {"home_win": "away_win", "away_win": "home_win"}[key]
        for outcome_id, key in zip(
            current.valid_outcome_ids, current.valid_outcome_keys, strict=True
        )
    }
    with pytest.raises(ValueError, match="semantic"):
        registry.set_market_rule(
            market_id,
            period=current.period,
            overtime=current.overtime,
            shootout=current.shootout,
            draw=current.draw,
            valid_outcome_ids=current.valid_outcome_ids,
            valid_outcome_keys=swapped_keys,
            actor="owner",
            reason="Проверка неизменности семантики",
            expected_revision=updated.revision,
        )


def test_outcome_uuid_semantic_key_is_immutable_across_markets(tmp_path: Path) -> None:
    registry = EntityRegistry(tmp_path / "master.sqlite3")
    registry.initialize()
    tournament = registry.create_entity("tournament", "NHL", sport="ice_hockey")
    first_market_id = seed_nhl_pinnacle_market(registry, tournament_id=tournament.id)
    first_rule = registry.get_market_rule(first_market_id)
    second_market = registry.create_entity("market", "Second market", sport="ice_hockey")
    swapped = {
        outcome_id: {"home_win": "away_win", "away_win": "home_win"}[key]
        for outcome_id, key in zip(
            first_rule.valid_outcome_ids, first_rule.valid_outcome_keys, strict=True
        )
    }

    with pytest.raises(ValueError, match="semantic"):
        registry.set_market_rule(
            second_market.id,
            period="game",
            overtime=True,
            shootout=True,
            draw=False,
            valid_outcome_ids=first_rule.valid_outcome_ids,
            valid_outcome_keys=swapped,
            actor="owner",
            reason="Проверка глобальной семантики UUID",
            expected_revision=0,
        )
    with pytest.raises(KeyError):
        registry.get_market_rule(second_market.id)


def test_v1_snapshot_remains_readable_and_v2_carries_market_rules(tmp_path: Path) -> None:
    registry = EntityRegistry(tmp_path / "master.sqlite3")
    registry.initialize()
    tournament = registry.create_entity("tournament", "NHL", sport="ice_hockey")
    seed_nhl_pinnacle_market(registry, tournament_id=tournament.id)
    artifact = export_registry_snapshot(registry, tmp_path / "snapshots")
    v2 = verify_registry_snapshot(artifact.path)
    assert v2.manifest["format_version"] == 2
    assert "market_rules.jsonl" in v2.manifest["files"]

    legacy_registry = EntityRegistry(tmp_path / "legacy.sqlite3")
    legacy_registry.initialize()
    legacy_registry.create_entity("tournament", "Legacy league", sport="ice_hockey")
    legacy_artifact = export_registry_snapshot(legacy_registry, tmp_path / "legacy-snapshots")
    v1_path = tmp_path / "legacy-v1"
    shutil.copytree(legacy_artifact.path, v1_path)
    (v1_path / "market_rules.jsonl").unlink()
    manifest = json.loads((v1_path / "manifest.json").read_text(encoding="utf-8"))
    manifest["format_version"] = 1
    manifest["registry_schema_version"] = 11
    manifest["files"].pop("market_rules.jsonl")
    identity = {key: value for key, value in manifest.items() if key != "snapshot_id"}
    digest = hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    manifest["snapshot_id"] = f"ir1:{digest}"
    (v1_path / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    legacy = verify_registry_snapshot(v1_path)
    assert legacy.manifest["format_version"] == 1
    assert legacy.snapshot_id != v2.snapshot_id
    legacy_reader = RegistrySnapshotReader(legacy)
    assert (
        legacy_reader.resolve_market(
            source="the_odds_api",
            sport="ice_hockey",
            tournament_id=tournament.id,
            bookmaker="pinnacle",
            raw_market_key="h2h",
        ).status
        == "unresolved"
    )


def test_schema_11_migration_preserves_entity_foreign_keys(tmp_path: Path) -> None:
    import sqlite3

    path = tmp_path / "schema-11.sqlite3"
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA foreign_keys=ON")
    connection.executescript(
        """
        CREATE TABLE entities (
            id TEXT PRIMARY KEY,kind TEXT NOT NULL,sport TEXT NOT NULL,project_name TEXT NOT NULL,
            seed_key TEXT,seed_entity_key TEXT,revision INTEGER NOT NULL DEFAULT 1,
            state TEXT NOT NULL DEFAULT 'active',created_at TEXT NOT NULL,updated_at TEXT NOT NULL,
            CHECK(kind IN ('tournament','team','event','player'))
        );
        CREATE UNIQUE INDEX seeded_entity_identity ON entities(seed_key,seed_entity_key)
            WHERE seed_key IS NOT NULL;
        CREATE TABLE designations (id TEXT PRIMARY KEY,entity_id TEXT REFERENCES entities(id));
        CREATE TABLE event_relations (
            event_id TEXT PRIMARY KEY REFERENCES entities(id),
            tournament_id TEXT NOT NULL REFERENCES entities(id),
            home_team_id TEXT NOT NULL REFERENCES entities(id),
            away_team_id TEXT NOT NULL REFERENCES entities(id),scheduled_at TEXT
        );
        CREATE TABLE related (entity_id TEXT REFERENCES entities(id));
        INSERT INTO entities VALUES ('tournament-1','tournament','ice_hockey','NHL',NULL,NULL,1,'active','a','a');
        INSERT INTO entities VALUES ('home-1','team','ice_hockey','Home',NULL,NULL,1,'active','a','a');
        INSERT INTO entities VALUES ('away-1','team','ice_hockey','Away',NULL,NULL,1,'active','a','a');
        INSERT INTO entities VALUES ('event-1','event','ice_hockey','Game',NULL,NULL,1,'active','a','a');
        INSERT INTO designations VALUES ('designation-1','home-1');
        INSERT INTO event_relations VALUES ('event-1','tournament-1','home-1','away-1','2026-10-12T17:00:00Z');
        INSERT INTO related VALUES ('tournament-1');
        PRAGMA user_version=11;
        """
    )
    connection.close()

    EntityRegistry(path).initialize()

    connection = sqlite3.connect(path)
    assert connection.execute("PRAGMA user_version").fetchone()[0] == 12
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    assert connection.execute("SELECT id,kind FROM entities").fetchone() == (
        "tournament-1",
        "tournament",
    )
    assert connection.execute("SELECT count(*) FROM entities").fetchone()[0] == 4
    assert connection.execute("SELECT count(*) FROM designations").fetchone()[0] == 1
    assert connection.execute("SELECT event_id FROM event_relations").fetchone() == ("event-1",)
    connection.execute(
        "INSERT INTO entities VALUES ('market-1','market','ice_hockey','Winner',NULL,NULL,1,'active','a','a')"
    )
    connection.commit()
    connection.close()


def test_installed_reader_loads_v1_and_v2_snapshots(tmp_path: Path) -> None:
    registry = EntityRegistry(tmp_path / "master.sqlite3")
    registry.initialize()
    tournament = registry.create_entity("tournament", "NHL", sport="ice_hockey")
    market_id = seed_nhl_pinnacle_market(registry, tournament_id=tournament.id)
    v2 = export_registry_snapshot(registry, tmp_path / "v2-packages")
    legacy_registry = EntityRegistry(tmp_path / "legacy.sqlite3")
    legacy_registry.initialize()
    legacy_registry.create_entity("tournament", "Legacy league", sport="ice_hockey")
    v2_legacy = export_registry_snapshot(legacy_registry, tmp_path / "legacy-packages")
    legacy_path = tmp_path / "v1-package"
    shutil.copytree(v2_legacy.path, legacy_path)
    (legacy_path / "market_rules.jsonl").unlink()
    manifest = json.loads((legacy_path / "manifest.json").read_text(encoding="utf-8"))
    manifest["format_version"] = 1
    manifest["registry_schema_version"] = 11
    manifest["files"].pop("market_rules.jsonl")
    identity = {key: value for key, value in manifest.items() if key != "snapshot_id"}
    legacy_digest = hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    manifest["snapshot_id"] = f"ir1:{legacy_digest}"
    (legacy_path / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    for snapshot_path, publication_sequence, want_market in (
        (v2.path, 1, True),
        (legacy_path, 1, False),
    ):
        engine = create_engine("sqlite://")
        Base.metadata.create_all(engine)
        with Session(engine) as session:
            session.add(RegistryInstallationLock(id=1, lock_version=0))
            session.commit()
            snapshot = verify_registry_snapshot(snapshot_path)
            reader = install_registry_publication(
                session,
                snapshot_path,
                publication=VerifiedPublicationRecord(
                    publication_id=str(uuid4()),
                    sequence=publication_sequence,
                    snapshot_id=snapshot.snapshot_id,
                    snapshot_sha256=snapshot.projection_sha256,
                    previous_publication_id=None,
                    published_at=datetime.now(UTC),
                    actor="owner.registry",
                ),
            )
            if want_market:
                assert reader.get_market_rule(market_id).valid_outcome_ids
            else:
                assert (
                    reader.resolve_market(
                        source="the_odds_api",
                        sport="ice_hockey",
                        tournament_id=tournament.id,
                        bookmaker="pinnacle",
                        raw_market_key="h2h",
                    ).status
                    == "unresolved"
                )
                with pytest.raises(KeyError):
                    reader.get_market_rule(market_id)
        engine.dispose()


def test_market_rule_catalog_edit_requires_current_revision_and_audits(tmp_path: Path) -> None:
    registry = EntityRegistry(tmp_path / "master.sqlite3")
    registry.initialize()
    tournament = registry.create_entity("tournament", "NHL", sport="ice_hockey")
    market_id = seed_nhl_pinnacle_market(registry, tournament_id=tournament.id)
    secret = "a-long-random-owner-secret-for-tests"
    secret_path = tmp_path / "review.secret"
    secret_path.write_text(secret, encoding="utf-8")
    secret_path.chmod(0o600)
    client = TestClient(
        create_review_app(ReviewQueueService(registry), secret_path=secret_path, actor="owner"),
        base_url="http://127.0.0.1:8765",
    )
    client.post(
        "/login",
        data={"secret": secret},
        headers={"Origin": "http://127.0.0.1:8765"},
        follow_redirects=False,
    )
    detail = client.get(f"/registry/{market_id}").text
    assert "Правила рынка" in detail
    assert "pinnacle" in detail
    csrf = re.search(r"name='csrf' value='([^']+)'", detail)
    revision = re.search(r"name='revision' value='([^']+)'", detail)
    assert csrf and revision
    rule = registry.get_market_rule(market_id)
    outcome_fields = {
        f"outcome_key_{outcome_id}": key
        for outcome_id, key in zip(rule.valid_outcome_ids, rule.valid_outcome_keys, strict=True)
    }
    updated = client.post(
        f"/registry/{market_id}/market-rule",
        data={
            "csrf": csrf.group(1),
            "revision": revision.group(1),
            "period": "game",
            "overtime": "1",
            "shootout": "1",
            "draw": "0",
            "valid_outcome_ids": list(rule.valid_outcome_ids),
            **outcome_fields,
            "reason": "Сверено с условиями рынка",
        },
        headers={"Origin": "http://127.0.0.1:8765"},
        follow_redirects=False,
    )
    assert updated.status_code == 303
    assert registry.list_market_rule_audit(market_id)[-1].reason == "Сверено с условиями рынка"
    stale = client.post(
        f"/registry/{market_id}/market-rule",
        data={
            "csrf": csrf.group(1),
            "revision": revision.group(1),
            "period": "regulation",
            "overtime": "0",
            "shootout": "0",
            "draw": "1",
            "valid_outcome_ids": list(rule.valid_outcome_ids),
            **outcome_fields,
            "reason": "Старая форма",
        },
        headers={"Origin": "http://127.0.0.1:8765"},
        follow_redirects=False,
    )
    assert stale.status_code == 409
    refreshed = client.get(f"/registry/{market_id}").text
    fresh_csrf = re.search(r"name='csrf' value='([^']+)'", refreshed)
    fresh_revision = re.search(r"name='revision' value='([^']+)'", refreshed)
    assert fresh_csrf and fresh_revision
    swapped = client.post(
        f"/registry/{market_id}/market-rule",
        data={
            "csrf": fresh_csrf.group(1),
            "revision": fresh_revision.group(1),
            "period": "game",
            "overtime": "1",
            "shootout": "1",
            "draw": "0",
            "valid_outcome_ids": list(rule.valid_outcome_ids),
            f"outcome_key_{rule.valid_outcome_ids[0]}": {
                "home_win": "away_win",
                "away_win": "home_win",
            }[rule.valid_outcome_keys[0]],
            f"outcome_key_{rule.valid_outcome_ids[1]}": {
                "home_win": "away_win",
                "away_win": "home_win",
            }[rule.valid_outcome_keys[1]],
            "reason": "Попытка заменить meaning UUID",
        },
        headers={"Origin": "http://127.0.0.1:8765"},
        follow_redirects=False,
    )
    assert swapped.status_code == 409
