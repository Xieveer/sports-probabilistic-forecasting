from datetime import UTC, datetime, timedelta

from sports_forecast.identity.derived_event_matching import (
    DerivedEventCandidate,
    match_derived_events,
)


START = datetime(2026, 10, 11, 21, tzinfo=UTC)


def _candidate(
    key: str,
    *,
    minute: int = 0,
    tournament: str | None = "nhl",
    home: str | None = "home",
    away: str | None = "away",
    reason: str | None = None,
) -> DerivedEventCandidate:
    return DerivedEventCandidate(
        key=key,
        tournament_id=tournament,
        home_team_id=home,
        away_team_id=away,
        scheduled_at=START + timedelta(minutes=minute),
        unresolved_reason=reason,
    )


def test_matches_six_provider_events_with_ten_minute_clock_offset() -> None:
    calendar = [_candidate(f"game-{i}", minute=i * 60) for i in range(6)]
    provider = [_candidate(f"odds-{i}", minute=i * 60 + 10) for i in range(6)]

    result = match_derived_events(calendar, provider)

    assert result.provider_to_calendar == {f"odds-{i}": f"game-{i}" for i in range(6)}
    assert result.provider_reasons == {}


def test_time_tolerance_is_inclusive_at_fifteen_minutes() -> None:
    result = match_derived_events([_candidate("game")], [_candidate("odds", minute=15)])

    assert result.provider_to_calendar == {"odds": "game"}


def test_time_tolerance_rejects_sixteen_minutes() -> None:
    result = match_derived_events([_candidate("game")], [_candidate("odds", minute=16)])

    assert result.provider_to_calendar == {}
    assert result.provider_reasons["odds"] == "outside_time_tolerance"


def test_duplicate_provider_candidates_are_ambiguous() -> None:
    result = match_derived_events(
        [_candidate("game")],
        [_candidate("odds-a"), _candidate("odds-b")],
    )

    assert result.provider_to_calendar == {}
    assert result.provider_reasons == {
        "odds-a": "ambiguous",
        "odds-b": "ambiguous",
    }


def test_calendar_candidate_must_also_have_one_provider_match() -> None:
    result = match_derived_events(
        [_candidate("game-a", minute=-5), _candidate("game-b", minute=5)],
        [_candidate("odds")],
    )

    assert result.provider_to_calendar == {}
    assert result.provider_reasons["odds"] == "ambiguous"


def test_home_away_and_tournament_are_part_of_identity() -> None:
    result = match_derived_events(
        [_candidate("game")],
        [
            _candidate("reversed", home="away", away="home"),
            _candidate("other-league", tournament="other"),
        ],
    )

    assert result.provider_to_calendar == {}
    assert set(result.provider_reasons.values()) == {"no_matching_event"}


def test_unresolved_source_alias_has_explanatory_reason() -> None:
    result = match_derived_events(
        [_candidate("game")],
        [_candidate("odds", home=None, reason="unconfirmed_team_alias")],
    )

    assert result.provider_to_calendar == {}
    assert result.provider_reasons["odds"] == "unconfirmed_team_alias"


def test_unresolved_candidates_do_not_match_or_poison_confirmed_pair() -> None:
    result = match_derived_events(
        [_candidate("calendar-good"), _candidate("calendar-unknown", reason="unknown_calendar")],
        [_candidate("odds-good"), _candidate("odds-unknown", reason="unknown_provider")],
    )

    assert result.provider_to_calendar == {"odds-good": "calendar-good"}
    assert result.provider_reasons["odds-unknown"] == "unknown_provider"
