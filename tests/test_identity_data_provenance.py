"""Проверки content binding и переноса registry identity через DVC data layers."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest
from omegaconf import OmegaConf

from sports_forecast.data import clean, ingest
from sports_forecast.features import features_build
from sports_forecast.identity.data_provenance import (
    IdentityRowResolution,
    load_enabled_registry_snapshot,
    propagate_identity_provenance,
    read_identity_provenance,
    write_identity_provenance,
)
from sports_forecast.identity.snapshot import (
    RegistrySnapshotReader,
    VerifiedRegistrySnapshot,
    export_registry_snapshot,
    install_registry_snapshot,
    verify_registry_snapshot,
)
from tests.test_registry_snapshot import _registry


def _rewrite_sidecar(path: Path, update: dict[str, object]) -> None:
    sidecar = Path(f"{path}.identity.json")
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    payload.update(update)
    payload.pop("provenance_sha256", None)
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    payload["provenance_sha256"] = hashlib.sha256(encoded).hexdigest()
    sidecar.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )


def test_identity_provenance_propagates_verified_rows_and_allows_long_duplicates(
    tmp_path: Path,
) -> None:
    registry = _registry(tmp_path / "master.sqlite3")
    snapshot = export_registry_snapshot(registry, tmp_path / "snapshots")
    verified = verify_registry_snapshot(snapshot.path)
    RegistrySnapshotReader(verified)
    raw = tmp_path / "raw.parquet"
    interim = tmp_path / "interim.parquet"
    long = tmp_path / "train_long.parquet"
    pd.DataFrame({"id": ["101", "102"]}).to_parquet(raw)
    resolutions = (
        IdentityRowResolution(
            "101",
            "fixture-101",
            "resolved",
            registry.list_entities(kind="event")[0].id,
            "Точное совпадение",
        ),
        IdentityRowResolution("102", "fixture-102", "unresolved", None, "Связь не найдена"),
    )

    write_identity_provenance(
        raw,
        snapshot=verified,
        adapter_name="synthetic",
        source="fixture-feed",
        tournament="north-league",
        resolutions=resolutions,
    )
    pd.DataFrame({"id": ["101", "102"]}).to_parquet(interim)
    propagate_identity_provenance(
        raw,
        interim,
        snapshot_root=tmp_path / "snapshots",
        row_id_column="id",
    )
    pd.DataFrame({"id": ["101", "101", "102"]}).to_parquet(long)
    propagate_identity_provenance(
        interim,
        long,
        snapshot_root=tmp_path / "snapshots",
        row_id_column="id",
        allow_duplicate_row_ids=True,
    )

    provenance = read_identity_provenance(long, snapshot_root=tmp_path / "snapshots")

    assert provenance.snapshot_id == verified.snapshot_id
    assert provenance.dataset_row_count == 3
    assert [row.row_id for row in provenance.resolutions] == ["101", "102"]


def test_identity_provenance_rejects_stale_sidecar_after_same_row_count_change(
    tmp_path: Path,
) -> None:
    registry = _registry(tmp_path / "master.sqlite3")
    snapshot = verify_registry_snapshot(
        export_registry_snapshot(registry, tmp_path / "snapshots").path
    )
    dataset = tmp_path / "matches.parquet"
    pd.DataFrame({"id": ["101", "102"]}).to_parquet(dataset)
    write_identity_provenance(
        dataset,
        snapshot=snapshot,
        adapter_name="synthetic",
        source="fixture-feed",
        tournament="north-league",
        resolutions=(
            IdentityRowResolution("101", "fixture-101", "unresolved", None, "Ожидает решения"),
            IdentityRowResolution("102", "fixture-102", "unresolved", None, "Ожидает решения"),
        ),
    )
    pd.DataFrame({"id": ["changed-1", "changed-2"]}).to_parquet(dataset)

    with pytest.raises(ValueError, match="hash|измен|checksum"):
        read_identity_provenance(dataset, snapshot_root=tmp_path / "snapshots")


@pytest.mark.parametrize("row_ids", [["101", "101"], ["101", None]])
def test_identity_provenance_rejects_duplicate_or_missing_resolution_ids(
    tmp_path: Path, row_ids: list[str | None]
) -> None:
    registry = _registry(tmp_path / "master.sqlite3")
    snapshot = verify_registry_snapshot(
        export_registry_snapshot(registry, tmp_path / "snapshots").path
    )
    dataset = tmp_path / "matches.parquet"
    pd.DataFrame({"id": ["row"]}).to_parquet(dataset)
    resolutions = tuple(
        IdentityRowResolution(row_id, f"event-{index}", "unresolved", None, "Нет связи")
        for index, row_id in enumerate(row_ids)
    )

    with pytest.raises(ValueError, match="ID|идентификатор|повтор"):
        write_identity_provenance(
            dataset,
            snapshot=snapshot,
            adapter_name="synthetic",
            source="fixture-feed",
            tournament="north-league",
            resolutions=resolutions,
        )


def test_identity_provenance_rejects_duplicate_source_parquet_ids(tmp_path: Path) -> None:
    registry = _registry(tmp_path / "master.sqlite3")
    snapshot = verify_registry_snapshot(
        export_registry_snapshot(registry, tmp_path / "snapshots").path
    )
    dataset = tmp_path / "matches.parquet"
    pd.DataFrame({"id": ["101", "101"]}).to_parquet(dataset)

    with pytest.raises(ValueError, match="уникальным|повтор"):
        write_identity_provenance(
            dataset,
            snapshot=snapshot,
            adapter_name="synthetic",
            source="fixture-feed",
            tournament="north-league",
            resolutions=(
                IdentityRowResolution("101", "fixture-101", "unresolved", None, "Нет связи"),
            ),
        )


def test_identity_provenance_rejects_digest_path_traversal(tmp_path: Path) -> None:
    registry = _registry(tmp_path / "master.sqlite3")
    snapshot = verify_registry_snapshot(
        export_registry_snapshot(registry, tmp_path / "snapshots").path
    )
    dataset = tmp_path / "matches.parquet"
    pd.DataFrame({"id": ["101"]}).to_parquet(dataset)
    write_identity_provenance(
        dataset,
        snapshot=snapshot,
        adapter_name="synthetic",
        source="fixture-feed",
        tournament="north-league",
        resolutions=(IdentityRowResolution("101", "x", "unresolved", None, "Нет связи"),),
    )
    _rewrite_sidecar(dataset, {"snapshot_sha256": "../" + "a" * 61, "snapshot_id": "bad"})

    with pytest.raises(ValueError, match="digest"):
        read_identity_provenance(dataset, snapshot_root=tmp_path / "snapshots")


def test_identity_provenance_rejects_oversized_sidecar_before_json_parse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sports_forecast.identity import data_provenance

    registry = _registry(tmp_path / "master.sqlite3")
    snapshot = verify_registry_snapshot(
        export_registry_snapshot(registry, tmp_path / "snapshots").path
    )
    dataset = tmp_path / "matches.parquet"
    pd.DataFrame({"id": ["101"]}).to_parquet(dataset)
    write_identity_provenance(
        dataset,
        snapshot=snapshot,
        adapter_name="synthetic",
        source="fixture-feed",
        tournament="north-league",
        resolutions=(IdentityRowResolution("101", "x", "unresolved", None, "Нет связи"),),
    )
    monkeypatch.setattr(data_provenance, "MAX_SIDECAR_BYTES", 1)

    with pytest.raises(ValueError, match="размер"):
        read_identity_provenance(dataset, snapshot_root=tmp_path / "snapshots")


def test_selected_package_changes_pin_and_corruption_fails_before_use(tmp_path: Path) -> None:
    registry = _registry(tmp_path / "master.sqlite3")
    archive = tmp_path / "project" / "data" / "registry" / "snapshots"
    selected_path = tmp_path / "project" / "data" / "registry" / "current" / "package"
    config_dir = tmp_path / "project" / "conf"
    config_dir.mkdir(parents=True)
    first = export_registry_snapshot(registry, archive)
    install_registry_snapshot(first.path, selected_path)
    config_path = config_dir / "identity_registry.yaml"
    config_path.write_text(
        "enabled: true\n"
        "enabled_tournaments: [demo]\n"
        "adapters:\n  demo:\n    source: feed\n    sport: hockey\n    row_id: id\n    event_id: event\n    scheduled_at: date\n    home_id: home\n    away_id: away\n"
        "snapshot_root: data/registry/snapshots\n"
        "selected_package_path: data/registry/current/package\n",
        encoding="utf-8",
    )

    first_pin = load_enabled_registry_snapshot(tmp_path / "project")
    assert first_pin is not None and first_pin.snapshot_id == first.snapshot_id
    assert first_pin.path == first.path
    event = registry.list_entities(kind="event")[0]
    registry.rename_entity(event.id, "Revised", actor="owner", reason="Pin switch regression")
    second = export_registry_snapshot(registry, archive)
    install_registry_snapshot(second.path, selected_path)
    second_pin = load_enabled_registry_snapshot(tmp_path / "project")
    assert second_pin is not None and second_pin.snapshot_id == second.snapshot_id
    assert first_pin.snapshot_id != second_pin.snapshot_id
    assert first_pin.path == first.path

    (selected_path / "entities.jsonl").write_bytes(b"damaged\n")
    with pytest.raises(ValueError):
        load_enabled_registry_snapshot(tmp_path / "project")


def test_snapshot_manifest_limit_checked_before_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sports_forecast.identity.snapshot import SnapshotLimits

    registry = _registry(tmp_path / "master.sqlite3")
    package = export_registry_snapshot(registry, tmp_path / "snapshots")
    manifest_path = package.path / "manifest.json"
    limits = SnapshotLimits(max_line_bytes=10)
    original_read_bytes = Path.read_bytes

    def guarded_read_bytes(path: Path) -> bytes:
        if path == manifest_path:
            raise AssertionError("Manifest был прочитан до проверки размера")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", guarded_read_bytes)
    with pytest.raises(ValueError, match="Manifest"):
        verify_registry_snapshot(package.path, limits=limits)


def test_identity_provenance_rejects_forged_resolved_event_even_with_recomputed_checksum(
    tmp_path: Path,
) -> None:
    registry = _registry(tmp_path / "master.sqlite3")
    snapshot = verify_registry_snapshot(
        export_registry_snapshot(registry, tmp_path / "snapshots").path
    )
    dataset = tmp_path / "matches.parquet"
    pd.DataFrame({"id": ["101"]}).to_parquet(dataset)
    write_identity_provenance(
        dataset,
        snapshot=snapshot,
        adapter_name="synthetic",
        source="fixture-feed",
        tournament="north-league",
        resolutions=(IdentityRowResolution("101", "x", "unresolved", None, "Нет связи"),),
    )
    _rewrite_sidecar(
        dataset,
        {
            "resolutions": [
                {
                    "row_id": "101",
                    "source_event_id": "x",
                    "status": "resolved",
                    "project_event_id": "00000000-0000-4000-8000-000000000001",
                    "reason": "Forged",
                }
            ]
        },
    )

    with pytest.raises(ValueError, match="verified registry snapshot"):
        read_identity_provenance(dataset, snapshot_root=tmp_path / "snapshots")


def test_ingest_run_pins_once_and_keeps_unselected_tournament_legacy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = _registry(tmp_path / "master.sqlite3")
    project_root = tmp_path / "project"
    archive = project_root / "data" / "registry" / "snapshots"
    package = export_registry_snapshot(registry, archive)
    current = project_root / "data" / "registry" / "current" / "package"
    install_registry_snapshot(package.path, current)
    (project_root / "conf").mkdir(parents=True)
    (project_root / "conf" / "identity_registry.yaml").write_text(
        "enabled: true\n"
        "enabled_tournaments: [demo]\n"
        "snapshot_root: data/registry/snapshots\n"
        "selected_package_path: data/registry/current/package\n"
        "adapters:\n  demo:\n    source: feed\n    sport: hockey\n    row_id: id\n    event_id: event\n    scheduled_at: date\n    home_id: home\n    away_id: away\n",
        encoding="utf-8",
    )
    source_root = project_root / "data" / "source"
    (source_root / "demo").mkdir(parents=True)
    (source_root / "legacy").mkdir(parents=True)
    paths_cfg = OmegaConf.create({"paths": {"source_dir": "data/source", "raw_dir": "data/raw"}})
    monkeypatch.setattr(ingest, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(ingest, "load_paths_config", lambda: paths_cfg)
    captured: list[tuple[str, VerifiedRegistrySnapshot | None]] = []

    def capture(
        source_dir: Path,
        _raw_root: Path,
        _paths_cfg: object,
        *,
        identity_snapshot: VerifiedRegistrySnapshot | None = None,
    ) -> None:
        captured.append((source_dir.name, identity_snapshot))
        if source_dir.name == "demo":
            registry.rename_entity(
                registry.list_entities(kind="event")[0].id,
                "Edited during stage",
                actor="owner",
                reason="Mid-run snapshot pin regression",
            )
            switched = export_registry_snapshot(registry, archive)
            install_registry_snapshot(switched.path, current)

    monkeypatch.setattr(ingest, "process_tournament", capture)
    ingest.run()

    assert [name for name, _snapshot in captured] == ["demo", "legacy"]
    assert captured[0][1] is not None
    assert captured[0][1] is captured[1][1]
    assert captured[0][1].snapshot_id == package.snapshot_id


def test_ingest_rollout_without_adapter_fails_before_processing_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_root = tmp_path / "project"
    conf = project_root / "conf"
    conf.mkdir(parents=True)
    (conf / "identity_registry.yaml").write_text(
        "enabled: true\nenabled_tournaments: [missing_adapter]\nadapters: {}\n",
        encoding="utf-8",
    )
    source = project_root / "data" / "source" / "missing_adapter"
    source.mkdir(parents=True)
    paths_cfg = OmegaConf.create({"paths": {"source_dir": "data/source", "raw_dir": "data/raw"}})
    processed: list[str] = []
    monkeypatch.setattr(ingest, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(ingest, "load_paths_config", lambda: paths_cfg)
    monkeypatch.setattr(
        ingest,
        "process_tournament",
        lambda *args, **kwargs: processed.append(str(args[0])),
    )

    with pytest.raises(ValueError, match="adapter"):
        ingest.run()

    assert processed == []


def test_clean_pipeline_verifies_raw_sidecar_and_writes_content_bound_interim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = _registry(tmp_path / "master.sqlite3")
    snapshot = verify_registry_snapshot(
        export_registry_snapshot(registry, tmp_path / "data" / "registry" / "snapshots").path
    )
    project_root = tmp_path / "project"
    (project_root / "conf").mkdir(parents=True)
    snapshot_path = project_root / "data" / "registry" / "snapshots" / snapshot.projection_sha256
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    import shutil

    shutil.copytree(snapshot.path, snapshot_path)
    selected_path = project_root / "data" / "registry" / "current" / "package"
    selected_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(snapshot.path, selected_path)
    (project_root / "conf" / "identity_registry.yaml").write_text(
        "enabled: true\n"
        "enabled_tournaments: [fixture]\n"
        "adapters:\n  fixture:\n    source: feed\n    sport: hockey\n    row_id: id\n    event_id: event\n    scheduled_at: date\n    home_id: home\n    away_id: away\n"
        "snapshot_root: data/registry/snapshots\n"
        "selected_package_path: data/registry/current/package\n"
        "master_db: data/registry/master.sqlite3\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(clean, "PROJECT_ROOT", project_root)
    raw_path = tmp_path / "data" / "raw" / "fixture" / "matches.parquet"
    raw_path.parent.mkdir(parents=True)
    pd.DataFrame({"id": ["row-1"], "score": [1]}).to_parquet(raw_path)
    write_identity_provenance(
        raw_path,
        snapshot=snapshot,
        adapter_name="fixture",
        source="fixture-feed",
        tournament="fixture",
        resolutions=(IdentityRowResolution("row-1", "evt-1", "unresolved", None, "Review"),),
    )
    tournament_cfg = OmegaConf.create(
        {
            "data_clean": {
                "required_columns": ["id"],
                "score_columns": [],
                "drop_na_columns": [],
                "select_columns": ["id"],
            }
        }
    )
    paths_cfg = OmegaConf.create({"paths": {"interim_dir": "data/interim"}})

    clean.process_tournament(raw_path.parent, tournament_cfg, paths_cfg)

    interim = project_root / "data" / "interim" / "fixture" / "matches_interim.parquet"
    provenance = read_identity_provenance(
        interim, snapshot_root=project_root / "data" / "registry" / "snapshots"
    )
    assert provenance.snapshot_id == snapshot.snapshot_id
    assert provenance.parquet_sha256


def test_features_pipeline_writes_sidecars_for_train_and_inference_formats(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = _registry(tmp_path / "master.sqlite3")
    exported = export_registry_snapshot(registry, tmp_path / "exported")
    snapshot = verify_registry_snapshot(exported.path)
    project_root = tmp_path / "project"
    (project_root / "conf").mkdir(parents=True)
    package_path = project_root / "data" / "registry" / "snapshots" / snapshot.projection_sha256
    package_path.parent.mkdir(parents=True)
    import shutil

    shutil.copytree(snapshot.path, package_path)
    selected_path = project_root / "data" / "registry" / "current" / "package"
    selected_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(snapshot.path, selected_path)
    (project_root / "conf" / "identity_registry.yaml").write_text(
        "enabled: true\n"
        "enabled_tournaments: [demo]\n"
        "adapters:\n  demo:\n    source: feed\n    sport: hockey\n    row_id: id\n    event_id: event\n    scheduled_at: date\n    home_id: home\n    away_id: away\n"
        "snapshot_root: data/registry/snapshots\n"
        "selected_package_path: data/registry/current/package\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(features_build, "PROJECT_ROOT", project_root)
    interim_root = tmp_path / "interim"
    input_path = interim_root / "demo" / "matches_interim.parquet"
    input_path.parent.mkdir(parents=True)
    pd.DataFrame(
        {
            "id": ["1", "2"],
            "status": ["finished", "upcoming"],
            "home_team": ["North", "North"],
            "away_team": ["South", "South"],
        }
    ).to_parquet(input_path)
    write_identity_provenance(
        input_path,
        snapshot=snapshot,
        adapter_name="fixture",
        source="fixture-feed",
        tournament="demo",
        resolutions=(
            IdentityRowResolution("1", "evt-1", "unresolved", None, "Review"),
            IdentityRowResolution("2", "evt-2", "unresolved", None, "Review"),
        ),
    )

    class StubPipeline:
        def __init__(self, _config: object) -> None:
            pass

        def get_generator_summary(self) -> dict[str, int]:
            return {}

        def generate_features(
            self, _frame: pd.DataFrame, *, format: str
        ) -> tuple[pd.DataFrame, list[str]]:
            assert format == "wide"
            return (
                pd.DataFrame(
                    {
                        "id": ["1", "1", "2", "2"],
                        "status": ["finished", "finished", "upcoming", "upcoming"],
                    }
                ),
                [],
            )

    monkeypatch.setattr(features_build, "FeaturePipeline", StubPipeline)
    monkeypatch.setattr(features_build, "materialize_features_config", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        features_build,
        "long_to_wide",
        lambda frame, **_kwargs: frame.drop_duplicates("id").reset_index(drop=True),
    )
    monkeypatch.setattr("sports_forecast.validation.gates.validate_processed", lambda *a, **k: None)
    processed = tmp_path / "processed"

    features_build.process_tournament_new("demo", interim_root, processed, OmegaConf.create({}))

    for name in ("train_long", "train_wide", "inference_long", "inference_wide"):
        data_path = processed / "demo" / f"{name}.parquet"
        provenance = read_identity_provenance(
            data_path,
            snapshot_root=project_root / "data" / "registry" / "snapshots",
            expected_snapshot_id=snapshot.snapshot_id,
        )
        assert provenance.dataset_row_count == len(pd.read_parquet(data_path))

    inference_only = tmp_path / "inference-only"
    features_build.process_tournament_new(
        "demo", interim_root, inference_only, OmegaConf.create({}), inference_only=True
    )
    for name in ("inference_long", "inference_wide"):
        data_path = inference_only / "demo" / f"{name}.parquet"
        provenance = read_identity_provenance(
            data_path,
            snapshot_root=project_root / "data" / "registry" / "snapshots",
            expected_snapshot_id=snapshot.snapshot_id,
        )
        assert provenance.dataset_row_count == len(pd.read_parquet(data_path))

    def finished_only(_self: object, _frame: pd.DataFrame, *, format: str):
        return pd.DataFrame({"id": ["1"], "status": ["finished"]}), []

    monkeypatch.setattr(StubPipeline, "generate_features", finished_only)
    empty_only = tmp_path / "empty-inference-only"
    features_build.process_tournament_new(
        "demo", interim_root, empty_only, OmegaConf.create({}), inference_only=True
    )
    for name in ("inference_long", "inference_wide"):
        data_path = empty_only / "demo" / f"{name}.parquet"
        provenance = read_identity_provenance(
            data_path,
            snapshot_root=project_root / "data" / "registry" / "snapshots",
            expected_snapshot_id=snapshot.snapshot_id,
        )
        assert provenance.dataset_row_count == 0


@pytest.mark.parametrize("split", [False, True])
def test_ingest_entrypoint_writes_raw_sidecars_for_single_and_split_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, split: bool
) -> None:
    registry = _registry(tmp_path / "master.sqlite3")
    package = export_registry_snapshot(registry, tmp_path / "snapshots")
    snapshot = verify_registry_snapshot(package.path)
    project_root = tmp_path / "project"
    (project_root / "conf").mkdir(parents=True)
    selected_package = project_root / "data" / "registry" / "snapshots" / snapshot.projection_sha256
    selected_package.parent.mkdir(parents=True)
    import shutil

    shutil.copytree(snapshot.path, selected_package)
    current_package = project_root / "data" / "registry" / "current" / "package"
    current_package.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(snapshot.path, current_package)
    (project_root / "conf" / "identity_registry.yaml").write_text(
        "enabled: true\n"
        "enabled_tournaments: [demo]\n"
        "snapshot_root: data/registry/snapshots\n"
        "selected_package_path: data/registry/current/package\n"
        "master_db: data/registry/master.sqlite3\n"
        "adapters:\n"
        "  demo:\n"
        "    source: fixture-feed\n"
        "    sport: ice_hockey\n"
        "    event_id: external_event\n"
        "    row_id: id\n"
        "    scheduled_at: scheduled_at\n"
        "    tournament_value: League\n"
        "    home_id: home_id\n"
        "    away_id: away_id\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(ingest, "PROJECT_ROOT", project_root)
    source_dir = tmp_path / "source" / "demo"
    source_dir.mkdir(parents=True)
    pd.DataFrame(
        {
            "id": ["row-1"],
            "external_event": ["fixture-101"],
            "scheduled_at": ["2026-10-04T17:00:00Z"],
            "home_id": ["NTH"],
            "away_id": ["STH"],
            "group": ["selected"],
        }
    ).to_csv(source_dir / "source.csv", index=False)
    source_config = OmegaConf.create(
        {
            "split_strategy": {
                "enabled": split,
                "split_column": "group",
                "rules": [
                    {
                        "condition": "equals('selected')",
                        "output_tournament": "demo-selected",
                    }
                ],
            }
        }
    )

    class Provider:
        def fetch(self, _name: str) -> Path:
            return source_dir / "source.csv"

    monkeypatch.setattr(ingest, "load_source_config", lambda _name: source_config)
    monkeypatch.setattr(ingest, "get_provider", lambda *_args: Provider())
    raw_root = tmp_path / "raw"

    ingest.process_tournament(source_dir, raw_root, OmegaConf.create({}))

    output = raw_root / ("demo-selected" if split else "demo") / "matches.parquet"
    provenance = read_identity_provenance(
        output,
        snapshot_root=project_root / "data" / "registry" / "snapshots",
        expected_snapshot_id=snapshot.snapshot_id,
    )
    assert provenance.resolutions[0].project_event_id == registry.list_entities(kind="event")[0].id
