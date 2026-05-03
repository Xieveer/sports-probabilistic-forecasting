"""
Спорт-осознанная композиция узла ``generators`` для FeaturePipeline (R29).

Сливает пресет из Hydra (``conf/features/*.yaml``) с группами из ``feature_pipeline``
в ``conf/sport/*.yaml`` и опциональными ``feature_pipeline_overrides`` в
``conf/tournament/*.yaml``. См. ``docs/cursor/context/feature_pipeline_composition.md``.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping, MutableMapping
from pathlib import Path
from typing import Any

import yaml
from omegaconf import DictConfig, OmegaConf

from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)

_PROJECT_CONF = Path(__file__).resolve().parents[2] / "conf"

# Ключи генераторов, относящиеся к группам optional-пакета (не к пресетному каркасу).
GROUP_NHL_BOXSCORE_KEYS: tuple[str, ...] = (
    "nhl_schedule",
    "nhl_standings",
    "nhl_roster",
)
GROUP_STREAK_KEYS: tuple[str, ...] = ("streak",)

_NHL_BOXSCORE_YAML_PATHS: tuple[Path, ...] = (
    _PROJECT_CONF / "features/generators/schedule/nhl.yaml",
    _PROJECT_CONF / "features/generators/standings/nhl.yaml",
    _PROJECT_CONF / "features/generators/roster/nhl.yaml",
)
_STREAK_YAML_PATH: Path = _PROJECT_CONF / "features/generators/streak/default.yaml"

# Дефолт групп, если в merge турнира нет ``feature_pipeline`` но задан ``sport``.
_FALLBACK_SPORT_GROUPS: dict[str, dict[str, bool]] = {
    "ice_hockey": {"nhl_boxscore": True, "streak": True},
    "cyberhockey": {"nhl_boxscore": False, "streak": False},
    "table_tennis": {"nhl_boxscore": False, "streak": False},
    "football": {"nhl_boxscore": False, "streak": False},
    "basketball": {"nhl_boxscore": False, "streak": False},
}

# Порядок пре-генераторов и ранних генераторов (остальные — хвост в стабильном порядке).
_CANONICAL_HEAD_ORDER: tuple[str, ...] = (
    "time",
    "nhl_schedule",
    "nhl_standings",
    "nhl_roster",
    "form",
    "streak",
)


def _read_yaml_mapping(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"feature_pipeline: fragment not found: {path}")
    with path.open(encoding="utf-8") as f:
        loaded = yaml.safe_load(f)
    if not isinstance(loaded, dict):
        raise TypeError(f"feature_pipeline: expected mapping in {path}, got {type(loaded)}")
    return dict(loaded)


def _load_nhl_boxscore_generators() -> dict[str, Any]:
    out: dict[str, Any] = {}
    for p in _NHL_BOXSCORE_YAML_PATHS:
        frag = _read_yaml_mapping(p)
        for k, v in frag.items():
            if k in out:
                raise ValueError(f"feature_pipeline: duplicate generator key {k!r} in {p}")
            out[k] = copy.deepcopy(v)
    return out


def _load_streak_generator() -> dict[str, Any]:
    frag = _read_yaml_mapping(_STREAK_YAML_PATH)
    if "streak" not in frag:
        raise KeyError(f"feature_pipeline: expected 'streak' root key in {_STREAK_YAML_PATH}")
    return {"streak": copy.deepcopy(frag["streak"])}


def _get_sport_name(tournament_cfg: Any) -> str | None:
    if tournament_cfg is None:
        return None
    if isinstance(tournament_cfg, dict):
        s = tournament_cfg.get("sport")
    elif isinstance(tournament_cfg, DictConfig):
        s = OmegaConf.select(tournament_cfg, "sport")
    else:
        s = getattr(tournament_cfg, "sport", None)
    if s is None:
        return None
    return str(s)


def _select_subcfg(tournament_cfg: Any, key: str) -> Any | None:
    if tournament_cfg is None:
        return None
    if isinstance(tournament_cfg, dict):
        return tournament_cfg.get(key)
    if isinstance(tournament_cfg, DictConfig):
        return OmegaConf.select(tournament_cfg, key)
    return getattr(tournament_cfg, key, None)


def _groups_dict_from_node(node: Any) -> dict[str, bool]:
    if node is None:
        return {}
    if OmegaConf.is_config(node):
        node = OmegaConf.to_container(node, resolve=True)
    if not isinstance(node, Mapping):
        return {}
    out: dict[str, bool] = {}
    for k, v in node.items():
        ks = str(k)
        if ks in ("nhl_boxscore", "streak"):
            out[ks] = bool(v)
    return out


def _exclude_list_from_overrides(over_node: Any) -> list[str]:
    if over_node is None:
        return []
    if OmegaConf.is_config(over_node):
        over_node = OmegaConf.to_container(over_node, resolve=True)
    if not isinstance(over_node, Mapping):
        return []
    raw = over_node.get("exclude_generators")
    if raw is None:
        return []
    if not isinstance(raw, (list, tuple)):
        return []
    return [str(x) for x in raw if x is not None]


def _effective_feature_groups(tournament_cfg: Any) -> tuple[dict[str, bool], list[str]]:
    """Вернуть (groups, exclude_generators) после слияния sport → overrides."""
    sport = _get_sport_name(tournament_cfg)
    fp = _select_subcfg(tournament_cfg, "feature_pipeline")
    over = _select_subcfg(tournament_cfg, "feature_pipeline_overrides")

    if sport is not None:
        merged: dict[str, bool] = dict(
            _FALLBACK_SPORT_GROUPS.get(str(sport), {"nhl_boxscore": False, "streak": False})
        )
    else:
        merged = {"nhl_boxscore": False, "streak": False}

    if fp is not None:
        if isinstance(fp, DictConfig):
            gnode = OmegaConf.select(fp, "groups")
        elif isinstance(fp, Mapping):
            gnode = fp.get("groups")
        else:
            gnode = None
        merged.update(_groups_dict_from_node(gnode))

    if over is not None:
        if isinstance(over, DictConfig):
            og = OmegaConf.select(over, "groups")
        elif isinstance(over, Mapping):
            og = over.get("groups")
        else:
            og = None
        merged.update(_groups_dict_from_node(og))

    exclude = _exclude_list_from_overrides(over)
    return merged, exclude


def _should_compose(tournament_cfg: Any) -> bool:
    if tournament_cfg is None:
        return False
    return (
        _get_sport_name(tournament_cfg) is not None
        or _select_subcfg(tournament_cfg, "feature_pipeline") is not None
        or _select_subcfg(tournament_cfg, "feature_pipeline_overrides") is not None
    )


def _reorder_generators(gens: MutableMapping[str, Any]) -> dict[str, Any]:
    """Зафиксировать порядок: time → NHL pre → form → streak → rolling-хвост."""

    def tail_rank(k: str) -> tuple[int, str]:
        if k == "ewm_diff":
            return (0, k)
        if k == "ewm_total":
            return (1, k)
        if k == "count":
            return (2, k)
        if k.startswith("ewm_sport_"):
            return (3, k)
        return (4, k)

    head: list[str] = []
    for name in _CANONICAL_HEAD_ORDER:
        if name in gens:
            head.append(name)
    tail_keys = [k for k in gens if k not in head]
    tail_keys.sort(key=tail_rank)
    ordered = head + tail_keys
    return {k: gens[k] for k in ordered}


def compose_feature_pipeline(
    features_cfg: MutableMapping[str, Any],
    tournament_cfg: Any = None,
) -> None:
    """
    Смержить ``features_cfg['generators']`` с группами NHL/streak согласно спорту и турниру.

    Мутирует ``features_cfg`` in-place. Если ``tournament_cfg`` без sport/feature_pipeline/
    overrides — no-op (совместимость с unit-тестами rolling/EWM).

    Args:
        features_cfg: словарь конфига фичей (после ``OmegaConf.to_container`` или plain dict).
        tournament_cfg: узел турнира Hydra (sport и опции смержены в корень).
    """
    if not _should_compose(tournament_cfg):
        return

    gens = features_cfg.get("generators")
    if not isinstance(gens, MutableMapping):
        return

    groups, exclude_keys = _effective_feature_groups(tournament_cfg)
    sport = _get_sport_name(tournament_cfg)

    # Удалить optional-ключи согласно группам (и лишнее из старых пресетов).
    drop_keys: set[str] = set()
    if not groups.get("nhl_boxscore", False):
        drop_keys.update(GROUP_NHL_BOXSCORE_KEYS)
    if not groups.get("streak", False):
        drop_keys.update(GROUP_STREAK_KEYS)
    drop_keys.update(exclude_keys)

    for k in drop_keys:
        gens.pop(k, None)

    if groups.get("nhl_boxscore", False):
        for k, spec in _load_nhl_boxscore_generators().items():
            if k not in gens:
                gens[k] = copy.deepcopy(spec)

    if groups.get("streak", False):
        streak_payload = _load_streak_generator()
        for k, spec in streak_payload.items():
            if k not in gens:
                gens[k] = copy.deepcopy(spec)

    # Фиксированный порядок вставок для детерминизма логов и рантайма.
    reordered = _reorder_generators(gens)
    gens.clear()
    gens.update(reordered)

    active = list(gens.keys())
    has_tournament_fp_over = (
        _select_subcfg(tournament_cfg, "feature_pipeline_overrides") is not None
    )
    logger.info(
        "feature_pipeline: sport=%s tournament_overrides=%s effective_groups=%s "
        "exclude_generators=%s active=%s",
        sport,
        has_tournament_fp_over,
        groups,
        exclude_keys,
        active,
    )
