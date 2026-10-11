from sports_forecast.data.providers.nhl.schedule import ScheduleGameStub
from sports_forecast.identity.nhl_event_bootstrap import bootstrap_nhl_events
from sports_forecast.identity.registry import EntityRegistry
from sports_forecast.identity.review_service import ReviewQueueService


def _registry(path, *, car_valid_until=None, nhl_valid_until=None):
    registry = EntityRegistry(path)
    registry.initialize()
    tournament = registry.create_entity("tournament", "NHL", sport="ice_hockey")
    registry.add_designation(
        entity_id=tournament.id,
        source="nhl_web_api",
        kind="tournament",
        scope={"sport": "ice_hockey"},
        value_kind="name",
        raw_value="nhl",
        state="confirmed",
        valid_until=nhl_valid_until,
    )
    teams = {}
    for abbrev, name in (("CAR", "Carolina Hurricanes"), ("BUF", "Buffalo Sabres")):
        team = registry.create_entity("team", name, sport="ice_hockey")
        registry.add_designation(
            entity_id=team.id,
            source="nhl_web_api",
            kind="team",
            scope={"sport": "ice_hockey", "tournament": tournament.id},
            value_kind="name",
            raw_value=abbrev,
            state="confirmed",
            valid_until=car_valid_until if abbrev == "CAR" else None,
        )
        teams[abbrev] = team
    return registry, tournament, teams


def _game(game_id=2026020001, *, home="CAR", away="BUF", starts="2026-10-10T23:00:00Z"):
    return ScheduleGameStub(
        game_id=game_id,
        season=20262027,
        game_type=2,
        game_date="2026-10-10",
        start_time_utc=starts,
        venue_default="",
        home_abbrev=home,
        away_abbrev=away,
        game_state="FUT",
        match_end=None,
        home_score=None,
        away_score=None,
    )


def _add_existing_event(registry, tournament, teams, game, *, valid_until=None, inactive=False):
    event = registry.create_entity("event", "Existing event", sport="ice_hockey")
    registry.set_event_relation(
        event.id,
        tournament_id=tournament.id,
        home_team_id=teams[game.home_abbrev].id,
        away_team_id=teams[game.away_abbrev].id,
        scheduled_at=game.start_time_utc,
        actor="owner",
        reason="Existing confirmed event",
    )
    registry.add_designation(
        entity_id=event.id,
        source="nhl_web_api",
        kind="event",
        scope={"sport": "ice_hockey", "tournament": tournament.id},
        value_kind="external_id",
        raw_value=str(game.game_id),
        state="confirmed",
        valid_until=valid_until,
    )
    if inactive:
        with registry._connect() as connection:
            connection.execute("UPDATE entities SET state='inactive' WHERE id=?", (event.id,))
    return event


def test_dry_run_plans_without_mutating_registry(tmp_path):
    registry, _, _ = _registry(tmp_path / "registry.sqlite3")

    report = bootstrap_nhl_events([_game()], registry)

    assert report.items[0].status == "planned"
    assert registry.list_entities(kind="event") == []


def test_apply_creates_audited_event_and_is_idempotent(tmp_path):
    registry, tournament, teams = _registry(tmp_path / "registry.sqlite3")
    game = _game()

    first = bootstrap_nhl_events([game], registry, dry_run=False)
    second = bootstrap_nhl_events([game], registry, dry_run=False)

    assert first.items[0].status == "created"
    event_id = first.items[0].project_event_id
    assert event_id is not None
    assert second.items[0].status == "already_present"
    relation = registry.get_event_relation(event_id)
    assert relation.tournament_id == tournament.id
    assert (relation.home_team_id, relation.away_team_id) == (
        teams["CAR"].id,
        teams["BUF"].id,
    )
    assert relation.scheduled_at == "2026-10-10T23:00:00.000000Z"
    designation = registry.find_designation(
        "nhl_web_api",
        "event",
        {"sport": "ice_hockey", "tournament": tournament.id},
        "external_id",
        str(game.game_id),
    )
    assert designation.entity_id == event_id
    assert designation.state == "confirmed"
    audit = registry.list_event_relation_audit(event_id)
    assert audit[0].actor == "nhl_web_api"
    assert str(game.game_id) in audit[0].reason


def test_expired_event_source_designation_requires_review(tmp_path):
    registry, tournament, teams = _registry(tmp_path / "registry.sqlite3")
    game = _game()
    _add_existing_event(
        registry,
        tournament,
        teams,
        game,
        valid_until="2026-10-10T22:59:59Z",
    )

    report = bootstrap_nhl_events([game], registry, dry_run=False)

    assert report.items[0].status == "needs_review"
    assert report.items[0].reason == "source_designation_not_valid_at_event_time"


def test_inactive_existing_event_requires_review(tmp_path):
    registry, tournament, teams = _registry(tmp_path / "registry.sqlite3")
    game = _game()
    _add_existing_event(registry, tournament, teams, game, inactive=True)

    report = bootstrap_nhl_events([game], registry, dry_run=False)

    assert report.items[0].status == "needs_review"
    assert report.items[0].reason == "source_entity_not_active"


def test_unconfirmed_or_ambiguous_input_stays_for_owner_review(tmp_path):
    registry, _, _ = _registry(tmp_path / "registry.sqlite3")

    report = bootstrap_nhl_events(
        [_game(home="FAKE"), _game(game_id=2026020002, starts="")], registry
    )

    assert [item.status for item in report.items] == ["needs_review", "needs_review"]
    assert registry.list_entities(kind="event") == []


def test_apply_persists_review_items_idempotently_with_source_facts(tmp_path):
    registry, _, _ = _registry(tmp_path / "registry.sqlite3")
    game = _game(home="FAKE")

    first = bootstrap_nhl_events([game], registry, dry_run=False)
    second = bootstrap_nhl_events([game], registry, dry_run=False)

    queue = ReviewQueueService(registry)
    candidates = queue.list_candidates(source="nhl_web_api", query=str(game.game_id))
    assert len(candidates) == 1
    assert first.items[0].candidate_id == candidates[0].id
    assert second.items[0].candidate_id == candidates[0].id
    assert candidates[0].facts["source_event_id"] == str(game.game_id)
    assert candidates[0].facts["home_abbrev"] == "FAKE"
    assert candidates[0].facts["reason"] == "designation_not_uniquely_confirmed"
    assert candidates[0].observation_count == 2


def test_dry_run_does_not_persist_review_items(tmp_path):
    registry, _, _ = _registry(tmp_path / "registry.sqlite3")

    bootstrap_nhl_events([_game(home="FAKE")], registry, dry_run=True)

    assert ReviewQueueService(registry).list_candidates(source="nhl_web_api") == []


def test_expired_team_designation_is_not_used_for_event(tmp_path):
    registry, _, _ = _registry(
        tmp_path / "registry.sqlite3", car_valid_until="2026-10-10T22:59:59Z"
    )

    report = bootstrap_nhl_events([_game()], registry, dry_run=False)

    assert report.items[0].status == "needs_review"
    assert report.items[0].reason == "designation_not_valid_at_event_time"
    assert registry.list_entities(kind="event") == []
    candidates = ReviewQueueService(registry).list_candidates(
        source="nhl_web_api", query=str(2026020001)
    )
    assert len(candidates) == 1


def test_expired_tournament_designation_is_not_used_for_event(tmp_path):
    registry, tournament, _ = _registry(
        tmp_path / "registry.sqlite3", nhl_valid_until="2026-10-10T22:59:59Z"
    )

    report = bootstrap_nhl_events([_game()], registry, dry_run=False)

    assert report.items[0].status == "needs_review"
    assert report.items[0].reason == "designation_not_valid_at_event_time"
    assert registry.list_entities(kind="event") == []
    candidates = ReviewQueueService(registry).list_candidates(
        source="nhl_web_api", query=str(2026020001)
    )
    assert len(candidates) == 1
    assert candidates[0].scope["tournament"] == tournament.id


def test_inactive_team_entity_is_not_used_for_event(tmp_path):
    registry, _, teams = _registry(tmp_path / "registry.sqlite3")
    with registry._connect() as connection:
        connection.execute("UPDATE entities SET state='inactive' WHERE id=?", (teams["CAR"].id,))

    report = bootstrap_nhl_events([_game()], registry, dry_run=False)

    assert report.items[0].status == "needs_review"
    assert report.items[0].reason == "entity_not_active"
    assert registry.list_entities(kind="event") == []


def test_source_id_conflict_does_not_create_or_reassign_event(tmp_path):
    registry, tournament, teams = _registry(tmp_path / "registry.sqlite3")
    existing = registry.create_entity("event", "Existing event", sport="ice_hockey")
    registry.set_event_relation(
        existing.id,
        tournament_id=tournament.id,
        home_team_id=teams["CAR"].id,
        away_team_id=teams["BUF"].id,
        scheduled_at="2026-10-10T23:00:00Z",
        actor="owner",
        reason="Existing confirmed event",
    )
    registry.add_designation(
        entity_id=existing.id,
        source="nhl_web_api",
        kind="event",
        scope={"sport": "ice_hockey", "tournament": tournament.id},
        value_kind="external_id",
        raw_value=str(2026020001),
        state="confirmed",
    )

    report = bootstrap_nhl_events([_game(home="BUF", away="CAR")], registry)

    assert report.items[0].status == "needs_review"
    assert report.items[0].reason == "source_id_conflict"
    assert len(registry.list_entities(kind="event")) == 1


def test_existing_relation_without_source_key_is_not_duplicated(tmp_path):
    registry, tournament, teams = _registry(tmp_path / "registry.sqlite3")
    existing = registry.create_entity("event", "Existing event", sport="ice_hockey")
    registry.set_event_relation(
        existing.id,
        tournament_id=tournament.id,
        home_team_id=teams["CAR"].id,
        away_team_id=teams["BUF"].id,
        scheduled_at="2026-10-10T23:00:00Z",
        actor="owner",
        reason="Existing confirmed event",
    )

    report = bootstrap_nhl_events([_game()], registry, dry_run=False)

    assert report.items[0].status == "needs_review"
    assert report.items[0].reason == "relation_conflict"
    assert len(registry.list_entities(kind="event")) == 1
