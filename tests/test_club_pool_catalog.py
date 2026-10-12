"""Контракт единого клубного пула до запуска локального E2E."""

from __future__ import annotations

from pathlib import Path

from sports_forecast.config.loaders import load_source_config
from sports_forecast.config.portfolio import load_portfolio_catalog
from sports_forecast.orchestration.portfolio_refresh import build_heavy_refresh_targets


def test_club_pool_is_one_market_without_scheduled_refresh() -> None:
    """Локальный клубный пул не активирует Airflow или production refresh."""
    catalog = load_portfolio_catalog(Path("conf/portfolio/default.yaml"))
    pool = catalog.model_pools["football_top_leagues"]
    tournament = catalog.tournaments["football_top_leagues"]
    source = load_source_config(tournament.source)

    assert pool.sport == tournament.sport == "football"
    assert pool.market_specs == ("winner_1x2",)
    assert tournament.memberships[0].market_specs == pool.market_specs
    assert all(
        profile.tournament != tournament.name for profile in catalog.deployment_profiles.values()
    )
    assert all(
        target.tournament != tournament.name for target in build_heavy_refresh_targets(catalog)
    )
    assert set(source.provider.competition_codes) == {
        "ENG1",
        "SPA1",
        "GER1",
        "ITA1",
        "FRA1",
        "RUS1",
        "RUS2",
        "UCL",
        "UEL",
    }
