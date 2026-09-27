"""Проверка host evidence перед освобождением зависшего Data Cycle."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True)
class HostStopEvidence:
    """Проверяемый результат остановки systemd-владельца и его Compose containers."""

    run_id: str
    owner_id: str
    owner_generation: int
    systemd_active_state: str
    systemd_invocation_id: str
    systemd_main_pid: int
    discovered_container_ids: tuple[str, ...]
    stopped_container_ids: tuple[str, ...]
    remaining_container_ids: tuple[str, ...]
    container_run_ids: tuple[str, ...]
    container_generations: tuple[int, ...]
    container_owner_ids: tuple[str, ...]
    inventory_complete: bool
    verified_at: datetime

    @classmethod
    def from_json(cls, raw: str) -> HostStopEvidence:
        """Разобрать evidence JSON, принимая только известные поля и типы."""
        value: Any = json.loads(raw)
        required = {
            "run_id",
            "owner_id",
            "owner_generation",
            "systemd_active_state",
            "systemd_invocation_id",
            "systemd_main_pid",
            "discovered_container_ids",
            "stopped_container_ids",
            "remaining_container_ids",
            "container_run_ids",
            "container_generations",
            "container_owner_ids",
            "inventory_complete",
            "verified_at",
        }
        if not isinstance(value, dict) or set(value) != required:
            raise ValueError("Некорректная структура host recovery evidence")
        sequence_fields = (
            "discovered_container_ids",
            "stopped_container_ids",
            "remaining_container_ids",
            "container_run_ids",
            "container_generations",
            "container_owner_ids",
        )
        if any(not isinstance(value[key], list) for key in sequence_fields):
            raise ValueError("Некорректный container inventory в host evidence")
        try:
            verified_at = datetime.fromisoformat(value["verified_at"].replace("Z", "+00:00"))
        except (AttributeError, ValueError) as exc:
            raise ValueError("Некорректное время host evidence") from exc
        if verified_at.tzinfo is None:
            raise ValueError("Время host evidence должно содержать timezone")
        return cls(
            run_id=_string(value, "run_id"),
            owner_id=_string(value, "owner_id"),
            owner_generation=_positive_integer(value, "owner_generation"),
            systemd_active_state=_string(value, "systemd_active_state"),
            systemd_invocation_id=_string(value, "systemd_invocation_id"),
            systemd_main_pid=_nonnegative_integer(value, "systemd_main_pid"),
            discovered_container_ids=tuple(
                _string_item(item) for item in value["discovered_container_ids"]
            ),
            stopped_container_ids=tuple(
                _string_item(item) for item in value["stopped_container_ids"]
            ),
            remaining_container_ids=tuple(
                _string_item(item) for item in value["remaining_container_ids"]
            ),
            container_run_ids=tuple(_string_item(item) for item in value["container_run_ids"]),
            container_generations=tuple(
                _positive_integer_item(item) for item in value["container_generations"]
            ),
            container_owner_ids=tuple(_string_item(item) for item in value["container_owner_ids"]),
            inventory_complete=value["inventory_complete"] is True,
            verified_at=verified_at.astimezone(UTC),
        )

    def validate_for(self, *, run_id: str, owner_id: str, owner_generation: int) -> int:
        """Отклонить неполный inventory, чужой owner или любой оставшийся container."""
        if (
            self.run_id != run_id
            or self.owner_id != owner_id
            or self.owner_generation != owner_generation
            or self.systemd_invocation_id != owner_id
        ):
            raise ValueError("Host evidence относится к другому executor owner")
        if self.systemd_active_state not in {"inactive", "failed"} or self.systemd_main_pid != 0:
            raise ValueError("Host не подтвердил остановку systemd process")
        if not self.inventory_complete:
            raise ValueError("Host не подтвердил полную остановку executor")
        if self.remaining_container_ids:
            raise ValueError("Run containers ещё работают")
        if len(set(self.discovered_container_ids)) != len(self.discovered_container_ids):
            raise ValueError("Host evidence содержит повторные container IDs")
        if set(self.discovered_container_ids) != set(self.stopped_container_ids):
            raise ValueError("Не все обнаруженные run containers остановлены")
        if len(set(self.stopped_container_ids)) != len(self.stopped_container_ids):
            raise ValueError("Host evidence содержит повторные stopped container IDs")
        count = len(self.discovered_container_ids)
        if len(self.container_run_ids) != count or any(
            container_run_id != run_id for container_run_id in self.container_run_ids
        ):
            raise ValueError("Container inventory не подтверждает run identity")
        if len(self.container_generations) != count or any(
            generation != owner_generation for generation in self.container_generations
        ):
            raise ValueError("Container inventory не подтверждает owner generation")
        if len(self.container_owner_ids) != count or any(
            container_owner_id != owner_id for container_owner_id in self.container_owner_ids
        ):
            raise ValueError("Container inventory не подтверждает systemd owner")
        if any(
            re.fullmatch(r"[0-9a-f]{12,64}", item) is None for item in self.stopped_container_ids
        ):
            raise ValueError("Host evidence содержит некорректный container ID")
        return count


def _string(value: dict[str, Any], field: str) -> str:
    item = value[field]
    if not isinstance(item, str) or not item:
        raise ValueError("Некорректное поле host recovery evidence")
    return item


def _string_item(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("Некорректный container inventory в host evidence")
    return value


def _positive_integer(value: dict[str, Any], field: str) -> int:
    return _positive_integer_item(value[field])


def _nonnegative_integer(value: dict[str, Any], field: str) -> int:
    item = value[field]
    if not isinstance(item, int) or isinstance(item, bool) or item < 0:
        raise ValueError("Некорректное значение systemd process в host evidence")
    return item


def _positive_integer_item(value: Any) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError("Некорректная generation в host evidence")
    return value
