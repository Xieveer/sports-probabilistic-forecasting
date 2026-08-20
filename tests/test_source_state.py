"""Контракт NHL source-state bootstrap, install и failure preservation."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from sports_forecast.data.providers.odds.store import ODDS_STORE_COLUMNS_V3
from sports_forecast.deploy.source_state import (
    SourceStateError,
    build_nhl_source_state_bundle,
    export_nhl_source_state,
    install_nhl_source_state_bundle,
    prepare_nhl_source_state_input,
    verify_nhl_source_state_bundle,
)


def _state_files(root: Path, value: str = "1") -> tuple[Path, Path, Path]:
    root.mkdir(parents=True, exist_ok=True)
    source = root / "source.csv"
    source.write_text(
        f"id,datetime,match_is_end\n{value},2026-08-20T00:00:00Z,0\n", encoding="utf-8"
    )
    odds = root / "odds" / "pinnacle_odds.parquet"
    odds.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [{"game_date": "2026-08-20", "pinnacle_winner_withOT_home_close": 2.1}]
    ).to_parquet(odds)
    checkpoint = root / "odds" / "refresh_state.json"
    checkpoint.write_text(json.dumps({"last_successful_date": "2026-08-19"}), encoding="utf-8")
    return source, odds, checkpoint


def test_initial_bundle_verify_and_idempotent_vps_install(tmp_path: Path) -> None:
    source, odds, checkpoint = _state_files(tmp_path / "input")
    bundle = build_nhl_source_state_bundle(source, odds, checkpoint, tmp_path / "bundles")
    assert verify_nhl_source_state_bundle(bundle.path).artifact_id == bundle.artifact_id

    volume = tmp_path / "volume"
    first = install_nhl_source_state_bundle(bundle.path, volume)
    second = install_nhl_source_state_bundle(bundle.path, volume)

    assert first.artifact_id == second.artifact_id
    assert (volume / "current.csv").read_bytes() == source.read_bytes()
    assert (volume / "odds/pinnacle_odds.parquet").is_file()
    assert (
        json.loads((bundle.path / "manifest.json").read_text())["provenance"]["source_rows"] == "1"
    )


def test_invalid_bundle_is_rejected_before_install_mutation(tmp_path: Path) -> None:
    source, odds, checkpoint = _state_files(tmp_path / "input")
    bundle = build_nhl_source_state_bundle(source, odds, checkpoint, tmp_path / "bundles")
    (bundle.path / "source.csv").write_text("corrupt", encoding="utf-8")

    with pytest.raises((SourceStateError, ValueError), match="checksum|Manifest|размер"):
        install_nhl_source_state_bundle(bundle.path, tmp_path / "volume")

    assert not (tmp_path / "volume" / "current.csv").exists()


def test_install_rolls_back_if_file_replacement_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, odds, checkpoint = _state_files(tmp_path / "input")
    bundle = build_nhl_source_state_bundle(source, odds, checkpoint, tmp_path / "bundles")
    volume = tmp_path / "volume"
    volume.mkdir()
    (volume / "source.csv").write_text("old", encoding="utf-8")
    (volume / "current.csv").write_text("old", encoding="utf-8")

    import sports_forecast.deploy.source_state as source_state

    original_copyfile = source_state.shutil.copyfile
    calls = 0

    def fail_on_second_copy(
        src: str | Path, dst: str | Path, *, follow_symlinks: bool = True
    ) -> str:
        nonlocal calls
        if Path(dst).name.endswith(".new"):
            calls += 1
        if calls == 2:
            raise OSError("simulated install interruption")
        return str(original_copyfile(src, dst, follow_symlinks=follow_symlinks))

    monkeypatch.setattr(source_state.shutil, "copyfile", fail_on_second_copy)
    with pytest.raises(OSError, match="interruption"):
        install_nhl_source_state_bundle(bundle.path, volume)

    assert (volume / "source.csv").read_text(encoding="utf-8") == "old"
    assert (volume / "current.csv").read_text(encoding="utf-8") == "old"


def test_successful_refresh_export_contains_full_source_state(tmp_path: Path) -> None:
    source, odds, checkpoint = _state_files(tmp_path / "volume")
    artifact = export_nhl_source_state(source, tmp_path / "archive", run_id="refresh-1")

    assert artifact.path.parent.name == "v1"
    assert {
        item["path"]
        for item in json.loads((artifact.path / "manifest.json").read_text(encoding="utf-8"))[
            "files"
        ]
    } == {"source.csv", "odds/pinnacle_odds.parquet", "odds/refresh_state.json"}


def test_manifest_records_actual_v3_odds_schema(tmp_path: Path) -> None:
    source, odds, checkpoint = _state_files(tmp_path / "volume")
    row = dict.fromkeys(ODDS_STORE_COLUMNS_V3)
    row["game_date"] = "2026-08-20"
    pd.DataFrame([row]).to_parquet(odds)

    artifact = build_nhl_source_state_bundle(source, odds, checkpoint, tmp_path / "archive")
    provenance = json.loads((artifact.path / "manifest.json").read_text())["provenance"]

    assert provenance["odds_schema_version"] == "3"


def test_local_training_descriptor_keeps_odds_history_available(tmp_path: Path) -> None:
    source, odds, checkpoint = _state_files(tmp_path / "volume")
    artifact = build_nhl_source_state_bundle(source, odds, checkpoint, tmp_path / "archive")

    descriptor = prepare_nhl_source_state_input(
        artifact.path, tmp_path / "imports", tmp_path / "training" / "input.json"
    )

    payload = json.loads(descriptor.read_text(encoding="utf-8"))
    assert "odds/pinnacle_odds.parquet" in payload["partitions"]


def test_failed_refresh_does_not_create_replacement_source_state_artifact(tmp_path: Path) -> None:
    source, odds, checkpoint = _state_files(tmp_path / "volume")
    archive_root = tmp_path / "archive"
    previous = build_nhl_source_state_bundle(source, odds, checkpoint, archive_root, run_id="ok")
    odds.unlink()

    with pytest.raises(SourceStateError):
        build_nhl_source_state_bundle(source, odds, checkpoint, archive_root, run_id="failed")

    artifacts = list((archive_root / "operational-archive/nhl-source-state/v1").iterdir())
    assert [path.name for path in artifacts] == [previous.artifact_id]
