"""
Тесты для модуля валидации конфигурации.

Покрывают:
- validate_experiment_config: валидация полного эксперимента
- get_data_path: получение пути к данным
- get_allowed_lines: получение допустимых линий
- check_line_allowed: проверка допустимости линии
"""

from __future__ import annotations

from pathlib import Path

import pytest
from omegaconf import DictConfig

from sports_forecast.config.validation import (
    ConfigValidationError,
    check_line_allowed,
    get_allowed_lines,
    get_data_path,
)


# ==================== Fixtures ====================


@pytest.fixture
def tournament_cfg() -> DictConfig:
    """Минимальный валидный tournament config."""
    return DictConfig(
        {
            "name": "uel_kz_1",
            "sport": "cyberhockey",
            "data": {
                "processed_dir": "data/processed/uel_kz_1",
                "formats": {
                    "long": "train_long.parquet",
                    "wide": "train_wide.parquet",
                },
            },
            "allowed_market_specs": {
                "winner": {"specs": ["winner"]},
                "total": {
                    "lines": [3.5, 4.5, 5.5, 6.5, 7.5, 8.5, 9.5],
                    "specs": ["total_over", "total_under"],
                },
            },
        }
    )


@pytest.fixture
def valid_cfg(tournament_cfg: DictConfig) -> DictConfig:
    """Полный валидный config для эксперимента."""
    return DictConfig(
        {
            "tournament": tournament_cfg,
            "market": {"family": "total"},
            "market_spec": {
                "name": "total_over",
                "data_format": "wide",
                "line": 6.5,
                "target_source_key": "total_sum",
            },
            "algorithm": {
                "name": "catboost",
                "_target_": "sports_forecast.training.models.catboost.CatBoostModel",
                "params": {},
            },
            "features": {"name": "basic", "generators": []},
        }
    )


# ==================== get_data_path Tests ====================


class TestGetDataPath:
    """Тесты для get_data_path."""

    def test_long_format(self, tournament_cfg: DictConfig) -> None:
        """Правильный путь для long format."""
        path = get_data_path(tournament_cfg, "long")
        assert path == Path("data/processed/uel_kz_1/train_long.parquet")

    def test_wide_format(self, tournament_cfg: DictConfig) -> None:
        """Правильный путь для wide format."""
        path = get_data_path(tournament_cfg, "wide")
        assert path == Path("data/processed/uel_kz_1/train_wide.parquet")

    def test_invalid_format_raises(self, tournament_cfg: DictConfig) -> None:
        """ValueError для неизвестного формата."""
        with pytest.raises(ValueError, match="data_format должен быть"):
            get_data_path(tournament_cfg, "csv")


# ==================== get_allowed_lines Tests ====================


class TestGetAllowedLines:
    """Тесты для get_allowed_lines."""

    def test_total_lines(self, tournament_cfg: DictConfig) -> None:
        """Получение допустимых линий для total."""
        lines = get_allowed_lines(tournament_cfg, "total")
        assert lines == [3.5, 4.5, 5.5, 6.5, 7.5, 8.5, 9.5]

    def test_winner_no_lines(self, tournament_cfg: DictConfig) -> None:
        """Winner market не имеет линий."""
        lines = get_allowed_lines(tournament_cfg, "winner")
        assert lines == []

    def test_unknown_market_family(self, tournament_cfg: DictConfig) -> None:
        """Несуществующий market family возвращает пустой список."""
        lines = get_allowed_lines(tournament_cfg, "handicap")
        assert lines == []

    def test_no_allowed_market_specs(self) -> None:
        """Турнир без allowed_market_specs возвращает пустой список."""
        cfg = DictConfig({"name": "test"})
        lines = get_allowed_lines(cfg, "total")
        assert lines == []


# ==================== check_line_allowed Tests ====================


class TestCheckLineAllowed:
    """Тесты для check_line_allowed."""

    def test_allowed_line(self, tournament_cfg: DictConfig) -> None:
        """Допустимая линия возвращает True."""
        assert check_line_allowed(tournament_cfg, "total", 6.5) is True

    def test_disallowed_line(self, tournament_cfg: DictConfig) -> None:
        """Недопустимая линия возвращает False."""
        assert check_line_allowed(tournament_cfg, "total", 15.5) is False

    def test_no_restrictions(self) -> None:
        """Без ограничений — всегда True."""
        cfg = DictConfig({"name": "test"})
        assert check_line_allowed(cfg, "total", 999.0) is True


# ==================== validate_experiment_config Tests ====================


class TestValidateExperimentConfig:
    """Тесты для validate_experiment_config."""

    def test_valid_config_passes(self, valid_cfg: DictConfig, tmp_path: Path) -> None:
        """Валидный конфиг не вызывает ошибок (файл данных мокаем)."""
        # Создаём файл данных чтобы валидация пути прошла
        data_dir = tmp_path / "data" / "processed" / "uel_kz_1"
        data_dir.mkdir(parents=True)
        (data_dir / "train_wide.parquet").touch()

        from sports_forecast.config.validation import validate_experiment_config

        # Не должно выбросить исключение
        validate_experiment_config(valid_cfg, tmp_path)

    def test_missing_tournament_raises(self, valid_cfg: DictConfig, tmp_path: Path) -> None:
        """Отсутствие tournament вызывает ошибку."""
        from sports_forecast.config.validation import validate_experiment_config

        del valid_cfg["tournament"]
        with pytest.raises(ConfigValidationError, match="tournament.name обязателен"):
            validate_experiment_config(valid_cfg, tmp_path)

    def test_missing_market_raises(self, valid_cfg: DictConfig, tmp_path: Path) -> None:
        """Отсутствие market вызывает ошибку."""
        from sports_forecast.config.validation import validate_experiment_config

        del valid_cfg["market"]
        with pytest.raises(ConfigValidationError, match="market.family обязателен"):
            validate_experiment_config(valid_cfg, tmp_path)

    def test_invalid_market_family_raises(self, valid_cfg: DictConfig, tmp_path: Path) -> None:
        """Невалидный market family вызывает ошибку."""
        from sports_forecast.config.validation import validate_experiment_config

        valid_cfg.market.family = "unknown"
        with pytest.raises(ConfigValidationError, match="market.family должен быть одним из"):
            validate_experiment_config(valid_cfg, tmp_path)

    def test_total_without_line_raises(self, valid_cfg: DictConfig, tmp_path: Path) -> None:
        """Total market без line вызывает ошибку."""
        from omegaconf import MISSING

        from sports_forecast.config.validation import validate_experiment_config

        valid_cfg.market_spec.line = MISSING
        with pytest.raises(ConfigValidationError, match="market_spec.line обязателен"):
            validate_experiment_config(valid_cfg, tmp_path)

    def test_invalid_data_format_raises(self, valid_cfg: DictConfig, tmp_path: Path) -> None:
        """Невалидный data_format вызывает ошибку."""
        from sports_forecast.config.validation import validate_experiment_config

        valid_cfg.market_spec.data_format = "csv"
        with pytest.raises(ConfigValidationError, match="data_format должен быть"):
            validate_experiment_config(valid_cfg, tmp_path)

    def test_missing_algorithm_raises(self, valid_cfg: DictConfig, tmp_path: Path) -> None:
        """Отсутствие algorithm вызывает ошибку."""
        from sports_forecast.config.validation import validate_experiment_config

        del valid_cfg["algorithm"]
        with pytest.raises(ConfigValidationError, match="algorithm config обязателен"):
            validate_experiment_config(valid_cfg, tmp_path)

    def test_missing_features_raises(self, valid_cfg: DictConfig, tmp_path: Path) -> None:
        """Отсутствие features вызывает ошибку."""
        from sports_forecast.config.validation import validate_experiment_config

        del valid_cfg["features"]
        with pytest.raises(ConfigValidationError, match="features config обязателен"):
            validate_experiment_config(valid_cfg, tmp_path)

    def test_disallowed_line_raises(self, valid_cfg: DictConfig, tmp_path: Path) -> None:
        """Недопустимая линия для турнира вызывает ошибку."""
        from sports_forecast.config.validation import validate_experiment_config

        valid_cfg.market_spec.line = 99.5
        with pytest.raises(ConfigValidationError, match="Line 99.5 не допустима"):
            validate_experiment_config(valid_cfg, tmp_path)

    def test_data_file_not_found_raises(self, valid_cfg: DictConfig, tmp_path: Path) -> None:
        """Отсутствие файла данных вызывает ошибку."""
        from sports_forecast.config.validation import validate_experiment_config

        # tmp_path не содержит файлов данных
        with pytest.raises(ConfigValidationError, match="Файл данных не найден"):
            validate_experiment_config(valid_cfg, tmp_path)


class TestApplyTournamentDefaultBookmaker:
    """R26: NHL → the_odds_api при дефолтном fonbet из корня config."""

    def test_nhl_train_replaces_fonbet(self) -> None:
        from omegaconf import OmegaConf

        from sports_forecast.config.validation import apply_tournament_default_bookmaker

        cfg = OmegaConf.create(
            {
                "tournament": {"name": "nhl_train"},
                "bookmaker": {
                    "name": "fonbet",
                    "market_keys": {"winner_home": "1"},
                    "side_keys": {"h": "1", "a": "2"},
                },
            }
        )
        apply_tournament_default_bookmaker(cfg)
        assert cfg.bookmaker.name == "the_odds_api"
        assert "synthetic_odds_raw" in cfg.bookmaker

    def test_explicit_non_fonbet_unchanged(self) -> None:
        from omegaconf import OmegaConf

        from sports_forecast.config.validation import apply_tournament_default_bookmaker

        cfg = OmegaConf.create(
            {
                "tournament": {"name": "nhl_train"},
                "bookmaker": {"name": "custom", "market_keys": {}},
            }
        )
        apply_tournament_default_bookmaker(cfg)
        assert cfg.bookmaker.name == "custom"

    def test_non_nhl_unchanged(self) -> None:
        from omegaconf import OmegaConf

        from sports_forecast.config.validation import apply_tournament_default_bookmaker

        cfg = OmegaConf.create(
            {
                "tournament": {"name": "uel_kz_1"},
                "bookmaker": {"name": "fonbet"},
            }
        )
        apply_tournament_default_bookmaker(cfg)
        assert cfg.bookmaker.name == "fonbet"
