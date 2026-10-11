"""Подготовка project events из подтверждённого NHL schedule."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from sports_forecast.data.providers.nhl.schedule import ScheduleGameStub
from sports_forecast.identity.registry import EntityRegistry, _canonical_utc, _normalize, _timestamp
from sports_forecast.identity.review_service import CandidateObservation, ReviewQueueService


_SOURCE = "nhl_web_api"
_ACTOR = "nhl_web_api"
_SEED_KEY = "official:nhl_web_api:schedule:v1"


@dataclass(frozen=True)
class NHLBootstrapItem:
    """Решение по одной строке официального расписания."""

    source_event_id: str
    status: Literal["planned", "created", "already_present", "needs_review"]
    reason: str
    project_event_id: str | None = None
    candidate_id: str | None = None


@dataclass(frozen=True)
class NHLBootstrapReport:
    """Результаты dry-run или атомарного применения расписания."""

    items: tuple[NHLBootstrapItem, ...]
    dry_run: bool


def _confirmed_entity_id(
    connection,
    *,
    source: str,
    kind: str,
    scope: dict[str, str],
    value_kind: str,
    raw_value: str,
    at_utc: str | None = None,
) -> tuple[str | None, str]:
    scope_json = EntityRegistry._scope_json(scope)
    normalized = _normalize(raw_value, value_kind)
    rows = connection.execute(
        "SELECT id,entity_id,state,valid_from,valid_until FROM designations WHERE source=? AND kind=? "
        "AND scope_json=? AND value_kind=? AND normalized_value=? ORDER BY id",
        (source, kind, scope_json, value_kind, normalized),
    ).fetchall()
    if len(rows) != 1 or rows[0]["state"] != "confirmed" or not rows[0]["entity_id"]:
        return None, "designation_not_uniquely_confirmed"
    designation_id = rows[0]["id"]
    conflicts = connection.execute(
        "SELECT state,valid_from,valid_until FROM designation_conflicts WHERE "
        "(designation_id=? OR peer_designation_id=?) AND state<>'dismissed'",
        (designation_id, designation_id),
    ).fetchall()
    if conflicts:
        active_conflicts = conflicts
        if at_utc is not None:
            active_conflicts = []
            for conflict in conflicts:
                starts = _canonical_utc(conflict["valid_from"])
                ends = _canonical_utc(conflict["valid_until"])
                if (starts is None or starts <= at_utc) and (ends is None or at_utc < ends):
                    active_conflicts.append(conflict)
        if active_conflicts:
            return None, "designation_has_conflict"
    starts = _canonical_utc(rows[0]["valid_from"])
    ends = _canonical_utc(rows[0]["valid_until"])
    if at_utc is not None and (
        (starts is not None and starts > at_utc) or (ends is not None and at_utc >= ends)
    ):
        return None, "designation_not_valid_at_event_time"
    entity = connection.execute(
        "SELECT kind,sport,state FROM entities WHERE id=?", (rows[0]["entity_id"],)
    ).fetchone()
    if entity is None or entity["state"] != "active" or entity["kind"] != kind:
        return None, "entity_not_active"
    if entity["sport"] != "ice_hockey":
        return None, "entity_sport_mismatch"
    return rows[0]["entity_id"], "confirmed"


def _scheduled_at(raw: str) -> str | None:
    """Проверить точное время UTC, не интерпретируя локальную дату как UTC."""
    if not raw or not (raw.endswith("Z") or raw.endswith("+00:00")):
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        return None
    return _canonical_utc(parsed.isoformat())


def bootstrap_nhl_events(
    games: Sequence[ScheduleGameStub],
    registry: EntityRegistry,
    *,
    dry_run: bool = True,
) -> NHLBootstrapReport:
    """Спланировать или атомарно зарегистрировать однозначные NHL schedule events.

    Подтверждённые team designations должны существовать заранее. Запись не делает
    HTTP-запросов и сохраняет NHL game ID и actor/provenance в registry audit.
    Сомнительные, неполные и конфликтующие строки остаются ``needs_review``.
    """
    game_ids = [str(game.game_id) for game in games]
    duplicate_ids = {key for key, count in Counter(game_ids).items() if count > 1}
    relation_keys = [
        (game.home_abbrev, game.away_abbrev, _scheduled_at(game.start_time_utc)) for game in games
    ]
    relation_counts = Counter(relation_keys)
    duplicated_relations = {key for key, count in relation_counts.items() if count > 1}
    items: list[NHLBootstrapItem] = []
    with registry._connect(write=not dry_run) as connection:
        review_queue = ReviewQueueService(registry)
        tournament_id, tournament_state = _confirmed_entity_id(
            connection,
            source="nhl_web_api",
            kind="tournament",
            scope={"sport": "ice_hockey"},
            value_kind="name",
            raw_value="nhl",
        )
        team_scope = (
            {"sport": "ice_hockey", "tournament": tournament_id}
            if tournament_id is not None
            else None
        )

        def make_item(
            game: ScheduleGameStub,
            source_event_id: str,
            status: Literal["planned", "created", "already_present", "needs_review"],
            reason: str,
            project_event_id: str | None = None,
        ) -> NHLBootstrapItem:
            candidate_id = None
            if status == "needs_review" and not dry_run:
                scope = {
                    "sport": "ice_hockey",
                    "tournament": tournament_id or "nhl",
                }
                origin = "local:nhl-event-bootstrap"
                idempotency_key = f"nhl-game:{source_event_id}"
                prior = connection.execute(
                    "SELECT d.scope_json FROM review_candidates c "
                    "JOIN designations d ON d.id=c.designation_id "
                    "WHERE c.origin=? AND c.idempotency_key=?",
                    (origin, idempotency_key),
                ).fetchone()
                if prior is not None:
                    scope = json.loads(prior["scope_json"])
                observation = CandidateObservation(
                    source=_SOURCE,
                    kind="event",
                    scope=scope,
                    value_kind="external_id",
                    raw_value=source_event_id,
                    origin=origin,
                    idempotency_key=idempotency_key,
                    observed_at=datetime.now(UTC).isoformat(),
                    facts={
                        "source_event_id": source_event_id,
                        "game_date": game.game_date,
                        "start_time_utc": game.start_time_utc,
                        "season": str(game.season),
                        "game_type": str(game.game_type),
                        "home_abbrev": game.home_abbrev,
                        "away_abbrev": game.away_abbrev,
                        "game_state": game.game_state,
                        "game_schedule_state": game.game_schedule_state,
                        "reason": reason,
                    },
                    basis=f"Официальное NHL schedule; автоматическая регистрация требует проверки: {reason}",
                )
                candidate = review_queue._observe_connection(connection, observation)
                candidate_id = candidate.id
            return NHLBootstrapItem(source_event_id, status, reason, project_event_id, candidate_id)

        for game, source_event_id, relation_key in zip(games, game_ids, relation_keys, strict=True):
            if source_event_id in duplicate_ids or relation_key in duplicated_relations:
                items.append(
                    make_item(game, source_event_id, "needs_review", "duplicate_in_schedule_batch")
                )
                continue
            scheduled_at = _scheduled_at(game.start_time_utc)
            if scheduled_at is None:
                items.append(
                    make_item(game, source_event_id, "needs_review", "exact_utc_time_required")
                )
                continue
            if tournament_id is None or team_scope is None:
                items.append(make_item(game, source_event_id, "needs_review", tournament_state))
                continue
            scheduled_tournament_id, scheduled_tournament_state = _confirmed_entity_id(
                connection,
                source="nhl_web_api",
                kind="tournament",
                scope={"sport": "ice_hockey"},
                value_kind="name",
                raw_value="nhl",
                at_utc=scheduled_at,
            )
            if scheduled_tournament_id != tournament_id:
                reason = (
                    scheduled_tournament_state
                    if scheduled_tournament_id is None
                    else "tournament_designation_mismatch"
                )
                items.append(make_item(game, source_event_id, "needs_review", reason))
                continue
            home_team_id, home_state = _confirmed_entity_id(
                connection,
                source="nhl_web_api",
                kind="team",
                scope=team_scope,
                value_kind="name",
                raw_value=game.home_abbrev,
                at_utc=scheduled_at,
            )
            away_team_id, away_state = _confirmed_entity_id(
                connection,
                source="nhl_web_api",
                kind="team",
                scope=team_scope,
                value_kind="name",
                raw_value=game.away_abbrev,
                at_utc=scheduled_at,
            )
            if home_team_id is None or away_team_id is None:
                reason = home_state if home_team_id is None else away_state
                items.append(make_item(game, source_event_id, "needs_review", reason))
                continue
            if home_team_id == away_team_id:
                items.append(
                    make_item(game, source_event_id, "needs_review", "same_team_on_both_sides")
                )
                continue

            normalized_source_id = _normalize(source_event_id, "external_id")
            source_rows = connection.execute(
                "SELECT id,entity_id,state,scope_json,valid_from,valid_until FROM designations WHERE source=? "
                "AND kind='event' AND value_kind='external_id' AND normalized_value=? ORDER BY id",
                (_SOURCE, normalized_source_id),
            ).fetchall()
            if source_rows:
                source_reason = "source_id_conflict"
                if len(source_rows) == 1 and source_rows[0]["state"] == "confirmed":
                    designation = source_rows[0]
                    existing_id = designation["entity_id"]
                    valid_from = _canonical_utc(designation["valid_from"])
                    valid_until = _canonical_utc(designation["valid_until"])
                    if (valid_from is not None and valid_from > scheduled_at) or (
                        valid_until is not None and scheduled_at >= valid_until
                    ):
                        source_reason = "source_designation_not_valid_at_event_time"
                    event_entity = connection.execute(
                        "SELECT kind,sport,state FROM entities WHERE id=?", (existing_id,)
                    ).fetchone()
                    if (
                        event_entity is None
                        or event_entity["kind"] != "event"
                        or event_entity["sport"] != "ice_hockey"
                        or event_entity["state"] != "active"
                    ):
                        source_reason = "source_entity_not_active"
                    designation_conflicts = connection.execute(
                        "SELECT state,valid_from,valid_until FROM designation_conflicts WHERE "
                        "(designation_id=? OR peer_designation_id=?) AND state<>'dismissed'",
                        (designation["id"], designation["id"]),
                    ).fetchall()
                    active_conflicts = [
                        conflict
                        for conflict in designation_conflicts
                        if (
                            _canonical_utc(conflict["valid_from"]) is None
                            or _canonical_utc(conflict["valid_from"]) <= scheduled_at
                        )
                        and (
                            _canonical_utc(conflict["valid_until"]) is None
                            or scheduled_at < _canonical_utc(conflict["valid_until"])
                        )
                    ]
                    if active_conflicts:
                        source_reason = "source_designation_has_conflict"
                    if source_reason == "source_id_conflict":
                        relation = connection.execute(
                            "SELECT * FROM event_relations WHERE event_id=?", (existing_id,)
                        ).fetchone()
                        if (
                            relation is not None
                            and relation["tournament_id"] == tournament_id
                            and relation["home_team_id"] == home_team_id
                            and relation["away_team_id"] == away_team_id
                            and relation["scheduled_at"] == scheduled_at
                        ):
                            items.append(
                                NHLBootstrapItem(
                                    source_event_id,
                                    "already_present",
                                    "source_relation_matches",
                                    existing_id,
                                )
                            )
                            continue
                items.append(make_item(game, source_event_id, "needs_review", source_reason))
                continue

            matching_relations = connection.execute(
                "SELECT event_id FROM event_relations WHERE tournament_id=? "
                "AND ((home_team_id=? AND away_team_id=?) OR "
                "(home_team_id=? AND away_team_id=?)) AND scheduled_at=?",
                (
                    tournament_id,
                    home_team_id,
                    away_team_id,
                    away_team_id,
                    home_team_id,
                    scheduled_at,
                ),
            ).fetchall()
            if matching_relations:
                items.append(make_item(game, source_event_id, "needs_review", "relation_conflict"))
                continue

            if dry_run:
                items.append(
                    NHLBootstrapItem(
                        source_event_id, "planned", "trusted_schedule_and_teams_confirmed"
                    )
                )
                continue

            event = registry._seed_entity_in_transaction(
                connection,
                "event",
                f"{game.home_abbrev} vs {game.away_abbrev} ({scheduled_at})",
                "ice_hockey",
                _SEED_KEY,
                stable_key=source_event_id,
            )
            registry._insert_designation(
                connection,
                entity_id=event.id,
                source=_SOURCE,
                kind="event",
                scope=team_scope,
                value_kind="external_id",
                raw_value=source_event_id,
                state="confirmed",
                valid_from=None,
                valid_until=None,
                seed_key=_SEED_KEY,
            )
            now = _timestamp()
            connection.execute(
                "INSERT INTO event_relations VALUES (?,?,?,?,?,1,?)",
                (event.id, tournament_id, home_team_id, away_team_id, scheduled_at, now),
            )
            connection.execute(
                "INSERT INTO event_relation_audit VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    str(uuid4()),
                    event.id,
                    _ACTOR,
                    f"Создано по официальному NHL schedule, game ID {source_event_id}",
                    0,
                    1,
                    None,
                    tournament_id,
                    None,
                    home_team_id,
                    None,
                    away_team_id,
                    None,
                    scheduled_at,
                    now,
                ),
            )
            items.append(
                NHLBootstrapItem(
                    source_event_id, "created", "trusted_schedule_and_teams_confirmed", event.id
                )
            )
    return NHLBootstrapReport(tuple(items), dry_run)
