"""Загрузка турнирных политик для вычисляемой event readiness."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from sports_forecast.config.loaders import PROJECT_ROOT


_TOURNAMENT_PATTERN = re.compile(r"^[a-z0-9_-]{1,64}$")


@lru_cache(maxsize=32)
def load_readiness_policy(tournament: str) -> dict[str, Any] | None:
    """Загрузить policy по allowlisted tournament slug; неизвестный slug возвращает None."""
    if not _TOURNAMENT_PATTERN.fullmatch(tournament):
        return None
    policy_path = Path(PROJECT_ROOT) / "conf" / "readiness" / f"{tournament}.yaml"
    if not policy_path.is_file():
        return None
    raw = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"Некорректная readiness policy для {tournament}")
    return raw
