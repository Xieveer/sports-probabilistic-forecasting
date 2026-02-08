"""
Тесты для sports_forecast/train.py — entry point обучения.

Покрывает:
    - _get_mlflow_experiment_name
"""

from __future__ import annotations

from omegaconf import OmegaConf

from sports_forecast.train import _get_mlflow_experiment_name


# ─────────────────────────────────────────────────────────────────────────────
# _get_mlflow_experiment_name
# ─────────────────────────────────────────────────────────────────────────────


class TestGetMlflowExperimentName:
    """Тесты для _get_mlflow_experiment_name."""

    def test_total_with_line(self) -> None:
        """Total market с линией → tournament__total__over_6.5."""
        cfg = OmegaConf.create(
            {
                "tournament": {"name": "uel_kz_1"},
                "market": {"family": "total"},
                "market_spec": {"side": "over", "line": 6.5},
            }
        )
        result = _get_mlflow_experiment_name(cfg)
        assert result == "uel_kz_1__total__over_6.5"

    def test_handicap_with_line(self) -> None:
        """Handicap market с линией → tournament__handicap__home_1.5."""
        cfg = OmegaConf.create(
            {
                "tournament": {"name": "lp_ru"},
                "market": {"family": "handicap"},
                "market_spec": {"side": "home", "line": 1.5},
            }
        )
        result = _get_mlflow_experiment_name(cfg)
        assert result == "lp_ru__handicap__home_1.5"

    def test_winner_with_side(self) -> None:
        """Winner market с side → tournament__winner__home."""
        cfg = OmegaConf.create(
            {
                "tournament": {"name": "uel_cz"},
                "market": {"family": "winner"},
                "market_spec": {"side": "home"},
            }
        )
        result = _get_mlflow_experiment_name(cfg)
        assert result == "uel_cz__winner__home"

    def test_winner_without_side(self) -> None:
        """Winner market без side → tournament__winner."""
        cfg = OmegaConf.create(
            {
                "tournament": {"name": "uel_kz_2"},
                "market": {"family": "winner"},
                "market_spec": {"name": "winner"},
            }
        )
        result = _get_mlflow_experiment_name(cfg)
        assert result == "uel_kz_2__winner"

    def test_total_under(self) -> None:
        """Total under с линией."""
        cfg = OmegaConf.create(
            {
                "tournament": {"name": "lp_eu"},
                "market": {"family": "total"},
                "market_spec": {"side": "under", "line": 70.5},
            }
        )
        result = _get_mlflow_experiment_name(cfg)
        assert result == "lp_eu__total__under_70.5"

    def test_different_tournaments(self) -> None:
        """Разные турниры → разные имена экспериментов."""
        base = {
            "market": {"family": "total"},
            "market_spec": {"side": "over", "line": 6.5},
        }

        cfg1 = OmegaConf.create({**base, "tournament": {"name": "uel_kz_1"}})
        cfg2 = OmegaConf.create({**base, "tournament": {"name": "lp_ru"}})

        assert _get_mlflow_experiment_name(cfg1) != _get_mlflow_experiment_name(cfg2)

    def test_market_without_side_key(self) -> None:
        """Market без ключа side → tournament__market."""
        cfg = OmegaConf.create(
            {
                "tournament": {"name": "uel_kz_1"},
                "market": {"family": "winner"},
                "market_spec": {"name": "winner_any"},
            }
        )
        result = _get_mlflow_experiment_name(cfg)
        assert result == "uel_kz_1__winner"
