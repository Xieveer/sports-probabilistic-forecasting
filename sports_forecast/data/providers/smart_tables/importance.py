"""Производные поля match_importance и is_friendly из competition."""

from __future__ import annotations

from typing import Any


def compute_is_friendly(competition: dict[str, Any] | None) -> int:
    """1 если товарищеский матч (``code == FRII``)."""
    if not competition:
        return 0
    return 1 if str(competition.get("code", "")).upper() == "FRII" else 0


def compute_match_importance(competition: dict[str, Any] | None) -> int:
    """Классификация важности матча (1–4) для фильтрации при обучении.

    Args:
        competition: Объект ``competition`` из карточки матча ST.

    Returns:
        1=friendly, 4=flagship, 3=competitive cup, 2=остальные сборные.
    """
    if not competition:
        return 2
    code = str(competition.get("code", "")).upper()
    if code == "FRII":
        return 1
    if int(competition.get("is_top") or 0) == 1:
        return 4
    if int(competition.get("is_cup") or 0) == 1:
        return 3
    return 2
