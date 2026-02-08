"""
Фабрика создания моделей из конфигурации.

Централизует логику инстанцирования моделей, заменяя
хардкодные ``if/elif`` цепочки в trainer.py и predict.py.

Пример::

    from sports_forecast.training.model_factory import ModelFactory
    model = ModelFactory.create_model(cfg.algorithm)
    model.fit(X_train, y_train)
"""

from __future__ import annotations

from typing import Any

from omegaconf import DictConfig

from sports_forecast.training.base import BaseModel, BaseSingleModel
from sports_forecast.training.ensembles.stacking import StackingEnsemble
from sports_forecast.training.models.catboost import CatBoostModel
from sports_forecast.training.models.dummy import DummyModel
from sports_forecast.training.models.lgbm import LGBMModel
from sports_forecast.training.models.logreg import LogRegModel
from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)


class ModelFactory:
    """Фабрика для создания экземпляров моделей на основе конфигурации.

    Centralizes model instantiation logic, replacing hardcoded if/elif chains.
    All models must implement the ``BaseModel`` interface.

    Examples:
        >>> model = ModelFactory.create_model(cfg.algorithm)
        >>> model.fit(X_train, y_train)
        >>> proba = model.predict_proba(X_test)
    """

    @staticmethod
    def create_model(algorithm_cfg: DictConfig) -> BaseModel:
        """Создать экземпляр модели по конфигурации алгоритма.

        Args:
            algorithm_cfg: Конфигурация алгоритма из Hydra
                (должна содержать ``name`` и ``_target_``).

        Returns:
            Экземпляр модели, наследующий BaseModel.

        Raises:
            ValueError: Если тип модели не поддерживается.
        """
        model_name = algorithm_cfg.name
        params = dict(algorithm_cfg.get("params", {}))
        model_target = algorithm_cfg.get("_target_", "")

        logger.debug("ModelFactory: Создаём модель '%s' (target: %s)", model_name, model_target)

        if "dummy" in model_name.lower() or "DummyModel" in model_target:
            return DummyModel(name=model_name, config=algorithm_cfg, params=params)
        if "logreg" in model_name.lower() or "LogRegModel" in model_target:
            return LogRegModel(name=model_name, config=algorithm_cfg, params=params)
        if "catboost" in model_name.lower() or "CatBoostModel" in model_target:
            return CatBoostModel(name=model_name, config=algorithm_cfg, params=params)
        if "lgbm" in model_name.lower() or "LGBMModel" in model_target:
            return LGBMModel(name=model_name, config=algorithm_cfg, params=params)
        if "stacking" in model_name.lower() or "StackingEnsemble" in model_target:
            return ModelFactory._create_stacking_ensemble(algorithm_cfg)

        raise ValueError(
            f"Не удалось определить класс модели для: name={model_name}, target={model_target}"
        )

    @staticmethod
    def _create_stacking_ensemble(algorithm_cfg: DictConfig) -> StackingEnsemble:
        """Создать Stacking Ensemble.

        Base models передаются через CLI/Hydra::

            algorithm=stacking algorithm.base_models=[catboost,lgbm]

        Args:
            algorithm_cfg: Конфигурация алгоритма stacking.

        Returns:
            Экземпляр StackingEnsemble.

        Raises:
            ValueError: Если ``base_models`` не указаны в конфигурации.
        """
        base_model_configs = algorithm_cfg.get("base_models", [])
        if not base_model_configs:
            raise ValueError(
                "Для Stacking Ensemble необходимо указать 'base_models' "
                "в конфигурации алгоритма. "
                "Например: algorithm=stacking algorithm.base_models=[catboost,lgbm]"
            )

        _name_to_cls: dict[str, type[BaseSingleModel]] = {
            "dummy": DummyModel,
            "logreg": LogRegModel,
            "catboost": CatBoostModel,
            "lgbm": LGBMModel,
        }

        base_models: list[BaseSingleModel] = []
        for base_model_name in base_model_configs:
            cls = _name_to_cls.get(base_model_name)
            if cls is None:
                raise ValueError(f"Неизвестный тип базовой модели для Stacking: {base_model_name}")
            base_model_cfg: dict[str, Any] = {"name": base_model_name, "params": {}}
            base_models.append(cls(name=base_model_name, config=base_model_cfg))
            logger.debug("  Добавлена базовая модель: %s", base_model_name)

        # Мета-модель
        meta_model_cfg = algorithm_cfg.meta_model
        meta_model_type = meta_model_cfg.get("type", "logreg")
        meta_model_params = dict(meta_model_cfg.get("params", {}))

        if meta_model_type == "logreg":
            meta_model = LogRegModel(
                name="meta_logreg",
                config=meta_model_cfg,
                params=meta_model_params,
            )
        else:
            raise ValueError(f"Неизвестный тип мета-модели: {meta_model_type}")

        n_splits = algorithm_cfg.get("tscv_n_splits", 4)
        stacking = StackingEnsemble(
            name="stacking",
            base_models=base_models,
            meta_model=meta_model,
            config=algorithm_cfg,
            n_splits=n_splits,
        )
        logger.info(
            "Stacking Ensemble создан: %d базовых моделей + %s",
            len(base_models),
            meta_model_type,
        )
        return stacking
