"""Внутренний tournament-neutral контракт состояния уведомлений."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sports_forecast.service.db.models import NotificationCycle
from sports_forecast.service.db.repository import NotificationStateRepository


@dataclass(frozen=True)
class QuoteSnapshot:
    """Нормализованная линия одного матча из batch-ответа provider-а."""

    match_id: str
    starts_at: datetime
    line: Mapping[str, float] | None


@dataclass(frozen=True)
class QuoteChange:
    """Предметное изменение валидной линии."""

    match_id: str
    kind: Literal["new", "changed"]
    line: Mapping[str, float]


@dataclass(frozen=True)
class NotificationPlan:
    """Результат сравнения снимка с персистентным состоянием."""

    status: Literal["no_relevant_matches", "no_change", "notification_created"]
    changes: tuple[QuoteChange, ...] = ()
    cycle_id: int | None = None


class NotificationStateService:
    """Сравнивает линии и создаёт одно агрегированное событие на logical cycle."""

    def __init__(self, repository: NotificationStateRepository) -> None:
        self.repository = repository

    def record_baseline(
        self,
        profile_id: str,
        snapshots: list[QuoteSnapshot],
        now: datetime,
    ) -> None:
        """Записать baseline валидных линий без создания пользовательского события."""
        for snapshot in snapshots:
            line_json = _line_json(snapshot.line)
            if snapshot.starts_at <= now or line_json is None:
                continue
            self.repository.save_line(profile_id, snapshot.match_id, line_json)

    def plan_poll(
        self,
        profile_id: str,
        logical_cycle: str,
        snapshots: list[QuoteSnapshot],
        now: datetime,
    ) -> NotificationPlan:
        """Создать delta либо вернуть отсутствие релевантных матчей/изменений."""
        existing_cycle = self.repository.get_cycle(profile_id, logical_cycle)
        if existing_cycle is not None:
            return _plan_from_cycle(existing_cycle)

        relevant_count = 0
        changes: list[QuoteChange] = []
        for snapshot in snapshots:
            if snapshot.starts_at <= now:
                continue
            relevant_count += 1
            line_json = _line_json(snapshot.line)
            if line_json is None:
                continue
            previous = self.repository.get_line(profile_id, snapshot.match_id)
            if previous is None:
                changes.append(QuoteChange(snapshot.match_id, "new", dict(snapshot.line)))
            elif previous.line_json != line_json:
                changes.append(QuoteChange(snapshot.match_id, "changed", dict(snapshot.line)))
            self.repository.save_line(profile_id, snapshot.match_id, line_json)

        if relevant_count == 0:
            return NotificationPlan(status="no_relevant_matches")
        if not changes:
            return NotificationPlan(status="no_change")

        changes_json = _changes_json(changes)
        cycle = self.repository.create_cycle(profile_id, logical_cycle, changes_json)
        return NotificationPlan(
            status="notification_created",
            changes=tuple(changes),
            cycle_id=cycle.id,
        )


def _line_json(line: Mapping[str, float] | None) -> str | None:
    """Вернуть каноническое JSON-представление полной валидной линии."""
    if not line or any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 1
        for value in line.values()
    ):
        return None
    return json.dumps(dict(line), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _changes_json(changes: list[QuoteChange]) -> str:
    """Сериализовать предметную delta для одного агрегированного события."""
    return json.dumps(
        [
            {"match_id": change.match_id, "kind": change.kind, "line": dict(change.line)}
            for change in changes
        ],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _plan_from_cycle(cycle: NotificationCycle) -> NotificationPlan:
    """Восстановить уже созданное событие для retry того же logical cycle."""
    changes = tuple(
        QuoteChange(
            match_id=item["match_id"],
            kind=item["kind"],
            line=item["line"],
        )
        for item in json.loads(cycle.changes_json)
    )
    return NotificationPlan(
        status="notification_created",
        changes=changes,
        cycle_id=cycle.id,
    )
