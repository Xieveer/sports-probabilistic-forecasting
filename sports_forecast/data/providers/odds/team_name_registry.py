"""Реестр алиасов команд → каноническое имя для merge odds с source.

Загружается из YAML (секции по источникам: NHL API, The Odds API). Ключи и значения
нормализуются тем же способом, что и :func:`normalize_team_key`, чтобы сопоставление
было устойчивым к регистру/диакритике.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from sports_forecast.config.loaders import PROJECT_ROOT
from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)

#: Относительно корня репозитория — без хардкода абсолютных путей у потребителей.
DEFAULT_NHL_REGISTRY_PATH = Path("conf") / "bookmaker" / "team_name_registry" / "nhl.yaml"


def normalize_team_key(name: str) -> str:
    """Нормализовать имя команды для ключа сопоставления (ascii, upper, alnum)."""
    t = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^A-Z0-9]+", "", t.upper().strip())


@dataclass
class TeamNameRegistry:
    """Сопоставление алиасов (после нормализации ключа) с каноническим ключом merge.

    Пустой реестр эквивалентен «только :func:`normalize_team_key`».
    """

    _alias_to_canonical: dict[str, str] = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        """True, если нет ни одного алиаса (все разрешения — fallback-нормализация)."""
        return not self._alias_to_canonical

    def resolve(self, name: str) -> str:
        """Вернуть канонический ключ для имени: из реестра либо :func:`normalize_team_key`."""
        k = normalize_team_key(name)
        return self._alias_to_canonical.get(k, k)

    @classmethod
    def from_source_sections(
        cls,
        nhl_api: Mapping[str, Any] | None,
        odds_api: Mapping[str, Any] | None,
    ) -> TeamNameRegistry:
        """Собрать реестр из секций YAML ``nhl_api`` и ``odds_api`` (порядок: NHL, Odds)."""
        out: dict[str, str] = {}
        for section in (nhl_api or {}), (odds_api or {}):
            for alias, canonical in (section or {}).items():
                a = normalize_team_key(str(alias))
                c = normalize_team_key(str(canonical))
                if a and c:
                    out[a] = c
        return cls(_alias_to_canonical=out)


def load_team_name_registry_file(path: Path) -> TeamNameRegistry:
    """Загрузить реестр из YAML-файла.

    Ожидаемые корневые ключи: ``nhl_api``, ``odds_api`` (словари alias → canonical).
    Пустой или отсутствующий файл — пустой реестр. Ошибка парсинга пробрасывается.

    Args:
        path: Путь к ``*.yaml`` (абсолютный или относительно cwd).

    Returns:
        :class:`TeamNameRegistry` (возможно пустой).
    """
    if not path.is_file():
        logger.warning("TeamNameRegistry: файл не найден, пустой реестр: %s", path)
        return TeamNameRegistry()

    raw = path.read_text(encoding="utf-8")
    data = yaml.safe_load(raw) if raw.strip() else None
    if not isinstance(data, dict):
        return TeamNameRegistry()

    nhl = data.get("nhl_api")
    odds = data.get("odds_api")
    nhl_m = nhl if isinstance(nhl, dict) else None
    odds_m = odds if isinstance(odds, dict) else None
    return TeamNameRegistry.from_source_sections(nhl_m, odds_m)


def load_nhl_team_name_registry(
    project_root: Path | None = None,
    *,
    registry_path: Path | None = None,
) -> TeamNameRegistry:
    """Загрузить реестр NHL: ``conf/bookmaker/team_name_registry/nhl.yaml`` от корня проекта.

    Args:
        project_root: Корень репозитория; по умолчанию :data:`sports_forecast.config.loaders.PROJECT_ROOT`.
        registry_path: Явный путь к YAML; если задан, ``project_root`` не используется.

    Returns:
        Реестр или пустой, если файла нет.
    """
    if registry_path is not None:
        return load_team_name_registry_file(registry_path)
    root = project_root or PROJECT_ROOT
    return load_team_name_registry_file((root / DEFAULT_NHL_REGISTRY_PATH).resolve())
