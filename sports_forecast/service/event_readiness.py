"""Чистые правила независимой готовности календаря, прогноза и odds."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from sports_forecast.data.providers.odds.team_name_registry import (
    TeamNameRegistry,
    load_nhl_team_name_registry,
    normalize_team_key,
)
from sports_forecast.service.db.models import CanonicalEvent, OddsObservation, Prediction


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def evaluate_event_readiness(
    event: CanonicalEvent,
    predictions: Sequence[Prediction],
    odds: Sequence[OddsObservation],
    policy: dict[str, Any] | None,
    now: datetime,
) -> dict[str, Any]:
    """Вычислить состояния по persisted timestamps, не выводя сбои из отсутствия строк."""
    reference = _utc(now)
    if policy is None:
        return {
            "calendar_readiness": "current" if event.status == "scheduled" else event.status,
            "prediction_readiness": _component("unavailable", "policy_missing"),
            "odds_readiness": _component("missing", "policy_missing"),
            "readiness": {
                "status": "waiting",
                "reason_code": "policy_missing",
                "deadline_at": None,
                "computed_at": reference,
            },
        }

    deadline = _utc(event.scheduled_at) - timedelta(hours=int(policy["preparation_deadline_hours"]))
    prediction_policy = policy.get("prediction_markets", [])
    odds_policy = policy.get("odds_markets", [])
    prediction = _evaluate_markets(
        prediction_policy,
        predictions,
        now=reference,
        deadline=deadline,
        freshness=timedelta(hours=int(policy["prediction_freshness_hours"])),
        market_getter=lambda item: (item.market, item.market_spec),
        timestamp_getter=lambda item: item.prediction_ts,
        failed_getter=lambda item: item.status == "error",
        required_getter=lambda item: (str(item["market"]), str(item["market_spec"])),
        label=lambda pair: f"{pair[0]}:{pair[1]}",
        force_stale_getter=lambda item: item.status == "stale",
    )
    odds_readiness = _evaluate_markets(
        odds_policy,
        odds,
        now=reference,
        deadline=deadline,
        freshness=timedelta(hours=int(policy["odds_freshness_hours"])),
        market_getter=lambda item: (item.market, item.market_spec, item.bookmaker),
        timestamp_getter=lambda item: item.observed_at,
        failed_getter=lambda _item: False,
        required_getter=lambda item: (
            str(item["market"]),
            str(item["market_spec"]),
            str(item["bookmaker"]),
        ),
        label=lambda pair: ":".join(pair),
        pending_status="missing",
        unavailable_status="missing",
        stale_status="stale",
        force_stale_getter=lambda item: (
            _utc(item.event_scheduled_at) != _utc(event.scheduled_at)
            or item.event_home_participant != event.home_participant
            or item.event_away_participant != event.away_participant
        ),
    )

    required_prediction_keys = {
        (str(item["market"]), str(item["market_spec"])) for item in prediction_policy
    }
    identity_changed = any(
        (item.market, item.market_spec) in required_prediction_keys
        and _prediction_event_identity_changed(event, item)
        for item in predictions
    )
    calendar_status = "current" if event.status == "scheduled" else event.status
    if identity_changed and event.status == "scheduled":
        calendar_status = "changed"
        if prediction["status"] not in {"failed", "unavailable"}:
            prediction["status"] = "partial"
            prediction["reason_code"] = "event_identity_changed"
    component_statuses = (prediction["status"], odds_readiness["status"])
    if "failed" in component_statuses:
        aggregate, reason = "error", "required_component_failed"
    elif identity_changed:
        aggregate, reason = "partial", "event_identity_changed"
    elif event.status == "scheduled" and all(status == "ready" for status in component_statuses):
        aggregate, reason = "ready", "all_required_components_ready"
    elif any(status in {"ready", "partial", "stale"} for status in component_statuses):
        aggregate, reason = "partial", "components_incomplete"
    elif reference < deadline:
        aggregate, reason = "waiting", "preparation_deadline_not_reached"
    else:
        aggregate, reason = "partial", "required_data_missing_after_deadline"

    return {
        "calendar_readiness": calendar_status,
        "prediction_readiness": prediction,
        "odds_readiness": odds_readiness,
        "readiness": {
            "status": aggregate,
            "reason_code": reason,
            "deadline_at": deadline,
            "computed_at": reference,
        },
    }


def _prediction_event_identity_changed(event: CanonicalEvent, prediction: Prediction) -> bool:
    """Распознать перенос или замену участников без сравнения чужих snapshot IDs."""
    if prediction.match_datetime is not None and _utc(prediction.match_datetime) != _utc(
        event.scheduled_at
    ):
        return True
    if (
        prediction.home_player
        and event.home_participant
        and _participant_key(event.tournament, prediction.home_player)
        != _participant_key(event.tournament, event.home_participant)
    ):
        return True
    if prediction.away_player and event.away_participant:
        return _participant_key(event.tournament, prediction.away_player) != _participant_key(
            event.tournament, event.away_participant
        )
    return False


def _participant_key(tournament: str, participant: str) -> str:
    registry: TeamNameRegistry = (
        load_nhl_team_name_registry() if tournament == "nhl" else TeamNameRegistry()
    )
    return registry.resolve(participant) or normalize_team_key(participant)


def _component(status: str, reason_code: str) -> dict[str, Any]:
    return {
        "status": status,
        "reason_code": reason_code,
        "last_success_at": None,
        "required": [],
        "available": [],
    }


def _evaluate_markets(
    required: Sequence[dict[str, Any]],
    observations: Sequence[Any],
    *,
    now: datetime,
    deadline: datetime,
    freshness: timedelta,
    market_getter: Any,
    timestamp_getter: Any,
    failed_getter: Any,
    required_getter: Any,
    label: Any,
    pending_status: str = "pending",
    unavailable_status: str = "unavailable",
    stale_status: str = "partial",
    force_stale_getter: Any = lambda _item: False,
) -> dict[str, Any]:
    keys = [required_getter(item) for item in required]
    if not keys:
        return _component("unavailable", "policy_has_no_required_markets")
    found: dict[tuple[str, ...], Any] = {}
    for item in observations:
        key = market_getter(item)
        if key not in keys:
            continue
        current = found.get(key)
        if current is None or _utc(timestamp_getter(item)) > _utc(timestamp_getter(current)):
            found[key] = item
    failed = any(failed_getter(item) for item in found.values())
    last_successes = [
        _utc(timestamp_getter(item))
        for item in observations
        if market_getter(item) in keys and not failed_getter(item)
    ]
    last_success = max(last_successes) if last_successes else None
    available = [
        key
        for key, item in found.items()
        if (
            now - _utc(timestamp_getter(item)) <= freshness
            and not force_stale_getter(item)
            and not failed_getter(item)
        )
    ]
    stale = [key for key in found if key not in available]
    if failed:
        status, reason = "failed", "required_market_failed"
    elif len(available) == len(keys):
        status, reason = "ready", "required_markets_fresh"
    elif available or stale:
        status = "partial" if available else stale_status
        reason = "required_market_missing_or_stale"
    elif now < deadline:
        status, reason = pending_status, "before_preparation_deadline"
    else:
        status, reason = unavailable_status, "required_market_missing_after_deadline"
    return {
        "status": status,
        "reason_code": reason,
        "last_success_at": last_success,
        "required": [label(key) for key in keys],
        "available": [label(key) for key in available],
    }


def decode_odds_values(observation: OddsObservation) -> dict[str, float]:
    """Разобрать compact normalized odds values; invalid persisted JSON is ignored by caller."""
    decoded = json.loads(observation.values_json)
    if not isinstance(decoded, dict):
        raise ValueError("odds observation values must be a JSON object")
    return {str(key): float(value) for key, value in decoded.items()}
