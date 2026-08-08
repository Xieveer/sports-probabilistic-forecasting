"""Контракт конфигурационного каталога мультиспортивного портфеля."""

from __future__ import annotations

from pathlib import Path

import pytest

from sports_forecast.config.portfolio import PortfolioConfigError, load_portfolio_catalog


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _write_catalog(tmp_path: Path, content: str) -> Path:
    """Сохранить минимальный каталог для проверки контракта."""
    path = tmp_path / "portfolio.yaml"
    path.write_text(content, encoding="utf-8")
    return path


def test_loads_candidate_profile_for_supported_tournament(tmp_path: Path) -> None:
    """Каталог связывает турнир, пул и candidate-профиль."""
    path = _write_catalog(
        tmp_path,
        """
model_pools:
  football_winner:
    sport: football
    market_specs: [winner]
tournaments:
  premier_league:
    sport: football
    source: football_feed
    memberships:
      - model_pool: football_winner
        market_specs: [winner]
deployment_profiles:
  premier_league_winner:
    tournament: premier_league
    model_pool: football_winner
    market_spec: winner
    state: candidate
""",
    )

    catalog = load_portfolio_catalog(path)

    assert catalog.tournaments["premier_league"].source == "football_feed"
    assert catalog.deployment_profiles["premier_league_winner"].state == "candidate"


def test_loads_versioned_default_portfolio_catalog() -> None:
    """Репозиторный каталог фиксирует NHL legacy и футбольного кандидата."""
    catalog = load_portfolio_catalog(PROJECT_ROOT / "conf" / "portfolio" / "default.yaml")

    assert catalog.deployment_profiles["nhl_winner_with_ot"].state == "production"
    assert catalog.deployment_profiles["football_nationals_winner"].state == "candidate"


def test_rejects_tournament_membership_with_incompatible_sport(tmp_path: Path) -> None:
    """Турнир нельзя включить в пул другого вида спорта."""
    path = _write_catalog(
        tmp_path,
        """
model_pools:
  hockey_winner:
    sport: ice_hockey
    market_specs: [winner]
tournaments:
  premier_league:
    sport: football
    source: football_feed
    memberships:
      - model_pool: hockey_winner
        market_specs: [winner]
deployment_profiles: {}
""",
    )

    with pytest.raises(PortfolioConfigError, match="несовместим со sport"):
        load_portfolio_catalog(path)


def test_rejects_duplicate_market_spec_membership(tmp_path: Path) -> None:
    """Один market/spec турнира принадлежит ровно одному model pool."""
    path = _write_catalog(
        tmp_path,
        """
model_pools:
  football_winner_a:
    sport: football
    market_specs: [winner]
  football_winner_b:
    sport: football
    market_specs: [winner]
tournaments:
  premier_league:
    sport: football
    source: football_feed
    memberships:
      - model_pool: football_winner_a
        market_specs: [winner]
      - model_pool: football_winner_b
        market_specs: [winner]
deployment_profiles: {}
""",
    )

    with pytest.raises(PortfolioConfigError, match="несколько model_pool"):
        load_portfolio_catalog(path)


def test_rejects_production_profile_without_immutable_model_reference(tmp_path: Path) -> None:
    """Production разрешён только при наличии модели и отчёта кандидата."""
    path = _write_catalog(
        tmp_path,
        """
model_pools:
  football_winner:
    sport: football
    market_specs: [winner]
tournaments:
  premier_league:
    sport: football
    source: football_feed
    memberships:
      - model_pool: football_winner
        market_specs: [winner]
deployment_profiles:
  premier_league_winner:
    tournament: premier_league
    model_pool: football_winner
    market_spec: winner
    state: production
""",
    )

    with pytest.raises(PortfolioConfigError, match="immutable_model_ref"):
        load_portfolio_catalog(path)


def test_rejects_deployment_profile_for_unassigned_model_pool(tmp_path: Path) -> None:
    """Deployment не может заменить pool, назначенный турниру."""
    path = _write_catalog(
        tmp_path,
        """
model_pools:
  football_winner_a:
    sport: football
    market_specs: [winner]
  football_winner_b:
    sport: football
    market_specs: [winner]
tournaments:
  premier_league:
    sport: football
    source: football_feed
    memberships:
      - model_pool: football_winner_a
        market_specs: [winner]
deployment_profiles:
  premier_league_winner:
    tournament: premier_league
    model_pool: football_winner_b
    market_spec: winner
    state: candidate
""",
    )

    with pytest.raises(PortfolioConfigError, match="не назначен турниру"):
        load_portfolio_catalog(path)
