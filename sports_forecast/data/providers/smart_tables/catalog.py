"""Загрузка и фильтрация каталога турниров Smart Tables."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sports_forecast.config.loaders import PROJECT_ROOT
from sports_forecast.data.providers.base import SourceFetchError


@dataclass(frozen=True)
class CompetitionEntry:
    """Одна запись каталога slug → competition_id."""

    country_slug: str
    competition_slug: str
    competition_id: int
    code: str
    title: str
    for_national_teams: int
    match_count: int


def _parse_entry(raw: dict[str, Any]) -> CompetitionEntry | None:
    cid = raw.get("competition_id")
    if cid is None:
        return None
    return CompetitionEntry(
        country_slug=str(raw.get("country_slug", "")),
        competition_slug=str(raw.get("competition_slug", "")),
        competition_id=int(cid),
        code=str(raw.get("code", "")),
        title=str(raw.get("title", "")),
        for_national_teams=int(raw.get("for_national_teams", 0)),
        match_count=int(raw.get("match_count", 0)),
    )


def load_competition_catalog(catalog_path: str | Path) -> list[CompetitionEntry]:
    """Загрузить ``competition_catalog.json``.

    Args:
        catalog_path: Путь относительно корня репо или абсолютный.

    Returns:
        Список записей каталога.

    Raises:
        SourceFetchError: Файл не найден или невалидный JSON.
    """
    path = Path(catalog_path)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    if not path.is_file():
        raise SourceFetchError(f"Каталог Smart Tables не найден: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise SourceFetchError(f"Каталог Smart Tables: невалидный JSON {path}: {e}") from e
    if not isinstance(raw, list):
        raise SourceFetchError(f"Каталог Smart Tables: ожидался list, получено {type(raw)}")
    out: list[CompetitionEntry] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        entry = _parse_entry(item)
        if entry is not None:
            out.append(entry)
    return out


def filter_national_competitions(
    entries: list[CompetitionEntry],
    *,
    national_teams_only: bool = True,
    competition_codes: list[str] | None = None,
) -> list[CompetitionEntry]:
    """Отфильтровать турниры сборных и опционально по кодам (WC, EURO, …).

    Args:
        entries: Полный каталог.
        national_teams_only: Оставить только ``for_national_teams == 1``.
        competition_codes: Whitelist кодов; ``None`` — без фильтра по коду.

    Returns:
        Отфильтрованный список (стабильный порядок по competition_id).
    """
    out: list[CompetitionEntry] = []
    codes = {c.strip().upper() for c in competition_codes} if competition_codes else None
    for e in entries:
        if national_teams_only and e.for_national_teams != 1:
            continue
        if codes is not None and e.code.upper() not in codes:
            continue
        out.append(e)
    return sorted(out, key=lambda x: x.competition_id)
