"""Проверки готовности события по закреплённым project ID."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast

from sqlalchemy.orm import Session

from sports_forecast.identity.installation import InstalledRegistryReader
from sports_forecast.identity.registry import Resolution
from sports_forecast.service.db.models import CanonicalEvent, Prediction
from sports_forecast.service.event_readiness import evaluate_event_readiness
from sports_forecast.service.registry_readiness import pinned_participant_resolver


def test_strict_readiness_uses_confirmed_project_team_ids() -> None:
    """Два имени одной команды не делают прогноз устаревшим; новая команда делает."""
    event = SimpleNamespace(
        id=1,
        sport="ice_hockey",
        tournament="nhl",
        source="nhl_web_api",
        status="scheduled",
        scheduled_at=datetime(2026, 10, 20, 18, tzinfo=UTC),
        home_participant="NYR",
        away_participant="PIT",
    )
    prediction = SimpleNamespace(
        market="winner",
        market_spec="winner_withOT",
        prediction_ts=datetime(2026, 10, 19, 18, tzinfo=UTC),
        match_datetime=event.scheduled_at,
        home_player="New York Rangers",
        away_player="PIT",
        status="ok",
    )
    policy = {
        "preparation_deadline_hours": 4,
        "prediction_freshness_hours": 48,
        "odds_freshness_hours": 24,
        "prediction_markets": [{"market": "winner", "market_spec": "winner_withOT"}],
        "odds_markets": [],
    }
    ids = {"NYR": "home-id", "New York Rangers": "home-id", "PIT": "away-id"}

    def readiness() -> dict[str, Any]:
        return evaluate_event_readiness(
            cast(CanonicalEvent, event),
            [cast(Prediction, prediction)],
            [],
            policy,
            datetime(2026, 10, 20, 12, tzinfo=UTC),
            participant_resolver=ids.get,
        )

    ready = readiness()
    assert ready["calendar_readiness"] == "current"
    assert ready["prediction_readiness"]["status"] == "ready"

    ids["New York Rangers"] = "different-id"
    changed = readiness()
    assert changed["calendar_readiness"] == "changed"
    assert changed["prediction_readiness"]["reason_code"] == "event_identity_changed"


def test_pinned_participant_resolver_reads_only_snapshot_designations() -> None:
    """Вызов resolver после подготовки не открывает БД и не использует YAML."""
    event = SimpleNamespace(
        id=1,
        sport="ice_hockey",
        tournament="nhl",
        source="nhl_web_api",
        scheduled_at=datetime(2026, 10, 20, 18, tzinfo=UTC),
    )
    project = SimpleNamespace(id="event-id", sport="ice_hockey", tournament_id="league-id")
    calls: list[tuple[str, str, str]] = []

    class FakeReader:
        event_snapshot = SimpleNamespace(event_snapshot=SimpleNamespace(events=(project,)))

        def get_event_mapping(self, event_id: int, session: Session) -> SimpleNamespace:
            assert event_id == 1
            return SimpleNamespace(status="resolved", project_event_id="event-id")

        def resolve_designation(self, **kwargs: object) -> Resolution:
            calls.append(
                (str(kwargs["source"]), str(kwargs["value_kind"]), str(kwargs["raw_value"]))
            )
            if kwargs["raw_value"] in {"NYR", "New York Rangers"}:
                return Resolution("resolved", "home-id", "fixture")
            return Resolution("unresolved", None, "fixture")

    resolver = pinned_participant_resolver(
        cast(InstalledRegistryReader, FakeReader()),
        cast(Session, object()),
        cast(CanonicalEvent, event),
    )
    assert resolver("NYR") == "home-id"
    assert resolver("New York Rangers") == "home-id"
    assert resolver("UNKNOWN") is None
    assert calls
