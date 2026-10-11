"""Контракт первого конфигурационного кандидата Premier League."""

from pathlib import Path

import pandas as pd

from sports_forecast.config.loaders import load_source_config, load_tournament_config
from sports_forecast.config.portfolio import load_portfolio_catalog
from sports_forecast.data.ingest import split_tournament_by_config
from sports_forecast.orchestration.candidate import build_candidate_plan


ROOT = Path(__file__).resolve().parents[1]


def test_premier_league_config_selects_only_eng1(tmp_path: Path) -> None:
    source = load_source_config("premier_league")
    tournament = load_tournament_config("premier_league")
    catalog = load_portfolio_catalog(ROOT / "conf/portfolio/default.yaml")

    frame = pd.DataFrame({"match_id": ["eng", "spa"], "competition_code": ["ENG1", "SPA1"]})
    split_tournament_by_config(frame, tmp_path, "premier_league", source.split_strategy)
    selected = pd.read_parquet(tmp_path / "premier_league/matches.parquet")

    assert selected["match_id"].tolist() == ["eng"]
    assert tournament.name == "premier_league"
    assert catalog.tournaments["premier_league"].source == "premier_league"
    assert catalog.deployment_profiles["premier_league_winner"].state == "candidate"

    plan = build_candidate_plan(catalog, "premier_league_winner")
    assert plan.source == "premier_league"
    assert plan.tournament == "premier_league"
    assert plan.train_overrides == (
        "tournament=premier_league",
        "market=winner",
        "market_spec=winner",
        "algorithm=logreg",
        "features=basic",
        "bookmaker=smart_tables",
    )
