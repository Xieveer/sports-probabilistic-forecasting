"""Повторяемый импорт доверенного NHL mapping YAML."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import yaml

from sports_forecast.identity.registry import Entity, EntityRegistry, _normalize, _timestamp


NHL_SEED_ID = "trusted:nhl-team-name-registry:v1"


def import_nhl_yaml(registry: EntityRegistry, path: Path) -> str:
    """Атомарно импортировать проверенный mapping; вернуть стабильный seed ID."""
    content = Path(path).read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    parsed: Any = yaml.safe_load(content)
    if not isinstance(parsed, dict):
        raise ValueError("NHL seed должен быть YAML-объектом")
    nhl_api = parsed.get("nhl_api")
    odds_api = parsed.get("odds_api")
    if not isinstance(nhl_api, dict) or not isinstance(odds_api, dict):
        raise ValueError("NHL seed должен содержать nhl_api и odds_api")
    if any(
        not isinstance(key, str)
        or not key.strip()
        or not isinstance(value, str)
        or not value.strip()
        for section in (nhl_api, odds_api)
        for key, value in section.items()
    ):
        raise ValueError("Ключи и значения NHL seed должны быть непустыми строками")
    canonical_names = set(nhl_api.values())
    source_ids_by_canonical: dict[str, list[str]] = {}
    for source_id, canonical_name in nhl_api.items():
        source_ids_by_canonical.setdefault(canonical_name, []).append(source_id)
    unknown_canonical = set(odds_api.values()) - canonical_names
    if unknown_canonical:
        raise ValueError(
            f"Odds seed содержит неизвестные canonical команды: {sorted(unknown_canonical)}"
        )

    with registry._connect() as connection:
        imported = connection.execute(
            "SELECT content_hash FROM imports WHERE seed_key=?", (NHL_SEED_ID,)
        ).fetchone()
        if imported is not None and imported["content_hash"] == digest:
            return NHL_SEED_ID

        tournament = registry._seed_entity_in_transaction(
            connection, "tournament", "NHL", "ice_hockey", NHL_SEED_ID
        )
        scope = {"sport": "ice_hockey", "tournament": tournament.id}
        scope_json = registry._scope_json(scope)
        entities = {}
        for canonical_name in sorted(canonical_names):
            existing_entity_ids: set[str] = set()
            for source_id in source_ids_by_canonical[canonical_name]:
                existing = connection.execute(
                    "SELECT entity_id FROM designations WHERE source='nhl_api' AND kind='team' AND scope_json=? AND value_kind='external_id' AND normalized_value=? AND entity_id IS NOT NULL",
                    (scope_json, _normalize(source_id, "external_id")),
                ).fetchone()
                if existing is not None:
                    existing_entity_ids.add(existing["entity_id"])
            if len(existing_entity_ids) > 1:
                raise ValueError(
                    f"NHL source IDs для {canonical_name!r} уже связаны с разными project ID"
                )
            if existing_entity_ids:
                entity_id = next(iter(existing_entity_ids))
                entity_row = connection.execute(
                    "SELECT * FROM entities WHERE id=? AND kind='team'", (entity_id,)
                ).fetchone()
                if entity_row is None:
                    raise ValueError("Существующая NHL привязка указывает на неизвестную команду")
                entities[canonical_name] = Entity(
                    entity_row["id"],
                    entity_row["kind"],
                    entity_row["sport"],
                    entity_row["project_name"],
                    entity_row["revision"],
                )
            else:
                entities[canonical_name] = registry._seed_entity_in_transaction(
                    connection,
                    "team",
                    canonical_name,
                    "ice_hockey",
                    NHL_SEED_ID,
                    stable_key=f"nhl_api:{sorted(source_ids_by_canonical[canonical_name])[0]}",
                )
        for source, mapping, value_kind in (
            ("nhl_api", nhl_api, "external_id"),
            ("the_odds_api", odds_api, "name"),
        ):
            for raw_value, canonical_name in mapping.items():
                normalized = _normalize(raw_value, value_kind)
                existing = connection.execute(
                    "SELECT id FROM designations WHERE source=? AND kind='team' AND scope_json=? AND value_kind=? AND normalized_value=? LIMIT 1",
                    (
                        source,
                        registry._scope_json(scope),
                        value_kind,
                        normalized,
                    ),
                ).fetchone()
                if existing is not None:
                    # Любое существующее состояние может содержать решение владельца.
                    continue
                registry._insert_designation(
                    connection,
                    entity_id=entities[canonical_name].id,
                    source=source,
                    kind="team",
                    scope=scope,
                    value_kind=value_kind,
                    raw_value=raw_value,
                    state="confirmed",
                    valid_from=None,
                    valid_until=None,
                    seed_key=NHL_SEED_ID,
                )
        connection.execute(
            "INSERT INTO imports (seed_key,content_hash,imported_at) VALUES (?,?,?) ON CONFLICT(seed_key) DO UPDATE SET content_hash=excluded.content_hash,imported_at=excluded.imported_at",
            (NHL_SEED_ID, digest, _timestamp()),
        )
    return NHL_SEED_ID
