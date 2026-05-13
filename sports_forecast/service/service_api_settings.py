"""
Загрузка узла ``conf/service_api.yaml`` для read-only API и бота.

Пороги можно переопределить переменными окружения без правки файла.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from sports_forecast.betting.edge_decision import EdgeDecisionParams


def _project_root() -> Path:
    """Корень репозитория (родитель каталога ``sports_forecast``)."""
    return Path(__file__).resolve().parents[2]


def _parse_float(raw: str | None, *, fallback: float) -> float:
    if raw is None or not str(raw).strip():
        return fallback
    try:
        return float(raw)
    except ValueError:
        return fallback


@lru_cache(maxsize=1)
def load_edge_decision_params() -> EdgeDecisionParams:
    """Прочитать ``conf/service_api.yaml`` и применить env-переопределения.

    Env (опционально):

    * ``SERVICE_API_EDGE_THRESHOLD`` — float, порог edge ``p_model - 1/odds``.
    * ``SERVICE_API_MIN_ODDS`` — float, минимальный допустимый decimal.

    Returns:
        :class:`EdgeDecisionParams` с дефолтами, если файл отсутствует или пуст.
    """
    path = _project_root() / "conf" / "service_api.yaml"
    edge_default = 0.03
    min_odds_default = 1.01
    if path.is_file():
        raw: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        edge_default = float(raw.get("edge_threshold", edge_default))
        min_odds_default = float(raw.get("min_odds", min_odds_default))

    edge = _parse_float(
        os.environ.get("SERVICE_API_EDGE_THRESHOLD"),
        fallback=edge_default,
    )
    min_odds = _parse_float(
        os.environ.get("SERVICE_API_MIN_ODDS"),
        fallback=min_odds_default,
    )
    return EdgeDecisionParams(edge_threshold=edge, min_odds=min_odds)


def reset_service_api_settings_cache() -> None:
    """Сбросить кеш настроек (только для тестов)."""
    load_edge_decision_params.cache_clear()
