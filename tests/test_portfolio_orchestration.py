"""Контракт построения heavy refresh targets из portfolio catalog."""

from __future__ import annotations

from pathlib import Path

import pytest

from sports_forecast.config.portfolio import PortfolioConfigError, load_portfolio_catalog
from sports_forecast.orchestration.portfolio_refresh import (
    HeavyRefreshTarget,
    build_heavy_refresh_command,
    build_heavy_refresh_targets,
)


def test_catalog_profiles_build_isolated_targets_without_static_tournament_list(
    tmp_path: Path,
) -> None:
    """Новый профиль каталога добавляет target без изменения списка в Python/DAG."""
    catalog_path = tmp_path / "portfolio.yaml"
    catalog_path.write_text(
        """model_pools:
  football_winner:
    sport: football
    market_specs: [winner]
tournaments:
  league_a:
    sport: football
    source: feed_a
    memberships: [{model_pool: football_winner, market_specs: [winner]}]
  league_b:
    sport: football
    source: feed_b
    memberships: [{model_pool: football_winner, market_specs: [winner]}]
deployment_profiles:
  league_a_winner:
    tournament: league_a
    model_pool: football_winner
    market_spec: winner
    state: candidate
  league_b_winner:
    tournament: league_b
    model_pool: football_winner
    market_spec: winner
    state: candidate
""",
        encoding="utf-8",
    )

    targets = build_heavy_refresh_targets(load_portfolio_catalog(catalog_path))

    assert [(target.tournament, target.source) for target in targets] == [
        ("league_a", "feed_a"),
        ("league_b", "feed_b"),
    ]
    assert targets[0].lock_key != targets[1].lock_key


def test_target_command_uses_one_tournament_and_its_own_lock() -> None:
    """Конфликтует только refresh того же tournament/source, а не всего портфеля."""
    target = HeavyRefreshTarget(
        tournament="league_a",
        source="feed_a",
        model_pool="football_winner",
        market_spec="winner",
        lock_key="sf-refresh-league-a",
    )

    command = build_heavy_refresh_command(target, project_dir="/app", uv_run="uv run")

    assert 'flock -w 300 "/tmp/sf-refresh-league-a.lock"' in command
    assert '<<< "league_a"' in command
    assert "league_b" not in command


def test_catalog_rejects_duplicate_heavy_target_for_same_tournament_and_spec(
    tmp_path: Path,
) -> None:
    """Несколько profile одной heavy-цепочки не создают параллельную гонку."""
    catalog_path = tmp_path / "portfolio.yaml"
    catalog_path.write_text(
        """model_pools:
  football_winner:
    sport: football
    market_specs: [winner]
tournaments:
  league_a:
    sport: football
    source: feed_a
    memberships: [{model_pool: football_winner, market_specs: [winner]}]
deployment_profiles:
  first:
    tournament: league_a
    model_pool: football_winner
    market_spec: winner
    state: candidate
  second:
    tournament: league_a
    model_pool: football_winner
    market_spec: winner
    state: candidate
""",
        encoding="utf-8",
    )

    with pytest.raises(PortfolioConfigError, match="уже есть профиль"):
        load_portfolio_catalog(catalog_path)
