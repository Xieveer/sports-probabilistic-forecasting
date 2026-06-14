"""Backfill C: загрузка card/stat/chart/similar с raw JSON кэшем на диск."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from sports_forecast.data.providers.smart_tables.client import SmartTablesApiClient
from sports_forecast.data.providers.smart_tables.constants import (
    MATCH_CARD_RELATED_ENTITIES,
    PERIODS_API,
)
from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)


def match_raw_dir(raw_root: Path, match_id: int) -> Path:
    """Каталог bronze для одного матча."""
    return raw_root / str(match_id)


def _read_or_fetch(
    cache_path: Path,
    fetch_fn,
    *,
    use_network: bool,
) -> dict[str, Any]:
    if cache_path.is_file():
        return cast(dict[str, Any], json.loads(cache_path.read_text(encoding="utf-8")))
    if not use_network:
        return {}
    payload = cast(dict[str, Any], fetch_fn())
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return payload


def load_match_bronze_from_cache(raw_root: Path, match_id: int) -> dict[str, Any]:
    """Прочитать bronze JSON с диска без HTTP-клиента.

    Args:
        raw_root: ``data/source/football_nationals/raw``.
        match_id: PK матча ST.

    Returns:
        Словарь с ключами ``card``, ``stat_{period}``, ``chart_{period}``, ``similar``.
        Пустой ``card`` если ``card.json`` отсутствует.
    """
    mdir = match_raw_dir(raw_root, match_id)
    out: dict[str, Any] = {}
    card_path = mdir / "card.json"
    if not card_path.is_file():
        return out
    out["card"] = cast(dict[str, Any], json.loads(card_path.read_text(encoding="utf-8")))
    for period in PERIODS_API:
        for kind in ("stat", "chart"):
            cache_path = mdir / f"{kind}_{period}.json"
            out[f"{kind}_{period}"] = (
                cast(dict[str, Any], json.loads(cache_path.read_text(encoding="utf-8")))
                if cache_path.is_file()
                else {}
            )
    similar_path = mdir / "similar.json"
    out["similar"] = (
        cast(dict[str, Any], json.loads(similar_path.read_text(encoding="utf-8")))
        if similar_path.is_file()
        else {}
    )
    return out


def fetch_match_bronze(
    client: SmartTablesApiClient,
    match_id: int,
    raw_root: Path,
    *,
    use_network: bool = True,
) -> dict[str, Any]:
    """Загрузить (или прочитать из кэша) все bronze-файлы матча.

    Args:
        client: HTTP-клиент.
        match_id: PK матча ST.
        raw_root: ``data/source/football_nationals/raw``.
        use_network: При отсутствии кэша — запрос к API.

    Returns:
        Словарь с ключами ``card``, ``stat_{period}``, ``chart_{period}``, ``similar``.
    """
    mdir = match_raw_dir(raw_root, match_id)
    out: dict[str, Any] = {}

    out["card"] = _read_or_fetch(
        mdir / "card.json",
        lambda: client.get_json(
            f"matches/{match_id}",
            params={"relatedEntities": MATCH_CARD_RELATED_ENTITIES},
        ),
        use_network=use_network,
    )

    for period in PERIODS_API:
        out[f"stat_{period}"] = _read_or_fetch(
            mdir / f"stat_{period}.json",
            lambda p=period: client.get_json(
                f"matches/{match_id}/stat",
                params={"period": p},
            ),
            use_network=use_network,
        )
        out[f"chart_{period}"] = _read_or_fetch(
            mdir / f"chart_{period}.json",
            lambda p=period: client.get_json(
                f"matches/{match_id}/chart",
                params={"period": p, "stat": "goals"},
            ),
            use_network=use_network,
        )

    out["similar"] = _read_or_fetch(
        mdir / "similar.json",
        lambda: client.get_json(f"matches/{match_id}/similar"),
        use_network=use_network,
    )
    return out


def read_checkpoint(path: Path) -> set[int]:
    """Прочитать множество обработанных ``match_id``."""
    if not path.exists():
        return set()
    ids: set[int] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                ids.add(int(line))
            except ValueError:
                continue
    return ids


def append_checkpoint(path: Path, match_id: int) -> None:
    """Добавить ``match_id`` в checkpoint-файл."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(f"{match_id}\n")
