"""
Сборка списков rolling-контекстов из библиотеки и конфига турнира/спорта.

Библиотека: ``conf/features/generators/rolling/context_library.yaml``.
Активные имена: ``rolling_context_names`` в ``conf/sport/*.yaml`` (мержится в tournament).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from omegaconf import DictConfig, ListConfig, OmegaConf

from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)

_CONTEXT_LIBRARY_PATH = (
    Path(__file__).resolve().parents[2] / "conf/features/generators/rolling/context_library.yaml"
)


@lru_cache(maxsize=1)
def load_rolling_context_library() -> tuple[tuple[str, ...], dict[str, dict[str, Any]]]:
    """Загрузить canonical_order и definitions из YAML."""
    if not _CONTEXT_LIBRARY_PATH.is_file():
        raise FileNotFoundError(f"Rolling context library not found: {_CONTEXT_LIBRARY_PATH}")
    with _CONTEXT_LIBRARY_PATH.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    order = tuple(raw.get("canonical_order") or [])
    definitions = raw.get("definitions") or {}
    if not order:
        raise ValueError("context_library.yaml: canonical_order is empty")
    if not definitions:
        raise ValueError("context_library.yaml: definitions is empty")
    # Normalise definitions to plain dicts
    out_defs: dict[str, dict[str, Any]] = {}
    for name, spec in definitions.items():
        if not isinstance(spec, dict):
            raise TypeError(f"context '{name}': expected mapping, got {type(spec)}")
        out_defs[str(name)] = dict(spec)
    return order, out_defs


def _tournament_rolling_names(tournament_cfg: Any) -> list[str] | None:
    """Вернуть rolling_context_names из конфига турнира или None."""
    if tournament_cfg is None:
        return None
    if isinstance(tournament_cfg, (dict, DictConfig)):
        names = tournament_cfg.get("rolling_context_names")
    else:
        names = getattr(tournament_cfg, "rolling_context_names", None)
    if names is None:
        return None
    if isinstance(names, (list, tuple, ListConfig)):
        return [str(x) for x in names]
    raise TypeError(f"rolling_context_names must be a list, got {type(names)}")


def _sort_by_canonical(names: list[str], canonical_order: tuple[str, ...]) -> list[str]:
    rank = {n: i for i, n in enumerate(canonical_order)}
    return sorted(names, key=lambda x: rank.get(x, 10_000))


def _build_ewm_context(
    name: str,
    spec: dict[str, Any],
    *,
    compute_diff: bool,
) -> dict[str, Any]:
    if spec.get("h2h"):
        return {"name": name, "keys": list(spec["keys"]), "h2h": True}
    ctx: dict[str, Any] = {
        "name": name,
        "keys": list(spec["keys"]),
        "players": list(spec.get("players", ["pl", "opp"])),
        "compute_diff": compute_diff,
    }
    return ctx


def _build_count_context(name: str, spec: dict[str, Any]) -> dict[str, Any]:
    if spec.get("h2h"):
        return {"name": name, "keys": list(spec["keys"]), "h2h": True}
    return {
        "name": name,
        "keys": list(spec["keys"]),
        "players": list(spec.get("players", ["pl", "opp"])),
    }


def expand_rolling_generators_inplace(
    features_cfg: dict[str, Any],
    tournament_cfg: Any = None,
) -> None:
    """
    Для генераторов с ``context_source: library`` подставить ``contexts`` из библиотеки.

    Мутирует ``features_cfg["generators"]`` in-place. Удаляет ``context_source`` после сборки.

    Args:
        features_cfg: конфиг features (после ``OmegaConf.to_container``).
        tournament_cfg: узел tournament из Hydra (sport даёт ``rolling_context_names``).
    """
    gens = features_cfg.get("generators")
    if not isinstance(gens, dict):
        return

    canonical_order, definitions = load_rolling_context_library()
    requested = _tournament_rolling_names(tournament_cfg)
    if requested is None:
        enabled = list(canonical_order)
        logger.debug(
            "rolling_contexts: rolling_context_names не заданы, используется полный набор (%d)",
            len(enabled),
        )
    else:
        unknown = [n for n in requested if n not in definitions]
        if unknown:
            raise ValueError(
                f"rolling_context_names содержит неизвестные контексты: {unknown}. "
                f"Допустимые: {list(definitions.keys())}"
            )
        enabled = _sort_by_canonical(list(requested), canonical_order)
        logger.info(
            "rolling_contexts: активные контексты (%d): %s",
            len(enabled),
            enabled,
        )

    for gen_key in ("ewm_diff", "ewm_total", "count"):
        gen = gens.get(gen_key)
        if not isinstance(gen, dict):
            continue
        if gen.get("context_source") != "library":
            continue

        contexts: list[dict[str, Any]] = []
        for name in enabled:
            spec = definitions[name]
            if gen_key == "ewm_diff":
                contexts.append(_build_ewm_context(name, spec, compute_diff=True))
            elif gen_key == "ewm_total":
                contexts.append(_build_ewm_context(name, spec, compute_diff=False))
            else:
                contexts.append(_build_count_context(name, spec))

        gen["contexts"] = contexts
        del gen["context_source"]


def materialize_features_config(
    features_cfg: DictConfig | dict[str, Any],
    tournament_cfg: Any = None,
) -> dict[str, Any]:
    """
    Преобразовать конфиг фичей в plain dict и разрешить rolling library.

    Используется перед ``FeaturePipeline``, когда нужен доступ к ``tournament_cfg``.
    """
    if isinstance(features_cfg, DictConfig):
        out = OmegaConf.to_container(features_cfg, resolve=True)
    else:
        out = dict(features_cfg)
    if not isinstance(out, dict):
        raise TypeError(f"features_cfg must resolve to dict, got {type(out)}")
    expand_rolling_generators_inplace(out, tournament_cfg=tournament_cfg)
    return out
