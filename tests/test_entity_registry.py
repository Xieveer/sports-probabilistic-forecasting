"""Поведенческие тесты локального реестра идентичности."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest

from sports_forecast.identity import EntityRegistry, RegistryNotInitializedError
from sports_forecast.identity.nhl_seed import import_nhl_yaml


def make_registry(tmp_path: Path) -> EntityRegistry:
    registry = EntityRegistry(tmp_path / "registry.sqlite3")
    registry.initialize()
    return registry


def test_read_requires_explicit_schema_initialization(tmp_path: Path) -> None:
    registry = EntityRegistry(tmp_path / "registry.sqlite3")

    with pytest.raises(RegistryNotInitializedError):
        registry.list_entities()

    assert not (tmp_path / "registry.sqlite3").exists()


def test_designations_are_scoped_and_never_resolved_by_name_similarity(
    tmp_path: Path,
) -> None:
    registry = make_registry(tmp_path)
    tournament = registry.create_entity("tournament", "NHL", sport="ice_hockey")
    team = registry.create_entity("team", "Colorado Avalanche", sport="ice_hockey")
    nhl_scope = {"sport": "ice_hockey", "tournament": tournament.id}
    registry.add_designation(
        entity_id=team.id,
        source="nhl_api",
        kind="team",
        scope=nhl_scope,
        value_kind="external_id",
        raw_value="COL",
        state="confirmed",
    )
    registry.add_designation(
        entity_id=team.id,
        source="the_odds_api",
        kind="team",
        scope=nhl_scope,
        value_kind="name",
        raw_value="Colorado Avalanche",
        state="confirmed",
    )

    assert registry.resolve("nhl_api", "team", nhl_scope, "external_id", "COL").entity_id == team.id
    assert (
        registry.resolve("the_odds_api", "team", nhl_scope, "name", "Colorado Avalanche").entity_id
        == team.id
    )
    assert (
        registry.resolve("another_source", "team", nhl_scope, "name", "Colorado Avalanche").status
        == "unresolved"
    )

    renamed = registry.rename_entity(team.id, "Colorado Mammoth")
    assert renamed.id == team.id
    assert registry.get_entity(team.id).project_name == "Colorado Mammoth"
    rename_audit = registry.list_entity_audit(team.id)
    assert rename_audit[0].prior_name == "Colorado Avalanche"
    assert rename_audit[0].project_name == "Colorado Mammoth"


def test_pending_designation_requires_audited_owner_confirmation(tmp_path: Path) -> None:
    registry = make_registry(tmp_path)
    tournament = registry.create_entity("tournament", "League", sport="hockey")
    team = registry.create_entity("team", "Team One", sport="hockey")
    scope = {"sport": "hockey", "tournament": tournament.id}
    designation = registry.add_designation(
        entity_id=None,
        source="feed_a",
        kind="team",
        scope=scope,
        value_kind="name",
        raw_value="Team Oñe",
    )

    assert registry.resolve("feed_a", "team", scope, "name", "Team One").status == "unresolved"
    decision = registry.decide_designation(
        designation.id,
        action="confirm",
        entity_id=team.id,
        actor="owner",
        reason="Проверено по официальному источнику",
        expected_revision=designation.revision,
    )

    assert decision.actor == "owner"
    resolved = registry.resolve("feed_a", "team", scope, "name", "Team Oñe")
    assert resolved.status == "resolved"
    assert resolved.entity_id == team.id
    assert (
        registry.list_decisions(designation.id)[0].reason == "Проверено по официальному источнику"
    )


def test_overlapping_confirmed_designation_becomes_conflict_and_is_explicitly_resolved(
    tmp_path: Path,
) -> None:
    registry = make_registry(tmp_path)
    tournament = registry.create_entity("tournament", "League", sport="hockey")
    first = registry.create_entity("team", "Team One", sport="hockey")
    second = registry.create_entity("team", "Team Two", sport="hockey")
    scope = {"sport": "hockey", "tournament": tournament.id}
    key: dict[str, Any] = {
        "source": "feed_a",
        "kind": "team",
        "scope": scope,
        "value_kind": "external_id",
        "raw_value": "7",
    }
    registry.add_designation(entity_id=first.id, **key, state="confirmed")
    collided = registry.add_designation(entity_id=second.id, **key, state="confirmed")
    repeated = registry.add_designation(entity_id=second.id, **key, state="confirmed")

    assert repeated.id == collided.id
    assert registry.resolve("feed_a", "team", scope, "external_id", "7").status == "conflict"
    registry.decide_designation(
        collided.id,
        action="resolve_conflict",
        entity_id=second.id,
        actor="owner",
        reason="Источник сменил владельца ID; проверена дата",
        expected_revision=collided.revision,
    )
    assert registry.resolve("feed_a", "team", scope, "external_id", "7").entity_id == second.id
    assert len(registry.list_decisions(collided.id)) == 1


def test_player_memberships_keep_non_overlapping_history(tmp_path: Path) -> None:
    registry = make_registry(tmp_path)
    player = registry.create_entity("player", "Player One", sport="hockey")
    team_a = registry.create_entity("team", "Team A", sport="hockey")
    team_b = registry.create_entity("team", "Team B", sport="hockey")
    registry.add_membership(
        player.id, team_a.id, "club", "2020-01-01T00:00:00Z", "2022-07-01T00:00:00Z"
    )
    registry.add_membership(player.id, team_b.id, "club", "2022-07-01T03:00:00+03:00", None)

    assert registry.memberships_for_player(player.id) == [
        (team_a.id, "club", "2020-01-01T00:00:00.000000Z", "2022-07-01T00:00:00.000000Z"),
        (team_b.id, "club", "2022-07-01T00:00:00.000000Z", None),
    ]
    with pytest.raises(ValueError, match="пересекаются"):
        registry.add_membership(
            player.id,
            team_a.id,
            "club",
            "2022-01-01T00:00:00Z",
            "2023-01-01T00:00:00Z",
        )


def test_trusted_nhl_yaml_seed_is_idempotent_and_does_not_override_owner_decisions(
    tmp_path: Path,
) -> None:
    registry = make_registry(tmp_path)
    yaml_path = Path("conf/bookmaker/team_name_registry/nhl.yaml")
    first = import_nhl_yaml(registry, yaml_path)
    tournament = registry.list_entities(kind="tournament")[0]
    col = registry.resolve(
        "nhl_api",
        "team",
        {"sport": "ice_hockey", "tournament": tournament.id},
        "external_id",
        "COL",
    )
    assert col.status == "resolved"
    assert (
        registry.resolve(
            "the_odds_api",
            "team",
            {"sport": "ice_hockey", "tournament": tournament.id},
            "name",
            "Colorado Avalanche",
        ).entity_id
        == col.entity_id
    )
    assert import_nhl_yaml(registry, yaml_path) == first
    assert len(registry.list_entities(kind="team")) == 33

    designation = registry.find_designation(
        "the_odds_api",
        "team",
        {"sport": "ice_hockey", "tournament": tournament.id},
        "name",
        "Colorado Avalanche",
    )
    other_team = registry.create_entity("team", "Owner Choice", sport="ice_hockey")
    registry.decide_designation(
        designation.id,
        action="confirm",
        entity_id=other_team.id,
        actor="owner",
        reason="Коррекция владельца",
        expected_revision=designation.revision,
    )
    import_nhl_yaml(registry, yaml_path)
    assert (
        registry.resolve(
            "the_odds_api",
            "team",
            {"sport": "ice_hockey", "tournament": tournament.id},
            "name",
            "Colorado Avalanche",
        ).entity_id
        == other_team.id
    )


def test_same_contract_supports_a_second_tournament(tmp_path: Path) -> None:
    registry = make_registry(tmp_path)
    tournament = registry.create_entity("tournament", "Demo Cup", sport="football")
    team = registry.create_entity("team", "North City", sport="football")
    scope = {"sport": "football", "tournament": tournament.id, "season": "2025"}
    registry.add_designation(
        entity_id=team.id,
        source="demo_feed",
        kind="team",
        scope=scope,
        value_kind="external_id",
        raw_value="north-1",
        state="confirmed",
    )

    assert (
        registry.resolve("demo_feed", "team", scope, "external_id", "north-1").entity_id == team.id
    )


def test_seed_identity_is_stable_when_yaml_changes_and_preserves_owner_decisions(
    tmp_path: Path,
) -> None:
    registry = make_registry(tmp_path)
    first_yaml = tmp_path / "first.yaml"
    changed_yaml = tmp_path / "changed.yaml"
    first_yaml.write_text(
        "nhl_api:\n  COL: COL\nodds_api:\n  COLORADOAVALANCHE: COL\n", encoding="utf-8"
    )
    seed_id = import_nhl_yaml(registry, first_yaml)
    tournament = registry.list_entities(kind="tournament")[0]
    scope = {"sport": "ice_hockey", "tournament": tournament.id}
    designation = registry.find_designation(
        "the_odds_api", "team", scope, "name", "Colorado Avalanche"
    )
    owner_team = registry.create_entity("team", "Owner Choice", sport="ice_hockey")
    registry.decide_designation(
        designation.id,
        action="confirm",
        entity_id=owner_team.id,
        actor="owner",
        reason="Проверено владельцем",
        expected_revision=designation.revision,
    )
    changed_yaml.write_text(
        "# formatting changed\nnhl_api:\n  COL: COL\nodds_api:\n  COLORADOAVALANCHE: COL\n",
        encoding="utf-8",
    )

    assert import_nhl_yaml(registry, changed_yaml) == seed_id
    assert (
        registry.resolve("the_odds_api", "team", scope, "name", "Colorado Avalanche").entity_id
        == owner_team.id
    )
    assert len(registry.list_entities(kind="team")) == 2


def test_failed_seed_import_leaves_no_partial_entities_or_designations(tmp_path: Path) -> None:
    registry = make_registry(tmp_path)
    path = tmp_path / "invalid.yaml"
    path.write_text("nhl_api:\n  COL: COL\nodds_api:\n  FAIL: COL\n", encoding="utf-8")
    with registry._connect() as connection:
        connection.execute(
            "CREATE TRIGGER fail_seed_alias BEFORE INSERT ON designations "
            "WHEN NEW.raw_value='FAIL' BEGIN SELECT RAISE(ABORT,'injected seed failure'); END"
        )

    with pytest.raises(sqlite3.IntegrityError, match="injected seed failure"):
        import_nhl_yaml(registry, path)

    assert registry.list_entities() == []
    assert registry.count_designations() == 0


def test_duplicate_designations_respect_interval_and_state(tmp_path: Path) -> None:
    registry = make_registry(tmp_path)
    tournament = registry.create_entity("tournament", "League", sport="hockey")
    team = registry.create_entity("team", "Team", sport="hockey")
    common: dict[str, Any] = {
        "entity_id": team.id,
        "source": "feed",
        "kind": "team",
        "scope": {"sport": "hockey", "tournament": tournament.id},
        "value_kind": "external_id",
        "raw_value": "id",
        "state": "confirmed",
    }
    first = registry.add_designation(
        **common, valid_from="2020-01-01T00:00:00Z", valid_until="2021-01-01T00:00:00Z"
    )
    second = registry.add_designation(
        **common, valid_from="2021-01-01T00:00:00Z", valid_until="2022-01-01T00:00:00Z"
    )
    pending = registry.add_designation(
        **{**common, "state": "pending"},
        valid_from="2020-01-01T00:00:00Z",
        valid_until="2021-01-01T00:00:00Z",
    )

    assert len({first.id, second.id, pending.id}) == 3
    assert pending.state == "pending"


def test_resolution_at_date_ignores_conflicts_outside_active_interval(tmp_path: Path) -> None:
    registry = make_registry(tmp_path)
    tournament = registry.create_entity("tournament", "League", sport="hockey")
    teams = [registry.create_entity("team", name, sport="hockey") for name in ("A", "B", "C")]
    common: dict[str, Any] = {
        "source": "feed",
        "kind": "team",
        "scope": {"sport": "hockey", "tournament": tournament.id},
        "value_kind": "external_id",
        "raw_value": "7",
    }
    registry.add_designation(
        entity_id=teams[0].id,
        **common,
        state="confirmed",
        valid_from="2020-01-01T00:00:00Z",
        valid_until="2022-01-01T00:00:00Z",
    )
    registry.add_designation(
        entity_id=teams[1].id,
        **common,
        state="confirmed",
        valid_from="2021-01-01T00:00:00Z",
        valid_until="2023-01-01T00:00:00Z",
    )
    registry.add_designation(
        entity_id=teams[2].id,
        **common,
        state="confirmed",
        valid_from="2024-01-01T00:00:00Z",
        valid_until="2025-01-01T00:00:00Z",
    )

    assert (
        registry.resolve(
            "feed", "team", common["scope"], "external_id", "7", at="2024-06-01T03:00:00+03:00"
        ).entity_id
        == teams[2].id
    )


def test_owner_confirmation_rejects_overlapping_confirmed_peer(tmp_path: Path) -> None:
    registry = make_registry(tmp_path)
    tournament = registry.create_entity("tournament", "League", sport="hockey")
    first, second = [registry.create_entity("team", name, sport="hockey") for name in ("A", "B")]
    common: dict[str, Any] = {
        "source": "feed",
        "kind": "team",
        "scope": {"sport": "hockey", "tournament": tournament.id},
        "value_kind": "external_id",
        "raw_value": "7",
    }
    pending = registry.add_designation(
        entity_id=second.id,
        **common,
        state="pending",
        valid_from="2021-01-01T00:00:00Z",
        valid_until="2023-01-01T00:00:00Z",
    )
    registry.add_designation(
        entity_id=first.id,
        **common,
        state="confirmed",
        valid_from="2020-01-01T00:00:00Z",
        valid_until="2022-01-01T00:00:00Z",
    )

    with pytest.raises(ValueError, match="конфликт"):
        registry.decide_designation(
            pending.id,
            action="confirm",
            entity_id=second.id,
            actor="owner",
            reason="Проверка",
            expected_revision=pending.revision,
        )


def test_conflict_resolution_audits_overlap_without_rewriting_peer_state(tmp_path: Path) -> None:
    registry = make_registry(tmp_path)
    tournament = registry.create_entity("tournament", "League", sport="hockey")
    teams = [registry.create_entity("team", f"Team {i}", sport="hockey") for i in range(4)]
    common: dict[str, Any] = {
        "source": "feed",
        "kind": "team",
        "scope": {"sport": "hockey", "tournament": tournament.id},
        "value_kind": "external_id",
        "raw_value": "7",
        "state": "confirmed",
    }
    old_a = registry.add_designation(
        entity_id=teams[0].id,
        **common,
        valid_from="2020-01-01T00:00:00Z",
        valid_until="2022-01-01T00:00:00Z",
    )
    registry.add_designation(
        entity_id=teams[1].id,
        **common,
        valid_from="2021-01-01T00:00:00Z",
        valid_until="2023-01-01T00:00:00Z",
    )
    distant = registry.add_designation(
        entity_id=teams[2].id,
        **common,
        valid_from="2030-01-01T00:00:00Z",
        valid_until="2032-01-01T00:00:00Z",
    )
    selected = registry.add_designation(
        entity_id=teams[3].id,
        **common,
        valid_from="2031-01-01T00:00:00Z",
        valid_until="2033-01-01T00:00:00Z",
    )

    registry.decide_designation(
        selected.id,
        action="resolve_conflict",
        entity_id=teams[3].id,
        actor="owner",
        reason="Проверено",
        expected_revision=selected.revision,
    )

    assert registry.list_decisions(selected.id)[0].action == "resolve_conflict"
    assert registry.get_designation(distant.id).state == "confirmed"
    assert registry.list_decisions(distant.id)[0].action == "overlap_conflict_resolved"
    assert registry.get_designation(old_a.id).state == "confirmed"


def test_temporal_values_require_timezone_and_use_canonical_utc(tmp_path: Path) -> None:
    registry = make_registry(tmp_path)
    player = registry.create_entity("player", "Player", sport="hockey")
    first, second = [registry.create_entity("team", name, sport="hockey") for name in ("A", "B")]
    registry.add_membership(
        player.id, first.id, "club", "2020-01-01T00:00:00+03:00", "2020-01-02T00:00:00+03:00"
    )
    registry.add_membership(player.id, second.id, "club", "2020-01-01T21:00:00Z", None)
    assert registry.memberships_for_player(player.id)[0][2:] == (
        "2019-12-31T21:00:00.000000Z",
        "2020-01-01T21:00:00.000000Z",
    )
    with pytest.raises(ValueError, match="timezone"):
        registry.add_membership(player.id, first.id, "national", "2021-01-01T00:00:00", None)


def test_designation_with_suggested_entity_stays_pending_without_trusted_state(
    tmp_path: Path,
) -> None:
    registry = make_registry(tmp_path)
    tournament = registry.create_entity("tournament", "League", sport="hockey")
    team = registry.create_entity("team", "Likely", sport="hockey")
    designation = registry.add_designation(
        entity_id=team.id,
        source="feed",
        kind="team",
        scope={"sport": "hockey", "tournament": tournament.id},
        value_kind="name",
        raw_value="Likely",
    )
    assert designation.state == "pending"
    assert (
        registry.resolve("feed", "team", designation.scope, "name", "Likely").status == "unresolved"
    )


def test_owner_decision_rejects_stale_revision(tmp_path: Path) -> None:
    registry = make_registry(tmp_path)
    tournament = registry.create_entity("tournament", "League", sport="hockey")
    team = registry.create_entity("team", "Team", sport="hockey")
    designation = registry.add_designation(
        entity_id=team.id,
        source="feed",
        kind="team",
        scope={"sport": "hockey", "tournament": tournament.id},
        value_kind="name",
        raw_value="Team",
    )
    registry.decide_designation(
        designation.id,
        action="confirm",
        entity_id=team.id,
        actor="owner",
        reason="Подтверждено",
        expected_revision=designation.revision,
    )

    with pytest.raises(ValueError, match="устарела"):
        registry.decide_designation(
            designation.id,
            action="defer",
            entity_id=None,
            actor="owner",
            reason="Устаревшая форма",
            expected_revision=designation.revision,
        )


def test_initialize_upgrades_version_two_schema(tmp_path: Path) -> None:
    path = tmp_path / "registry.sqlite3"
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE entities (id TEXT PRIMARY KEY, kind TEXT, sport TEXT, project_name TEXT,
            seed_key TEXT, seed_entity_key TEXT, revision INTEGER, state TEXT,
            created_at TEXT, updated_at TEXT);
        CREATE TABLE designations (id TEXT PRIMARY KEY, source TEXT, kind TEXT, scope_json TEXT,
            value_kind TEXT, raw_value TEXT, normalized_value TEXT, entity_id TEXT, state TEXT,
            valid_from TEXT, valid_until TEXT, seed_key TEXT);
        CREATE TABLE decisions (id TEXT PRIMARY KEY, designation_id TEXT, actor TEXT, action TEXT,
            reason TEXT, prior_state TEXT, decided_at TEXT);
        CREATE TABLE entity_audit (id TEXT PRIMARY KEY, entity_id TEXT, actor TEXT, action TEXT,
            reason TEXT, prior_name TEXT, project_name TEXT, decided_at TEXT);
        CREATE TABLE memberships (id TEXT PRIMARY KEY, player_id TEXT, team_id TEXT,
            relation_kind TEXT, valid_from TEXT, valid_until TEXT);
        CREATE TABLE imports (seed_key TEXT PRIMARY KEY, imported_at TEXT NOT NULL);
        PRAGMA user_version = 2;
        """
    )
    connection.close()

    registry = EntityRegistry(path)
    registry.initialize()

    with sqlite3.connect(path) as migrated:
        assert migrated.execute("PRAGMA user_version").fetchone()[0] == 5
        assert "revision" in {row[1] for row in migrated.execute("PRAGMA table_info(designations)")}
        assert "content_hash" in {row[1] for row in migrated.execute("PRAGMA table_info(imports)")}
        assert "designation_conflicts" in {
            row[0] for row in migrated.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        conflict_schema = migrated.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='designation_conflicts'"
        ).fetchone()[0]
        assert "'dismissed'" in conflict_schema


def test_newer_conflict_does_not_change_resolution_before_its_interval(tmp_path: Path) -> None:
    registry = make_registry(tmp_path)
    tournament = registry.create_entity("tournament", "League", sport="hockey")
    team_a = registry.create_entity("team", "Team A", sport="hockey")
    team_b = registry.create_entity("team", "Team B", sport="hockey")
    scope = {"sport": "hockey", "tournament": tournament.id}
    common: dict[str, Any] = {
        "source": "feed",
        "kind": "team",
        "scope": scope,
        "value_kind": "external_id",
        "raw_value": "shared-id",
    }
    original = registry.add_designation(
        entity_id=team_a.id,
        **common,
        state="confirmed",
        valid_from="2020-01-01T00:00:00Z",
        valid_until="2030-01-01T00:00:00Z",
    )
    candidate = registry.add_designation(
        entity_id=team_b.id,
        **common,
        state="confirmed",
        valid_from="2025-01-01T00:00:00Z",
        valid_until="2026-01-01T00:00:00Z",
    )

    assert registry.get_designation(original.id).state == "confirmed"
    assert (
        registry.resolve(
            "feed", "team", scope, "external_id", "shared-id", at="2021-01-01T00:00:00Z"
        ).entity_id
        == team_a.id
    )
    assert (
        registry.resolve(
            "feed", "team", scope, "external_id", "shared-id", at="2025-06-01T00:00:00Z"
        ).status
        == "conflict"
    )

    registry.decide_designation(
        candidate.id,
        action="resolve_conflict",
        entity_id=team_b.id,
        actor="owner",
        reason="Проверено в архиве",
        expected_revision=candidate.revision,
    )

    assert (
        registry.resolve(
            "feed", "team", scope, "external_id", "shared-id", at="2021-01-01T00:00:00Z"
        ).entity_id
        == team_a.id
    )
    assert (
        registry.resolve(
            "feed", "team", scope, "external_id", "shared-id", at="2025-06-01T00:00:00Z"
        ).entity_id
        == team_b.id
    )
    assert registry.get_designation(original.id).state == "confirmed"
    assert registry.list_decisions(candidate.id)[0].action == "resolve_conflict"
    assert registry.list_decisions(original.id)[0].action == "overlap_conflict_resolved"


def test_seed_canonical_rename_keeps_team_uuid_by_nhl_source_id(tmp_path: Path) -> None:
    registry = make_registry(tmp_path)
    original_yaml = tmp_path / "original.yaml"
    renamed_yaml = tmp_path / "renamed.yaml"
    original_yaml.write_text(
        "nhl_api:\n  COL: COL\nodds_api:\n  COLORADOAVALANCHE: COL\n", encoding="utf-8"
    )
    import_nhl_yaml(registry, original_yaml)
    tournament = registry.list_entities(kind="tournament")[0]
    scope = {"sport": "ice_hockey", "tournament": tournament.id}
    original = registry.find_designation("nhl_api", "team", scope, "external_id", "COL")
    original_id = original.entity_id
    renamed_yaml.write_text(
        "nhl_api:\n  COL: COLORADO\nodds_api:\n  COLORADOAVALANCHE: COLORADO\n  COLORADONEWNAME: COLORADO\n",
        encoding="utf-8",
    )

    import_nhl_yaml(registry, renamed_yaml)

    renamed = registry.find_designation("nhl_api", "team", scope, "external_id", "COL")
    new_alias = registry.resolve("the_odds_api", "team", scope, "name", "Colorado New Name")
    assert renamed.entity_id == original_id
    assert new_alias.entity_id == original_id
    assert len(registry.list_entities(kind="team")) == 1


def test_resolving_overlap_does_not_rename_confirmed_base_interval(tmp_path: Path) -> None:
    registry = make_registry(tmp_path)
    tournament = registry.create_entity("tournament", "League", sport="hockey")
    team_a = registry.create_entity("team", "Team A", sport="hockey")
    team_b = registry.create_entity("team", "Team B", sport="hockey")
    scope = {"sport": "hockey", "tournament": tournament.id}
    common: dict[str, Any] = {
        "source": "feed",
        "kind": "team",
        "scope": scope,
        "value_kind": "external_id",
        "raw_value": "interval-choice",
    }
    original = registry.add_designation(
        entity_id=team_a.id,
        **common,
        state="confirmed",
        valid_from="2020-01-01T00:00:00Z",
        valid_until="2030-01-01T00:00:00Z",
    )
    registry.add_designation(
        entity_id=team_b.id,
        **common,
        state="confirmed",
        valid_from="2025-01-01T00:00:00Z",
        valid_until="2026-01-01T00:00:00Z",
    )

    registry.decide_designation(
        original.id,
        action="resolve_conflict",
        entity_id=team_b.id,
        actor="owner",
        reason="B относится к этому периоду",
        expected_revision=original.revision,
    )

    assert (
        registry.resolve(
            "feed", "team", scope, "external_id", "interval-choice", at="2021-01-01T00:00:00Z"
        ).entity_id
        == team_a.id
    )
    assert (
        registry.resolve(
            "feed", "team", scope, "external_id", "interval-choice", at="2025-06-01T00:00:00Z"
        ).entity_id
        == team_b.id
    )
    assert registry.get_designation(original.id).entity_id == team_a.id


def test_partial_overlap_resolution_keeps_unresolved_interval_remainder(tmp_path: Path) -> None:
    registry = make_registry(tmp_path)
    tournament = registry.create_entity("tournament", "League", sport="hockey")
    team_a = registry.create_entity("team", "Team A", sport="hockey")
    team_b = registry.create_entity("team", "Team B", sport="hockey")
    scope = {"sport": "hockey", "tournament": tournament.id}
    common: dict[str, Any] = {
        "source": "feed",
        "kind": "team",
        "scope": scope,
        "value_kind": "external_id",
        "raw_value": "partial-resolution",
    }
    original = registry.add_designation(
        entity_id=team_a.id,
        **common,
        state="confirmed",
        valid_from="2020-01-01T00:00:00Z",
        valid_until="2030-01-01T00:00:00Z",
    )
    registry.add_designation(
        entity_id=team_b.id,
        **common,
        state="confirmed",
        valid_from="2025-01-01T00:00:00Z",
        valid_until="2028-01-01T00:00:00Z",
    )

    registry.decide_designation(
        original.id,
        action="resolve_conflict",
        entity_id=team_b.id,
        actor="owner",
        reason="Выбрана только проверенная часть интервала",
        expected_revision=original.revision,
        conflict_period=("2025-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
    )

    assert (
        registry.resolve(
            "feed", "team", scope, "external_id", "partial-resolution", at="2025-06-01T00:00:00Z"
        ).entity_id
        == team_b.id
    )
    assert (
        registry.resolve(
            "feed", "team", scope, "external_id", "partial-resolution", at="2026-06-01T00:00:00Z"
        ).status
        == "conflict"
    )
    assert (
        registry.resolve(
            "feed", "team", scope, "external_id", "partial-resolution", at="2028-06-01T00:00:00Z"
        ).entity_id
        == team_a.id
    )


def test_rejecting_overlap_candidate_resolves_to_remaining_confirmed_peer(tmp_path: Path) -> None:
    registry = make_registry(tmp_path)
    tournament = registry.create_entity("tournament", "League", sport="hockey")
    team_a = registry.create_entity("team", "Team A", sport="hockey")
    team_b = registry.create_entity("team", "Team B", sport="hockey")
    scope = {"sport": "hockey", "tournament": tournament.id}
    common: dict[str, Any] = {
        "source": "feed",
        "kind": "team",
        "scope": scope,
        "value_kind": "external_id",
        "raw_value": "rejected-overlap",
    }
    original = registry.add_designation(
        entity_id=team_a.id,
        **common,
        state="confirmed",
        valid_from="2020-01-01T00:00:00Z",
        valid_until="2030-01-01T00:00:00Z",
    )
    candidate = registry.add_designation(
        entity_id=team_b.id,
        **common,
        state="confirmed",
        valid_from="2025-01-01T00:00:00Z",
        valid_until="2026-01-01T00:00:00Z",
    )

    registry.decide_designation(
        candidate.id,
        action="defer",
        entity_id=None,
        actor="owner",
        reason="Отложено до проверки источника",
        expected_revision=candidate.revision,
    )
    assert (
        registry.resolve(
            "feed", "team", scope, "external_id", "rejected-overlap", at="2025-06-01T00:00:00Z"
        ).status
        == "conflict"
    )
    candidate = registry.get_designation(candidate.id)
    registry.decide_designation(
        candidate.id,
        action="reject",
        entity_id=None,
        actor="owner",
        reason="Кандидат проверен и отклонён",
        expected_revision=candidate.revision,
    )

    assert (
        registry.resolve(
            "feed", "team", scope, "external_id", "rejected-overlap", at="2025-06-01T00:00:00Z"
        ).entity_id
        == team_a.id
    )
    assert registry.get_designation(original.id).state == "confirmed"
    assert registry.get_designation(candidate.id).state == "rejected"
    assert registry.list_decisions(original.id)[0].action == "overlap_conflict_dismissed"


def test_new_nhl_source_alias_keeps_existing_seed_entity(tmp_path: Path) -> None:
    registry = make_registry(tmp_path)
    original_yaml = tmp_path / "original.yaml"
    expanded_yaml = tmp_path / "expanded.yaml"
    original_yaml.write_text(
        "nhl_api:\n  COL: COL\nodds_api:\n  COLORADOAVALANCHE: COL\n", encoding="utf-8"
    )
    import_nhl_yaml(registry, original_yaml)
    tournament = registry.list_entities(kind="tournament")[0]
    scope = {"sport": "ice_hockey", "tournament": tournament.id}
    original = registry.find_designation("nhl_api", "team", scope, "external_id", "COL")
    expanded_yaml.write_text(
        "nhl_api:\n  COL: COL\n  AAA: COL\nodds_api:\n  COLORADOAVALANCHE: COL\n", encoding="utf-8"
    )

    import_nhl_yaml(registry, expanded_yaml)

    existing = registry.find_designation("nhl_api", "team", scope, "external_id", "COL")
    added = registry.find_designation("nhl_api", "team", scope, "external_id", "AAA")
    assert existing.entity_id == original.entity_id
    assert added.entity_id == original.entity_id
    assert len(registry.list_entities(kind="team")) == 1


def test_rejecting_one_of_three_candidates_leaves_other_conflict_open(tmp_path: Path) -> None:
    registry = make_registry(tmp_path)
    tournament = registry.create_entity("tournament", "League", sport="hockey")
    team_a, team_b, team_c = [
        registry.create_entity("team", name, sport="hockey") for name in ("A", "B", "C")
    ]
    scope = {"sport": "hockey", "tournament": tournament.id}
    common: dict[str, Any] = {
        "source": "feed",
        "kind": "team",
        "scope": scope,
        "value_kind": "external_id",
        "raw_value": "three-candidates",
        "valid_from": "2025-01-01T00:00:00Z",
        "valid_until": "2026-01-01T00:00:00Z",
    }
    registry.add_designation(entity_id=team_a.id, state="confirmed", **common)
    candidate_b = registry.add_designation(entity_id=team_b.id, state="confirmed", **common)
    candidate_c = registry.add_designation(entity_id=team_c.id, state="confirmed", **common)

    registry.decide_designation(
        candidate_b.id,
        action="reject",
        entity_id=None,
        actor="owner",
        reason="B отклонён, C ещё требует проверки",
        expected_revision=candidate_b.revision,
    )

    assert (
        registry.resolve(
            "feed", "team", scope, "external_id", "three-candidates", at="2025-06-01T00:00:00Z"
        ).status
        == "conflict"
    )
    current_c = registry.get_designation(candidate_c.id)
    registry.decide_designation(
        candidate_c.id,
        action="resolve_conflict",
        entity_id=team_a.id,
        actor="owner",
        reason="C также сопоставлен с A",
        expected_revision=current_c.revision,
    )
    assert (
        registry.resolve(
            "feed", "team", scope, "external_id", "three-candidates", at="2025-06-01T00:00:00Z"
        ).entity_id
        == team_a.id
    )


def test_new_confirmed_base_resolves_after_overlap_ends_and_audits_resolution(
    tmp_path: Path,
) -> None:
    registry = make_registry(tmp_path)
    tournament = registry.create_entity("tournament", "League", sport="hockey")
    team_a = registry.create_entity("team", "Team A", sport="hockey")
    team_b = registry.create_entity("team", "Team B", sport="hockey")
    scope = {"sport": "hockey", "tournament": tournament.id}
    common: dict[str, Any] = {
        "source": "feed",
        "kind": "team",
        "scope": scope,
        "value_kind": "external_id",
        "raw_value": "confirmed-tail",
    }
    original = registry.add_designation(
        entity_id=team_a.id,
        **common,
        state="confirmed",
        valid_from="2020-01-01T00:00:00Z",
        valid_until="2025-01-01T00:00:00Z",
    )
    later = registry.add_designation(
        entity_id=team_b.id,
        **common,
        state="confirmed",
        valid_from="2024-01-01T00:00:00Z",
        valid_until="2030-01-01T00:00:00Z",
    )

    assert registry.get_designation(later.id).state == "confirmed"
    assert (
        registry.resolve(
            "feed", "team", scope, "external_id", "confirmed-tail", at="2023-01-01T00:00:00Z"
        ).entity_id
        == team_a.id
    )
    assert (
        registry.resolve(
            "feed", "team", scope, "external_id", "confirmed-tail", at="2024-06-01T00:00:00Z"
        ).status
        == "conflict"
    )
    assert (
        registry.resolve(
            "feed", "team", scope, "external_id", "confirmed-tail", at="2026-01-01T00:00:00Z"
        ).entity_id
        == team_b.id
    )

    current = registry.get_designation(later.id)
    registry.decide_designation(
        later.id,
        action="resolve_conflict",
        entity_id=team_b.id,
        actor="owner",
        reason="Проверен временной конфликт",
        expected_revision=current.revision,
    )

    assert registry.get_designation(original.id).revision == 2
    assert registry.list_decisions(original.id)[0].action == "overlap_conflict_resolved"


def test_pending_candidate_blocks_only_overlap_and_adjacent_periods_do_not_conflict(
    tmp_path: Path,
) -> None:
    registry = make_registry(tmp_path)
    tournament = registry.create_entity("tournament", "League", sport="hockey")
    team_a = registry.create_entity("team", "Team A", sport="hockey")
    team_b = registry.create_entity("team", "Team B", sport="hockey")
    scope = {"sport": "hockey", "tournament": tournament.id}
    common: dict[str, Any] = {
        "source": "feed",
        "kind": "team",
        "scope": scope,
        "value_kind": "external_id",
        "raw_value": "pending-tail",
    }
    registry.add_designation(
        entity_id=team_a.id,
        **common,
        state="confirmed",
        valid_from="2020-01-01T00:00:00Z",
        valid_until="2025-01-01T00:00:00Z",
    )
    pending = registry.add_designation(
        entity_id=team_b.id,
        **common,
        state="pending",
        valid_from="2024-01-01T00:00:00Z",
        valid_until="2030-01-01T00:00:00Z",
    )

    assert pending.state == "pending"
    assert (
        registry.resolve(
            "feed", "team", scope, "external_id", "pending-tail", at="2023-01-01T00:00:00Z"
        ).entity_id
        == team_a.id
    )
    assert (
        registry.resolve(
            "feed", "team", scope, "external_id", "pending-tail", at="2024-06-01T00:00:00Z"
        ).status
        == "conflict"
    )
    assert (
        registry.resolve(
            "feed", "team", scope, "external_id", "pending-tail", at="2026-01-01T00:00:00Z"
        ).status
        == "unresolved"
    )

    adjacent = "adjacent-periods"
    registry.add_designation(
        source="feed",
        kind="team",
        scope=scope,
        value_kind="external_id",
        raw_value=adjacent,
        entity_id=team_a.id,
        state="confirmed",
        valid_from="2020-01-01T00:00:00Z",
        valid_until="2025-01-01T00:00:00Z",
    )
    registry.add_designation(
        source="feed",
        kind="team",
        scope=scope,
        value_kind="external_id",
        raw_value=adjacent,
        entity_id=team_b.id,
        state="confirmed",
        valid_from="2025-01-01T00:00:00Z",
        valid_until="2030-01-01T00:00:00Z",
    )
    assert (
        registry.resolve(
            "feed", "team", scope, "external_id", adjacent, at="2024-12-31T00:00:00Z"
        ).entity_id
        == team_a.id
    )
    assert (
        registry.resolve(
            "feed", "team", scope, "external_id", adjacent, at="2025-01-01T00:00:00Z"
        ).entity_id
        == team_b.id
    )


def test_confirmed_base_added_after_pending_candidate_creates_overlap_overlay(
    tmp_path: Path,
) -> None:
    registry = make_registry(tmp_path)
    tournament = registry.create_entity("tournament", "League", sport="hockey")
    team_a = registry.create_entity("team", "Team A", sport="hockey")
    team_b = registry.create_entity("team", "Team B", sport="hockey")
    scope = {"sport": "hockey", "tournament": tournament.id}
    common: dict[str, Any] = {
        "source": "feed",
        "kind": "team",
        "scope": scope,
        "value_kind": "external_id",
        "raw_value": "pending-before-confirmed",
    }
    pending = registry.add_designation(
        entity_id=team_b.id,
        **common,
        state="pending",
        valid_from="2024-01-01T00:00:00Z",
        valid_until="2030-01-01T00:00:00Z",
    )
    confirmed = registry.add_designation(
        entity_id=team_a.id,
        **common,
        state="confirmed",
        valid_from="2020-01-01T00:00:00Z",
        valid_until="2025-01-01T00:00:00Z",
    )

    assert pending.state == "pending"
    assert confirmed.state == "confirmed"
    assert (
        registry.resolve(
            "feed",
            "team",
            scope,
            "external_id",
            "pending-before-confirmed",
            at="2022-01-01T00:00:00Z",
        ).entity_id
        == team_a.id
    )
    assert (
        registry.resolve(
            "feed",
            "team",
            scope,
            "external_id",
            "pending-before-confirmed",
            at="2024-06-01T00:00:00Z",
        ).status
        == "conflict"
    )
    assert (
        registry.resolve(
            "feed",
            "team",
            scope,
            "external_id",
            "pending-before-confirmed",
            at="2026-01-01T00:00:00Z",
        ).status
        == "unresolved"
    )


def test_rejected_unbounded_overlay_does_not_make_no_date_resolution_ambiguous(
    tmp_path: Path,
) -> None:
    registry = make_registry(tmp_path)
    tournament = registry.create_entity("tournament", "League", sport="hockey")
    team_a = registry.create_entity("team", "Team A", sport="hockey")
    team_b = registry.create_entity("team", "Team B", sport="hockey")
    scope = {"sport": "hockey", "tournament": tournament.id}
    common: dict[str, Any] = {
        "source": "feed",
        "kind": "team",
        "scope": scope,
        "value_kind": "external_id",
        "raw_value": "rejected-unbounded",
    }
    original = registry.add_designation(entity_id=team_a.id, state="confirmed", **common)
    candidate = registry.add_designation(entity_id=team_b.id, state="confirmed", **common)
    registry.decide_designation(
        candidate.id,
        action="reject",
        entity_id=None,
        actor="owner",
        reason="Отклонено после проверки",
        expected_revision=candidate.revision,
    )

    result = registry.resolve("feed", "team", scope, "external_id", "rejected-unbounded")
    assert result.entity_id == team_a.id
    assert registry.get_designation(original.id).state == "confirmed"


@pytest.mark.parametrize(
    ("valid_from", "valid_until", "resolve_at"),
    [
        (None, None, None),
        ("2020-01-01T00:00:00Z", "2030-01-01T00:00:00Z", "2025-06-01T00:00:00Z"),
    ],
)
def test_rejecting_selected_entity_invalidates_prior_resolution_with_audit(
    tmp_path: Path,
    valid_from: str | None,
    valid_until: str | None,
    resolve_at: str | None,
) -> None:
    registry = make_registry(tmp_path)
    tournament = registry.create_entity("tournament", "League", sport="hockey")
    team_a = registry.create_entity("team", "Team A", sport="hockey")
    team_b = registry.create_entity("team", "Team B", sport="hockey")
    scope = {"sport": "hockey", "tournament": tournament.id}
    common: dict[str, Any] = {
        "source": "feed",
        "kind": "team",
        "scope": scope,
        "value_kind": "external_id",
        "raw_value": "corrected-owner-choice",
    }
    registry.add_designation(
        entity_id=team_a.id,
        **common,
        state="confirmed",
        valid_from=valid_from,
        valid_until=valid_until,
    )
    candidate = registry.add_designation(
        entity_id=team_b.id,
        **common,
        state="confirmed",
        valid_from=valid_from,
        valid_until=valid_until,
    )
    registry.decide_designation(
        candidate.id,
        action="resolve_conflict",
        entity_id=team_b.id,
        actor="owner",
        reason="Первичное решение",
        expected_revision=candidate.revision,
    )
    assert (
        registry.resolve(
            "feed", "team", scope, "external_id", "corrected-owner-choice", at=resolve_at
        ).entity_id
        == team_b.id
    )

    current = registry.get_designation(candidate.id)
    registry.decide_designation(
        candidate.id,
        action="reject",
        entity_id=None,
        actor="owner",
        reason="Исправление после повторной проверки",
        expected_revision=current.revision,
    )

    result = registry.resolve(
        "feed", "team", scope, "external_id", "corrected-owner-choice", at=resolve_at
    )
    assert result.entity_id == team_a.id
    assert [decision.action for decision in registry.list_decisions(candidate.id)] == [
        "resolve_conflict",
        "reject",
    ]
    with registry._connect(write=False) as connection:
        invalidated = connection.execute(
            "SELECT designation_id,peer_designation_id,state,selected_entity_id FROM designation_conflicts WHERE (designation_id=? OR peer_designation_id=?)",
            (candidate.id, candidate.id),
        ).fetchall()
    assert invalidated
    assert all(row["state"] == "dismissed" for row in invalidated)
    assert all(row["selected_entity_id"] == team_b.id for row in invalidated)
    peer = registry.get_designation(
        next(
            row["peer_designation_id"]
            if row["designation_id"] == candidate.id
            else row["designation_id"]
            for row in invalidated
        )
    )
    assert peer.revision == 3
    assert registry.list_decisions(peer.id)[-1].action == "overlap_conflict_invalidated"
