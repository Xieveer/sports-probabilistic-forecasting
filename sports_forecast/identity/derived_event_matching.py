"""Однозначное вычисляемое сопоставление событий по подтверждённым ID."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta


DEFAULT_START_TOLERANCE = timedelta(minutes=15)


@dataclass(frozen=True, slots=True)
class DerivedEventCandidate:
    """Событие с уже разрешёнными по источнику ID турнира и команд."""

    key: str
    tournament_id: str | None
    home_team_id: str | None
    away_team_id: str | None
    scheduled_at: datetime | None
    unresolved_reason: str | None = None


@dataclass(frozen=True, slots=True)
class DerivedEventMatchResult:
    """Уникальные пары provider → calendar и причины неприсоединения."""

    provider_to_calendar: dict[str, str]
    provider_reasons: dict[str, str]


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _valid_identity(candidate: DerivedEventCandidate) -> bool:
    return bool(
        candidate.tournament_id
        and candidate.home_team_id
        and candidate.away_team_id
        and candidate.home_team_id != candidate.away_team_id
    )


def _validate_unique_keys(candidates: Sequence[DerivedEventCandidate], side: str) -> None:
    keys = [item.key for item in candidates]
    if len(keys) != len(set(keys)):
        raise ValueError(f"Ключи {side} событий должны быть уникальны")


def match_derived_events(
    calendar_events: Sequence[DerivedEventCandidate],
    provider_events: Sequence[DerivedEventCandidate],
    *,
    tolerance: timedelta = DEFAULT_START_TOLERANCE,
) -> DerivedEventMatchResult:
    """Вернуть только взаимно-уникальные пары с совпадающими сторонами и временем.

    Кандидаты для обоих аргументов должны покрывать одно полное окно календаря и
    ответа источника. Обозначения перед вызовом разрешаются reader-ом конкретного
    источника; неизвестные обозначения передаются с ``unresolved_reason``.
    """
    if tolerance < timedelta(0):
        raise ValueError("Допуск времени не может быть отрицательным")
    _validate_unique_keys(calendar_events, "календаря")
    _validate_unique_keys(provider_events, "источника")

    provider_edges: dict[str, set[str]] = defaultdict(set)
    calendar_edges: dict[str, set[str]] = defaultdict(set)
    calendar_identity_index: dict[tuple[str, str, str], list[DerivedEventCandidate]] = defaultdict(
        list
    )
    for event in calendar_events:
        if _valid_identity(event) and event.unresolved_reason is None:
            identity = (
                event.tournament_id or "",
                event.home_team_id or "",
                event.away_team_id or "",
            )
            calendar_identity_index[identity].append(event)

    same_identity_exists: dict[str, bool] = {}
    for provider in provider_events:
        if provider.unresolved_reason is not None or not _valid_identity(provider):
            continue
        identity = (
            provider.tournament_id or "",
            provider.home_team_id or "",
            provider.away_team_id or "",
        )
        possible = calendar_identity_index.get(identity, [])
        same_identity_exists[provider.key] = bool(possible)
        if provider.scheduled_at is None:
            continue
        provider_time = _utc(provider.scheduled_at)
        for calendar in possible:
            if calendar.scheduled_at is None:
                continue
            if abs(provider_time - _utc(calendar.scheduled_at)) <= tolerance:
                provider_edges[provider.key].add(calendar.key)
                calendar_edges[calendar.key].add(provider.key)

    matches: dict[str, str] = {}
    reasons: dict[str, str] = {}
    for provider in provider_events:
        if provider.unresolved_reason:
            reasons[provider.key] = provider.unresolved_reason
            continue
        if not _valid_identity(provider):
            reasons[provider.key] = "unconfirmed_source_designation"
            continue
        if provider.scheduled_at is None:
            reasons[provider.key] = "missing_start_time"
            continue
        calendar_keys = provider_edges.get(provider.key, set())
        if len(calendar_keys) == 1:
            calendar_key = next(iter(calendar_keys))
            if len(calendar_edges[calendar_key]) == 1:
                matches[provider.key] = calendar_key
                continue
            reasons[provider.key] = "ambiguous"
            continue
        if len(calendar_keys) > 1:
            reasons[provider.key] = "ambiguous"
            continue
        reasons[provider.key] = (
            "outside_time_tolerance"
            if same_identity_exists.get(provider.key, False)
            else "no_matching_event"
        )

    return DerivedEventMatchResult(matches, reasons)


__all__ = [
    "DEFAULT_START_TOLERANCE",
    "DerivedEventCandidate",
    "DerivedEventMatchResult",
    "match_derived_events",
]
