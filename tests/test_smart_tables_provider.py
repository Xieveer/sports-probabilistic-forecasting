"""Тесты Smart Tables provider (без сетевых вызовов в CI)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from omegaconf import OmegaConf

import sports_forecast.data.clean as clean_mod
from sports_forecast.config.loaders import load_tournament_config
from sports_forecast.data.clean import process_tournament as clean_tournament
from sports_forecast.data.providers import SmartTablesSourceProvider, get_provider
from sports_forecast.data.providers.smart_tables.assembler import (
    bronze_to_row,
    load_assembler_config,
)
from sports_forecast.data.providers.smart_tables.catalog import (
    filter_national_competitions,
    load_competition_catalog,
)
from sports_forecast.data.providers.smart_tables.client import SmartTablesApiClient
from sports_forecast.data.providers.smart_tables.fetch import fetch_match_bronze
from sports_forecast.data.providers.smart_tables.importance import (
    compute_is_friendly,
    compute_match_importance,
)


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "smart_tables"
CATALOG_PATH = (
    Path(__file__).resolve().parents[1]
    / "docs/cursor/source_data/smart-tables/competition_catalog.json"
)

FOOTBALL_REQUIRED_COLUMNS: tuple[str, ...] = (
    "match_id",
    "datetime",
    "match_status",
    "match_is_end",
    "home_team_name",
    "away_team_name",
    "home_score_ft",
    "away_score_ft",
    "competition_code",
    "match_importance",
    "is_friendly",
    "home_goals_all",
    "away_goals_all",
    "odd_home",
    "odd_draw",
    "odd_away",
)


def _load_bronze_fixture(match_id: int = 314668) -> dict:
    base = FIXTURES / str(match_id)
    return {
        "card": json.loads((base / "card.json").read_text(encoding="utf-8")),
        "stat_all": json.loads((base / "stat_all.json").read_text(encoding="utf-8")),
        "stat_first": json.loads((base / "stat_first.json").read_text(encoding="utf-8")),
        "stat_second": json.loads((base / "stat_second.json").read_text(encoding="utf-8")),
        "chart_all": json.loads((base / "chart_all.json").read_text(encoding="utf-8")),
        "chart_first": json.loads((base / "chart_first.json").read_text(encoding="utf-8")),
        "chart_second": json.loads((base / "chart_second.json").read_text(encoding="utf-8")),
        "similar": json.loads((base / "similar.json").read_text(encoding="utf-8")),
    }


def _provider_cfg(**overrides: object) -> OmegaConf:
    base = {
        "type": "smart_tables_api",
        "base_url": "https://backend.smart-tables.ru/api/v1",
        "min_delay_sec": 1.0,
        "catalog_path": str(CATALOG_PATH),
        "national_teams_only": True,
        "competition_codes": ["WC"],
        "max_matches": 3,
        "use_network": False,
        "matches_page_limit": 200,
        "matches_list_checkpoint": ".smart_tables_matches_checkpoint.json",
        "matches_list_cache_dir": "raw/lists",
        "raw_cache_dir": "raw",
        "checkpoint_file": ".smart_tables_checkpoint.txt",
        "csv_flush_every": 0,
        "progress_log_every": 0,
        "mode": "backfill",
    }
    base.update(overrides)
    return OmegaConf.create(base)


def _seed_storage(tmp_path: Path, match_ids: list[int]) -> Path:
    """Скопировать fixtures и подготовить list cache для WC competition_id=27."""
    storage = tmp_path / "football_nationals"
    raw = storage / "raw"
    for mid in match_ids:
        src = FIXTURES / str(mid) if (FIXTURES / str(mid)).is_dir() else FIXTURES / "314668"
        shutil.copytree(src, raw / str(mid), dirs_exist_ok=True)

    list_dir = storage / "raw" / "lists"
    list_dir.mkdir(parents=True, exist_ok=True)
    items = [{"id": mid} for mid in match_ids]
    payload = {"success": True, "data": {"items": items, "total": len(items)}}
    (list_dir / "27_0.json").write_text(json.dumps(payload), encoding="utf-8")
    return storage


def test_client_rate_limit_sleeps() -> None:
    client = SmartTablesApiClient(_provider_cfg(min_delay_sec=0.2))
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"success": True, "data": {}}

    with (
        patch.object(client._session, "get", return_value=mock_resp) as mock_get,
        patch("sports_forecast.data.providers.smart_tables.client.time.sleep") as mock_sleep,
        patch(
            "sports_forecast.data.providers.smart_tables.client.time.monotonic",
            side_effect=[0.0, 0.05, 0.25],
        ),
    ):
        client.get_json("matches/1")
        client.get_json("matches/2")
    assert mock_get.call_count == 2
    mock_sleep.assert_called()
    wait = mock_sleep.call_args[0][0]
    assert wait > 0


def test_bronze_to_row_wc_final_314668() -> None:
    row = bronze_to_row(_load_bronze_fixture())
    assert row is not None
    assert row["match_id"] == 314668
    assert row["competition_code"] == "WC"
    assert row["match_importance"] == 4
    assert row["is_friendly"] == 0
    assert row["home_team_name"] == "Argentina"
    assert row["away_team_name"] == "France"
    assert row["home_goals_all"] == 2
    assert row["away_goals_all"] == 2
    assert row["home_score_ht"] == 2
    assert row["away_score_ht"] == 0
    assert row["odd_home"] == 2.45
    for col in FOOTBALL_REQUIRED_COLUMNS:
        assert col in row, f"missing {col}"


def test_national_filter_rejects_club_teams() -> None:
    bronze = _load_bronze_fixture()
    card = bronze["card"]["data"]["item"]
    card["home_team_with_coach"]["is_national"] = 0
    bronze["card"]["data"]["item"] = card
    assert bronze_to_row(bronze) is None


def test_match_importance_tiers() -> None:
    assert compute_match_importance({"code": "FRII"}) == 1
    assert compute_is_friendly({"code": "FRII"}) == 1
    assert compute_match_importance({"code": "WC", "is_top": 1, "is_cup": 1}) == 4
    assert compute_match_importance({"code": "WCQE", "is_cup": 1, "is_top": 0}) == 3
    assert compute_match_importance({"code": "EU21", "is_cup": 0}) == 2


def test_catalog_national_filter() -> None:
    entries = load_competition_catalog(CATALOG_PATH)
    nationals = filter_national_competitions(entries, national_teams_only=True)
    assert len(nationals) == 37
    wc = [e for e in nationals if e.code == "WC"]
    assert len(wc) == 1
    assert wc[0].competition_id == 27


def test_get_provider_smart_tables_api() -> None:
    source_cfg = OmegaConf.create(
        {
            "name": "football_nationals",
            "provider": {"type": "smart_tables_api", "catalog_path": str(CATALOG_PATH)},
        }
    )
    paths_cfg = OmegaConf.create({"paths": {"source_dir": "data/source"}})
    provider = get_provider(source_cfg, paths_cfg)
    assert isinstance(provider, SmartTablesSourceProvider)
    assert provider.is_available()


def test_fetch_match_bronze_from_cache(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    mid = 314668
    shutil.copytree(FIXTURES / str(mid), raw / str(mid))
    client = SmartTablesApiClient(_provider_cfg())
    bronze = fetch_match_bronze(client, mid, raw, use_network=False)
    assert bronze["card"]["success"] is True
    assert bronze["stat_all"]["data"]["stat"][0]["code"] == "goals"


def test_provider_backfill_offline(tmp_path: Path) -> None:
    project = tmp_path / "repo"
    _seed_storage(project / "data" / "source", [314668])

    source_cfg = OmegaConf.create(
        {
            "name": "football_nationals",
            "provider": _provider_cfg(max_matches=1, competition_codes=["WC"]),
        }
    )
    paths_cfg = OmegaConf.create({"paths": {"source_dir": "data/source"}})

    provider = SmartTablesSourceProvider(
        source_cfg=source_cfg,
        paths_cfg=paths_cfg,
        project_root=project,
    )

    out = provider.fetch("football_nationals")
    assert out.is_file()
    df = pd.read_csv(out, dtype=str)
    assert len(df) >= 1
    assert "314668" in df["match_id"].astype(str).values


def test_contract_ingest_clean_smoke(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Assembler → ingest → clean на offline cache (max 1 матч)."""
    project = tmp_path / "repo"
    _seed_storage(project / "data" / "source", [314668])

    source_cfg = OmegaConf.create(
        {
            "name": "football_nationals",
            "provider": _provider_cfg(max_matches=1, competition_codes=["WC"]),
        }
    )
    paths_cfg = OmegaConf.create(
        {
            "paths": {
                "source_dir": "data/source",
                "raw_dir": "data/raw",
                "interim_dir": "data/interim",
            }
        }
    )
    provider = SmartTablesSourceProvider(
        source_cfg=source_cfg,
        paths_cfg=paths_cfg,
        project_root=project,
    )
    csv_path = provider.fetch("football_nationals")
    assert csv_path.is_file()

    raw_root = project / "data" / "raw"
    raw_parquet = raw_root / "football_nationals" / "matches.parquet"
    raw_parquet.parent.mkdir(parents=True, exist_ok=True)
    pd.read_csv(csv_path, dtype=str, low_memory=False).to_parquet(raw_parquet, index=False)
    assert raw_parquet.is_file()
    raw_df = pd.read_parquet(raw_parquet)
    assert len(raw_df) >= 1

    monkeypatch.setattr(clean_mod, "PROJECT_ROOT", project)
    tournament_cfg = load_tournament_config("football_nationals")
    clean_tournament(raw_root / "football_nationals", tournament_cfg, paths_cfg)

    interim_path = project / "data" / "interim" / "football_nationals" / "matches_interim.parquet"
    assert interim_path.is_file()
    interim = pd.read_parquet(interim_path)
    for col in ("id", "datetime", "home_points", "away_points", "competition_code"):
        assert col in interim.columns
    assert interim["competition_code"].iloc[0] == "WC"


def test_load_assembler_config_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SF_SMART_TABLES_MAX_MATCHES", "5")
    monkeypatch.setenv("SF_SMART_TABLES_COMPETITION_CODES", "WC,EURO")
    cfg = load_assembler_config(_provider_cfg())
    assert cfg.max_matches == 5
    assert cfg.competition_codes == ["WC", "EURO"]
