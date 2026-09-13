"""Контракт полноты локального bronze-кэша Smart Tables."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from omegaconf import OmegaConf

from sports_forecast.data.providers.base import SourceFetchError
from sports_forecast.data.providers.smart_tables.assembler import load_assembler_config
from sports_forecast.data.providers.smart_tables.bronze_manifest import (
    WINNER_BASELINE_PROFILE,
    scan_bronze_cache,
)
from sports_forecast.data.providers.smart_tables.fetch import fetch_match_bronze


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "smart_tables"


def test_scan_classifies_required_and_optional_bronze_components(tmp_path: Path) -> None:
    """Отсутствующий chart не лишает матч готовности, stat_all — лишает."""
    raw_root = tmp_path / "raw"
    shutil.copytree(FIXTURES / "314668", raw_root / "101")
    (raw_root / "101" / "chart_all.json").unlink()

    (raw_root / "102").mkdir(parents=True)
    (raw_root / "102" / "card.json").write_text(
        json.dumps({"success": True, "data": {}}), encoding="utf-8"
    )

    manifest = scan_bronze_cache(raw_root, profile=WINNER_BASELINE_PROFILE)

    assert manifest.train_ready_match_ids == (101,)
    assert manifest.missing_required_match_ids == (102,)
    assert manifest.optional_only_match_ids == (101,)
    assert manifest.component_coverage["card.json"] == 1.0
    assert manifest.component_coverage["stat_all.json"] == 0.5
    assert manifest.train_ready_coverage == 0.5


def test_targeted_required_resume_skips_valid_cached_files(tmp_path: Path) -> None:
    """Required resume не делает HTTP для валидных card/stat_all."""
    raw_root = tmp_path / "raw"
    shutil.copytree(FIXTURES / "314668", raw_root / "101")

    class UnexpectedClient:
        def get_json(self, path: str, params: dict[str, object] | None = None) -> dict[str, object]:
            raise AssertionError(f"Неожиданный запрос: {path} {params}")

    bronze = fetch_match_bronze(
        UnexpectedClient(),  # type: ignore[arg-type]
        101,
        raw_root,
        profile=WINNER_BASELINE_PROFILE,
        include_optional=False,
    )

    assert set(bronze) == {"card", "stat_all"}


def test_scan_marks_corrupt_and_unsuccessful_envelopes_incomplete(tmp_path: Path) -> None:
    """Manifest не хранит payload и безопасно фиксирует тип ошибки."""
    raw_root = tmp_path / "raw"
    match_dir = raw_root / "101"
    match_dir.mkdir(parents=True)
    (match_dir / "card.json").write_text("{broken", encoding="utf-8")
    (match_dir / "stat_all.json").write_text(
        json.dumps({"success": False, "errors": ["secret response body"]}), encoding="utf-8"
    )

    manifest = scan_bronze_cache(raw_root, profile=WINNER_BASELINE_PROFILE)

    assert manifest.train_ready_match_ids == ()
    assert manifest.matches[0].component("card.json").error_kind == "invalid_json"
    assert manifest.matches[0].component("stat_all.json").error_kind == "invalid_envelope"
    assert "secret response body" not in json.dumps(manifest.to_dict())


def test_coverage_cli_reports_targeted_resume_plan(tmp_path: Path) -> None:
    """CLI печатает coverage и списки required/optional без записи в bronze."""
    raw_root = tmp_path / "raw"
    shutil.copytree(FIXTURES / "314668", raw_root / "101")
    (raw_root / "101" / "chart_all.json").unlink()

    result = subprocess.run(
        [
            sys.executable,
            "scripts/smart_tables_bronze_coverage.py",
            "--raw-root",
            str(raw_root),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    report = json.loads(result.stdout)
    assert report["train_ready_match_ids"] == [101]
    assert report["optional_only_match_ids"] == [101]
    assert report["component_coverage"]["chart_all.json"] == 0.0


def test_required_only_profile_is_explicit_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    """Массовый backfill использует только required только при явном env."""
    monkeypatch.setenv("SF_SMART_TABLES_BRONZE_PROFILE", "winner_baseline_required")
    cfg = load_assembler_config(
        OmegaConf.create(
            {
                "catalog_path": "catalog.json",
                "national_teams_only": False,
                "matches_list_cache_dir": "raw/lists",
                "raw_cache_dir": "raw",
                "mode": "backfill",
            }
        )
    )
    assert cfg.bronze_profile == "winner_baseline_required"


def test_failed_required_fetch_is_visible_in_manifest_without_response_body(tmp_path: Path) -> None:
    """Timeout сохраняет безопасный failed outcome для последующего resume."""

    class FailingClient:
        def get_json(self, path: str, params: dict[str, object] | None = None) -> dict[str, object]:
            raise SourceFetchError("Smart Tables HTTP ошибка: secret response body")

    with pytest.raises(SourceFetchError):
        fetch_match_bronze(
            FailingClient(),  # type: ignore[arg-type]
            101,
            tmp_path / "raw",
            profile=WINNER_BASELINE_PROFILE,
            include_optional=False,
        )

    component = (
        scan_bronze_cache(tmp_path / "raw", profile=WINNER_BASELINE_PROFILE)
        .matches[0]
        .component("card.json")
    )
    assert component.last_attempt_status == "failed"
    assert component.error_kind == "request_failed"
