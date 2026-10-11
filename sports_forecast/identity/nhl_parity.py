"""Проверка переноса NHL team aliases из legacy YAML в master и snapshot."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

from sports_forecast.identity.registry import EntityRegistry
from sports_forecast.identity.snapshot import (
    RegistrySnapshotReader,
    verify_registry_snapshot,
)


@dataclass(frozen=True)
class NHLParityDifference:
    """Одно отсутствующее или отличающееся legacy designation."""

    stage: str
    source: str
    raw_value: str
    expected_entity_id: str | None
    actual_entity_id: str | None
    reason: str


@dataclass(frozen=True)
class NHLParityReport:
    """Результат последовательной сверки YAML, SQLite master и snapshot."""

    yaml_designations: int
    master_snapshot_id: str
    differences: tuple[NHLParityDifference, ...]

    @property
    def is_complete(self) -> bool:
        """True, если все legacy aliases разрешаются одинаково на обеих стадиях."""
        return not self.differences

    def to_dict(self) -> dict[str, Any]:
        """Вернуть компактное сериализуемое представление отчёта."""
        return {
            "yaml_designations": self.yaml_designations,
            "master_snapshot_id": self.master_snapshot_id,
            "is_complete": self.is_complete,
            "differences": [asdict(item) for item in self.differences],
        }


def _read_seed(path: Path) -> tuple[dict[str, str], dict[str, str]]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("NHL legacy seed должен быть YAML-объектом")
    nhl_api = data.get("nhl_api")
    odds_api = data.get("odds_api")
    for name, mapping in (("nhl_api", nhl_api), ("odds_api", odds_api)):
        if not isinstance(mapping, dict) or any(
            not isinstance(key, str)
            or not key.strip()
            or not isinstance(value, str)
            or not value.strip()
            for key, value in mapping.items()
        ):
            raise ValueError(f"NHL legacy seed: секция {name} должна содержать строки")
    return nhl_api, odds_api


def check_nhl_registry_parity(
    yaml_path: Path,
    master_path: Path,
    snapshot_path: Path,
) -> NHLParityReport:
    """Сверить известные YAML aliases с подтверждёнными master и snapshot.

    Master остаётся источником ожидаемых project IDs для snapshot check. Новые
    master designations не считаются ошибкой: владелец может расширять registry.
    """
    nhl_api, odds_api = _read_seed(yaml_path)
    canonical_to_source_ids: dict[str, set[str]] = {}
    for source_id, canonical in nhl_api.items():
        canonical_to_source_ids.setdefault(canonical, set()).add(source_id)
    unknown_canonical = set(odds_api.values()) - set(canonical_to_source_ids)
    if unknown_canonical:
        raise ValueError(
            f"Odds seed ссылается на неизвестные NHL teams: {sorted(unknown_canonical)}"
        )

    registry = EntityRegistry(Path(master_path))
    scope = {"sport": "ice_hockey"}
    try:
        tournament = registry.find_designation("nhl_web_api", "tournament", scope, "name", "nhl")
        if tournament.state != "confirmed" or tournament.entity_id is None:
            raise ValueError("Master не содержит подтверждённый NHL tournament designation")
        team_scope = {**scope, "tournament": tournament.entity_id}
    except KeyError as exc:
        raise ValueError("Master не содержит NHL tournament designation") from exc

    verified_snapshot = verify_registry_snapshot(Path(snapshot_path))
    snapshot_reader = RegistrySnapshotReader(verified_snapshot)
    differences: list[NHLParityDifference] = []
    expected_rows: list[tuple[str, str, str, str]] = []
    for source_id, canonical in nhl_api.items():
        expected_rows.append(("nhl_api", "external_id", source_id, canonical))
        expected_rows.append(("nhl_web_api", "name", source_id, canonical))
    for alias, canonical in odds_api.items():
        expected_rows.append(("the_odds_api", "name", alias, canonical))

    resolved_master: dict[tuple[str, str, str], str | None] = {}
    for source, value_kind, raw_value, _canonical in expected_rows:
        try:
            designation = registry.find_designation(
                source, "team", team_scope, value_kind, raw_value
            )
            actual = designation.entity_id if designation.state == "confirmed" else None
            reason = "designation_not_confirmed" if actual is None else "entity_mismatch"
        except KeyError:
            actual = None
            reason = "designation_missing"
        resolved_master[(source, value_kind, raw_value)] = actual
        if actual is None:
            differences.append(
                NHLParityDifference(
                    "master",
                    source,
                    raw_value,
                    None,
                    actual,
                    reason,
                )
            )

    canonical_entity_ids: dict[str, set[str]] = {}
    for source_id, canonical in nhl_api.items():
        entity_id = resolved_master[("nhl_api", "external_id", source_id)]
        if entity_id is not None:
            canonical_entity_ids.setdefault(canonical, set()).add(entity_id)
    for source, value_kind, raw_value, canonical in expected_rows:
        expected_entity_id = resolved_master[(source, value_kind, raw_value)]
        canonical_ids = canonical_entity_ids.get(canonical, set())
        if len(canonical_ids) != 1:
            expected_entity_id = None
            if source == "nhl_api" or resolved_master[(source, value_kind, raw_value)] is not None:
                differences.append(
                    NHLParityDifference(
                        "master",
                        source,
                        raw_value,
                        None,
                        resolved_master[(source, value_kind, raw_value)],
                        "canonical_entity_missing_or_split",
                    )
                )
        else:
            expected_entity_id = next(iter(canonical_ids))
            actual_master_id = resolved_master[(source, value_kind, raw_value)]
            if actual_master_id is not None and actual_master_id != expected_entity_id:
                differences.append(
                    NHLParityDifference(
                        "master",
                        source,
                        raw_value,
                        expected_entity_id,
                        actual_master_id,
                        "entity_mismatch",
                    )
                )
        resolution = snapshot_reader.resolve_designation(
            source=source,
            kind="team",
            scope=team_scope,
            value_kind=value_kind,
            raw_value=raw_value,
        )
        actual = resolution.entity_id if resolution.status == "resolved" else None
        if actual != expected_entity_id:
            differences.append(
                NHLParityDifference(
                    "snapshot",
                    source,
                    raw_value,
                    expected_entity_id,
                    actual,
                    resolution.status if actual is None else "entity_mismatch",
                )
            )

    return NHLParityReport(len(expected_rows), verified_snapshot.snapshot_id, tuple(differences))


def main() -> int:
    """Запустить parity checker и вернуть ненулевой код при расхождениях."""
    parser = argparse.ArgumentParser(description="Сверка NHL legacy aliases с registry")
    parser.add_argument("--yaml", type=Path, required=True, dest="yaml_path")
    parser.add_argument("--master", type=Path, required=True, dest="master_path")
    parser.add_argument("--snapshot", type=Path, required=True, dest="snapshot_path")
    args = parser.parse_args()
    report = check_nhl_registry_parity(args.yaml_path, args.master_path, args.snapshot_path)
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report.is_complete else 1


if __name__ == "__main__":
    raise SystemExit(main())
