"""
Тесты для OptunaHyperOptimizer и build_param_space_from_config.

Покрытие:
- Построение param space из конфига (float, int, categorical)
- Создание OptunaHyperOptimizer
- Оптимизация с DummyModel
- Мерж лучших параметров с базовыми
- Обработка ошибок (отсутствие optuna_space, неверный тип)
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock

import pytest
from omegaconf import DictConfig, OmegaConf
from optuna.study import load_study
from optuna.trial import Trial

import optuna
from sports_forecast.training.optimization.optuna_optimizer import (
    OptunaHyperOptimizer,
    build_param_space_from_config,
)


# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture()
def catboost_optuna_space() -> DictConfig:
    """Пространство параметров CatBoost из конфига."""
    return OmegaConf.create(
        {
            "learning_rate": {"type": "float", "low": 0.01, "high": 0.3, "log": True},
            "depth": {"type": "int", "low": 4, "high": 12},
            "iterations": {"type": "int", "low": 100, "high": 500, "step": 100},
        }
    )


@pytest.fixture()
def logreg_optuna_space() -> DictConfig:
    """Пространство параметров LogReg из конфига."""
    return OmegaConf.create(
        {
            "C": {"type": "float", "low": 0.001, "high": 100.0, "log": True},
            "penalty": {"type": "categorical", "choices": ["l1", "l2"]},
        }
    )


@pytest.fixture()
def dummy_algorithm_cfg() -> DictConfig:
    """Конфигурация dummy алгоритма (без optuna_space)."""
    return OmegaConf.create(
        {
            "name": "dummy",
            "_target_": "sports_forecast.training.models.dummy.DummyModel",
            "params": {"strategy": "prior", "random_state": 42},
            "optuna_space": None,
        }
    )


@pytest.fixture()
def logreg_algorithm_cfg() -> DictConfig:
    """Конфигурация logreg алгоритма с optuna_space."""
    return OmegaConf.create(
        {
            "name": "logreg",
            "_target_": "sports_forecast.training.models.logreg.LogRegModel",
            "params": {
                "penalty": "l2",
                "C": 1.0,
                "solver": "saga",
                "max_iter": 100,
                "random_state": 42,
            },
            "optuna_space": {
                "C": {"type": "float", "low": 0.01, "high": 10.0, "log": True},
                "penalty": {"type": "categorical", "choices": ["l1", "l2"]},
            },
        }
    )


@pytest.fixture()
def hyper_cfg() -> DictConfig:
    """Конфигурация гиперпараметрической оптимизации."""
    return OmegaConf.create(
        {
            "strategy": "optuna",
            "enabled": True,
            "n_trials": 3,  # Минимум для тестов
            "timeout": 60,
            "direction": "minimize",
            "metric": "logloss",
            "sampler": {
                "type": "TPESampler",
                "n_startup_trials": 2,
                "multivariate": True,
                "seed": 42,
            },
            "pruner": {
                "type": "MedianPruner",
                "n_startup_trials": 1,
                "n_warmup_steps": 1,
                "interval_steps": 1,
            },
            "verbose": False,
            "show_progress_bar": False,
        }
    )


@pytest.fixture()
def split_cfg() -> DictConfig:
    """Конфигурация split."""
    return OmegaConf.create(
        {
            "tscv_n_splits": 2,
            "test_size": 0.1,
        }
    )


@pytest.fixture()
def _cleanup_optuna_dir():
    """Очистить директорию optuna после тестов."""
    yield
    optuna_dir = Path("optuna")
    if optuna_dir.exists():
        shutil.rmtree(optuna_dir)


# ── Tests: build_param_space_from_config ─────────────────────────────────


class TestBuildParamSpace:
    """Тесты построения param space из конфига."""

    def test_float_params(self, catboost_optuna_space: DictConfig) -> None:
        """Float параметры корректно генерируются."""
        trial = MagicMock(spec=Trial)
        trial.suggest_float.return_value = 0.05
        trial.suggest_int.return_value = 6

        params = build_param_space_from_config(catboost_optuna_space, trial)

        assert "learning_rate" in params
        trial.suggest_float.assert_called_once_with(
            "learning_rate",
            0.01,
            0.3,
            log=True,
        )

    def test_int_params(self, catboost_optuna_space: DictConfig) -> None:
        """Int параметры корректно генерируются."""
        trial = MagicMock(spec=Trial)
        trial.suggest_float.return_value = 0.1
        trial.suggest_int.return_value = 200

        params = build_param_space_from_config(catboost_optuna_space, trial)

        assert "depth" in params
        assert "iterations" in params

        # depth: step=1 (default)
        trial.suggest_int.assert_any_call("depth", 4, 12, step=1)
        # iterations: step=100
        trial.suggest_int.assert_any_call("iterations", 100, 500, step=100)

    def test_categorical_params(self, logreg_optuna_space: DictConfig) -> None:
        """Categorical параметры корректно генерируются."""
        trial = MagicMock(spec=Trial)
        trial.suggest_float.return_value = 1.0
        trial.suggest_categorical.return_value = "l2"

        params = build_param_space_from_config(logreg_optuna_space, trial)

        assert params["penalty"] == "l2"
        trial.suggest_categorical.assert_called_once_with(
            "penalty",
            ["l1", "l2"],
        )

    def test_unsupported_type_raises(self) -> None:
        """Неподдерживаемый тип параметра вызывает ValueError."""
        space = OmegaConf.create(
            {
                "bad_param": {"type": "complex", "low": 0, "high": 1},
            }
        )
        trial = MagicMock(spec=Trial)

        with pytest.raises(ValueError, match="Неподдерживаемый тип"):
            build_param_space_from_config(space, trial)

    def test_all_params_returned(self, catboost_optuna_space: DictConfig) -> None:
        """Все параметры из конфига присутствуют в результате."""
        trial = MagicMock(spec=Trial)
        trial.suggest_float.return_value = 0.1
        trial.suggest_int.return_value = 6

        params = build_param_space_from_config(catboost_optuna_space, trial)

        assert set(params.keys()) == {"learning_rate", "depth", "iterations"}

    def test_empty_space(self) -> None:
        """Пустое пространство возвращает пустой словарь."""
        space = OmegaConf.create({})
        trial = MagicMock(spec=Trial)

        params = build_param_space_from_config(space, trial)

        assert params == {}


# ── Tests: OptunaHyperOptimizer ──────────────────────────────────────────


class TestOptunaHyperOptimizer:
    """Тесты OptunaHyperOptimizer."""

    def test_initialization(
        self,
        logreg_algorithm_cfg: DictConfig,
        hyper_cfg: DictConfig,
        split_cfg: DictConfig,
    ) -> None:
        """Корректная инициализация оптимизатора."""
        optimizer = OptunaHyperOptimizer(
            algorithm_cfg=logreg_algorithm_cfg,
            hyper_cfg=hyper_cfg,
            split_cfg=split_cfg,
        )

        assert optimizer.n_trials == 3
        assert optimizer.metric == "logloss"
        assert optimizer.n_splits == 2
        assert optimizer.direction == "minimize"
        assert "hyper_logreg" in optimizer.study_name

    def test_custom_study_name(
        self,
        logreg_algorithm_cfg: DictConfig,
        hyper_cfg: DictConfig,
    ) -> None:
        """Пользовательское имя study."""
        optimizer = OptunaHyperOptimizer(
            algorithm_cfg=logreg_algorithm_cfg,
            hyper_cfg=hyper_cfg,
            study_name="custom_study",
        )

        assert optimizer.study_name == "custom_study"

    def test_default_split_cfg(
        self,
        logreg_algorithm_cfg: DictConfig,
        hyper_cfg: DictConfig,
    ) -> None:
        """Без split_cfg используется n_splits=4."""
        optimizer = OptunaHyperOptimizer(
            algorithm_cfg=logreg_algorithm_cfg,
            hyper_cfg=hyper_cfg,
            split_cfg=None,
        )

        assert optimizer.n_splits == 4

    def test_missing_optuna_space_raises(
        self,
        dummy_algorithm_cfg: DictConfig,
        hyper_cfg: DictConfig,
        _cleanup_optuna_dir,
    ) -> None:
        """Отсутствие optuna_space вызывает ValueError."""
        import numpy as np
        import pandas as pd

        optimizer = OptunaHyperOptimizer(
            algorithm_cfg=dummy_algorithm_cfg,
            hyper_cfg=hyper_cfg,
        )

        features = pd.DataFrame(np.random.rand(100, 5))
        target = pd.Series(np.random.randint(0, 2, 100))

        with pytest.raises(ValueError, match="optuna_space не задан"):
            optimizer.optimize(features, target)

    @pytest.mark.usefixtures("_cleanup_optuna_dir")
    def test_optimize_returns_merged_params(
        self,
        logreg_algorithm_cfg: DictConfig,
        hyper_cfg: DictConfig,
        split_cfg: DictConfig,
    ) -> None:
        """optimize() возвращает мерженные параметры (base + best)."""
        import numpy as np
        import pandas as pd

        # Создаём данные
        np.random.seed(42)
        features = pd.DataFrame(
            np.random.rand(200, 3),
            columns=["f1", "f2", "f3"],
        )
        target = pd.Series(np.random.randint(0, 2, 200))

        optimizer = OptunaHyperOptimizer(
            algorithm_cfg=logreg_algorithm_cfg,
            hyper_cfg=hyper_cfg,
            split_cfg=split_cfg,
            study_name="test_merge",
        )

        best_params = optimizer.optimize(features, target)

        # Проверяем что базовые параметры сохранились
        assert "solver" in best_params  # из base params
        assert "max_iter" in best_params  # из base params
        assert "random_state" in best_params  # из base params

        # Проверяем что оптимизированные параметры присутствуют
        assert "C" in best_params
        assert "penalty" in best_params

        # C должен быть float в диапазоне [0.01, 10.0]
        assert 0.01 <= best_params["C"] <= 10.0

        # penalty должен быть l1 или l2
        assert best_params["penalty"] in ["l1", "l2"]

    @pytest.mark.usefixtures("_cleanup_optuna_dir")
    def test_optimize_creates_study(
        self,
        logreg_algorithm_cfg: DictConfig,
        hyper_cfg: DictConfig,
        split_cfg: DictConfig,
    ) -> None:
        """optimize() создаёт Optuna study в SQLite."""
        import numpy as np
        import pandas as pd

        np.random.seed(42)
        features = pd.DataFrame(
            np.random.rand(200, 3),
            columns=["f1", "f2", "f3"],
        )
        target = pd.Series(np.random.randint(0, 2, 200))

        study_name = "test_study_creation"
        optimizer = OptunaHyperOptimizer(
            algorithm_cfg=logreg_algorithm_cfg,
            hyper_cfg=hyper_cfg,
            split_cfg=split_cfg,
            study_name=study_name,
        )

        optimizer.optimize(features, target)

        # Проверяем что study существует
        study = load_study(
            study_name=study_name,
            storage=optimizer.storage_url,
        )
        assert len(study.trials) == 3  # n_trials=3


class TestOptunaHyperOptimizerSampler:
    """Тесты конфигурации sampler/pruner."""

    def test_random_sampler(
        self,
        logreg_algorithm_cfg: DictConfig,
    ) -> None:
        """Конфигурация RandomSampler."""
        hyper_cfg = OmegaConf.create(
            {
                "enabled": True,
                "n_trials": 3,
                "direction": "minimize",
                "metric": "logloss",
                "sampler": {"type": "RandomSampler", "seed": 42},
                "pruner": {"type": "MedianPruner"},
            }
        )

        optimizer = OptunaHyperOptimizer(
            algorithm_cfg=logreg_algorithm_cfg,
            hyper_cfg=hyper_cfg,
        )

        assert isinstance(optimizer.sampler, optuna.samplers.RandomSampler)

    def test_tpe_sampler_default(
        self,
        logreg_algorithm_cfg: DictConfig,
    ) -> None:
        """TPESampler используется по умолчанию."""
        hyper_cfg = OmegaConf.create(
            {
                "enabled": True,
                "n_trials": 3,
                "direction": "minimize",
                "metric": "logloss",
                "sampler": {"type": "TPESampler", "seed": 42},
                "pruner": {"type": "MedianPruner"},
            }
        )

        optimizer = OptunaHyperOptimizer(
            algorithm_cfg=logreg_algorithm_cfg,
            hyper_cfg=hyper_cfg,
        )

        assert isinstance(optimizer.sampler, optuna.samplers.TPESampler)

    def test_unknown_sampler_falls_back_to_tpe(
        self,
        logreg_algorithm_cfg: DictConfig,
    ) -> None:
        """Неизвестный sampler fallback'ит на TPE."""
        hyper_cfg = OmegaConf.create(
            {
                "enabled": True,
                "n_trials": 3,
                "direction": "minimize",
                "metric": "logloss",
                "sampler": {"type": "UnknownSampler", "seed": 42},
                "pruner": {"type": "MedianPruner"},
            }
        )

        optimizer = OptunaHyperOptimizer(
            algorithm_cfg=logreg_algorithm_cfg,
            hyper_cfg=hyper_cfg,
        )

        assert isinstance(optimizer.sampler, optuna.samplers.TPESampler)


class TestOptunaTrainerIntegration:
    """Тесты интеграции OptunaHyperOptimizer с trainer."""

    def test_optimize_hyperparams_disabled(self) -> None:
        """_optimize_hyperparams возвращает None когда hyper отключён."""
        from sports_forecast.training.trainer import SingleExperimentRunner

        cfg = OmegaConf.create(
            {
                "hyper": {"enabled": False},
                "algorithm": {
                    "name": "dummy",
                    "_target_": "sports_forecast.training.models.dummy.DummyModel",
                    "params": {"strategy": "prior"},
                    "optuna_space": None,
                },
                "tournament": {"name": "test"},
                "market_spec": {"name": "test"},
                "features": {"name": "basic"},
            }
        )

        runner = SingleExperimentRunner(
            config=cfg,
            project_root=Path(),
        )

        import numpy as np
        import pandas as pd

        features = pd.DataFrame(np.random.rand(50, 3))
        target = pd.Series(np.random.randint(0, 2, 50))

        params, metrics = runner._optimize_hyperparams(features, target, cfg)

        assert params is None
        assert metrics == {}

    def test_optimize_hyperparams_no_space(self) -> None:
        """_optimize_hyperparams возвращает None если нет optuna_space."""
        from sports_forecast.training.trainer import SingleExperimentRunner

        cfg = OmegaConf.create(
            {
                "hyper": {"enabled": True, "n_trials": 3},
                "algorithm": {
                    "name": "dummy",
                    "_target_": "sports_forecast.training.models.dummy.DummyModel",
                    "params": {"strategy": "prior"},
                    "optuna_space": None,
                },
                "tournament": {"name": "test"},
                "market_spec": {"name": "test"},
                "features": {"name": "basic"},
            }
        )

        runner = SingleExperimentRunner(
            config=cfg,
            project_root=Path(),
        )

        import numpy as np
        import pandas as pd

        features = pd.DataFrame(np.random.rand(50, 3))
        target = pd.Series(np.random.randint(0, 2, 50))

        params, metrics = runner._optimize_hyperparams(features, target, cfg)

        assert params is None
        assert metrics == {}

    def test_create_model_with_optimized_params(self) -> None:
        """_create_model корректно мержит оптимизированные параметры."""
        from sports_forecast.training.trainer import SingleExperimentRunner

        cfg = OmegaConf.create(
            {
                "algorithm": {
                    "name": "dummy",
                    "_target_": "sports_forecast.training.models.dummy.DummyModel",
                    "params": {"strategy": "prior", "random_state": 42},
                },
                "tournament": {"name": "test"},
                "market_spec": {"name": "test"},
                "features": {"name": "basic"},
            }
        )

        runner = SingleExperimentRunner(
            config=cfg,
            project_root=Path(),
        )

        optimized_params = {"strategy": "stratified", "random_state": 99}
        model = runner._create_model(cfg.algorithm, optimized_params)

        model_any = cast(Any, model)
        assert model_any.params["strategy"] == "stratified"
        assert model_any.params["random_state"] == 99

    def test_create_model_without_optimized_params(self) -> None:
        """_create_model использует дефолтные параметры без оптимизации."""
        from sports_forecast.training.trainer import SingleExperimentRunner

        cfg = OmegaConf.create(
            {
                "algorithm": {
                    "name": "dummy",
                    "_target_": "sports_forecast.training.models.dummy.DummyModel",
                    "params": {"strategy": "prior", "random_state": 42},
                },
                "tournament": {"name": "test"},
                "market_spec": {"name": "test"},
                "features": {"name": "basic"},
            }
        )

        runner = SingleExperimentRunner(
            config=cfg,
            project_root=Path(),
        )

        model = runner._create_model(cfg.algorithm, None)

        model_any = cast(Any, model)
        assert model_any.params["strategy"] == "prior"
        assert model_any.params["random_state"] == 42


class TestFeatureImportance:
    """Тесты для _get_feature_importance."""

    def test_returns_importance_dataframe(self) -> None:
        """Возвращает DataFrame с feature importance для CatBoost."""
        import numpy as np
        import pandas as pd

        from sports_forecast.training.models.catboost import CatBoostModel
        from sports_forecast.training.trainer import SingleExperimentRunner

        cfg = OmegaConf.create(
            {
                "algorithm": {"name": "catboost"},
                "tournament": {"name": "test"},
                "market_spec": {"name": "test"},
                "features": {"name": "basic"},
            }
        )

        runner = SingleExperimentRunner(config=cfg, project_root=Path())

        model = CatBoostModel(
            name="catboost",
            config={},
            params={"iterations": 10, "depth": 3, "verbose": False},
        )

        np.random.seed(42)
        features = pd.DataFrame(
            {
                "f1": np.random.rand(100),
                "f2": np.random.rand(100),
                "f3": np.random.rand(100),
            }
        )
        target = pd.Series(np.random.randint(0, 2, 100))
        model.fit(features, target)

        importance = runner._get_feature_importance(model)

        assert importance is not None
        assert "feature" in importance.columns
        assert "importance" in importance.columns
        assert len(importance) == 3

    def test_returns_none_for_dummy(self) -> None:
        """Возвращает None для DummyModel (нет feature importance)."""
        import numpy as np
        import pandas as pd

        from sports_forecast.training.models.dummy import DummyModel
        from sports_forecast.training.trainer import SingleExperimentRunner

        cfg = OmegaConf.create(
            {
                "algorithm": {"name": "dummy"},
                "tournament": {"name": "test"},
                "market_spec": {"name": "test"},
                "features": {"name": "basic"},
            }
        )

        runner = SingleExperimentRunner(config=cfg, project_root=Path())

        model = DummyModel(name="dummy", config={}, params={"strategy": "prior"})
        features = pd.DataFrame(np.random.rand(50, 3))
        target = pd.Series(np.random.randint(0, 2, 50))
        model.fit(features, target)

        importance = runner._get_feature_importance(model)

        assert importance is None
