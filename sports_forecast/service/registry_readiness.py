"""Разрешение участников календаря по закреплённому серверному снимку."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC
from typing import Literal

from sqlalchemy.orm import Session

from sports_forecast.identity.installation import InstalledRegistryReader
from sports_forecast.service.db.models import CanonicalEvent


def pinned_participant_resolver(
    reader: InstalledRegistryReader,
    session: Session,
    event: CanonicalEvent,
) -> Callable[[str], str | None]:
    """Подготовить resolver без запросов БД во время сравнения имён."""
    try:
        mapping = reader.get_event_mapping(int(event.id), session)
    except KeyError:
        mapping = None
    project = next(
        (
            item
            for item in reader.event_snapshot.event_snapshot.events
            if mapping is not None and item.id == mapping.project_event_id
        ),
        None,
    )
    if mapping is None or mapping.status != "resolved" or project is None:
        return lambda _raw: None
    scheduled_at = event.scheduled_at
    at = (
        scheduled_at.replace(tzinfo=UTC)
        if scheduled_at.tzinfo is None
        else scheduled_at.astimezone(UTC)
    ).isoformat()
    sources: list[tuple[str, Literal["name", "external_id"]]] = [
        (event.source, "name"),
        (event.source, "external_id"),
    ]
    if event.tournament == "nhl":
        sources.extend((("nhl_web_api", "name"), ("nhl_api", "external_id")))
    sources = list(dict.fromkeys(sources))

    def resolve(raw: str) -> str | None:
        ids: set[str] = set()
        for source, value_kind in sources:
            result = reader.resolve_designation(
                source=source,
                kind="team",
                scope={"sport": project.sport, "tournament": project.tournament_id},
                value_kind=value_kind,
                raw_value=raw,
                at=at,
            )
            if result.status == "resolved" and result.entity_id is not None:
                ids.add(result.entity_id)
        return next(iter(ids)) if len(ids) == 1 else None

    return resolve
