"""Композиция правил рынка и способа оценки вероятностей моделью."""

from __future__ import annotations

from omegaconf import DictConfig, OmegaConf


_OVERRIDABLE = ("data_format", "target_source_key", "target_name", "feature_prefixes")


def effective_market_spec(cfg: DictConfig) -> DictConfig:
    """Вернуть market-spec с форматом и target выбранной стратегии модели."""
    strategy = cfg.get("model_strategy")
    if strategy is None or strategy.get("name") == "standard":
        return cfg.market_spec
    if cfg.market_spec.get("name") != "winner_1x2":
        raise ValueError("Нестандартная model_strategy разрешена только для winner_1x2")
    overrides = {key: strategy[key] for key in _OVERRIDABLE if key in strategy}
    return OmegaConf.merge(cfg.market_spec, OmegaConf.create(overrides))


def model_strategy_name(cfg: DictConfig) -> str:
    """Вернуть стабильное имя стратегии для путей и MLflow identity."""
    strategy = cfg.get("model_strategy")
    return str(strategy.get("name", "standard")) if strategy is not None else "standard"
