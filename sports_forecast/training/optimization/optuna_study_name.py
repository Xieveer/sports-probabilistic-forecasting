"""Имя Optuna study: суффикс по сплиту и объёму данных.

SQLite-хранилище Optuna использует ``load_if_exists=True``. Если имя study
не меняется при смене holdout / train_seasons / размера inner train, новые
trials накладываются на старые — ``best_trial`` может относиться к другому
распределению данных. Суффикс строится из детерминированного payload и
укорачивается до безопасного для путей идентификатора.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from omegaconf import DictConfig, OmegaConf


def _to_jsonable(obj: Any) -> Any:
    """Преобразовать значение в JSON-сериализуемый вид (для стабильного hash)."""
    if OmegaConf.is_config(obj):
        return OmegaConf.to_container(obj, resolve=True)
    return obj


def build_optuna_study_suffix(cfg: DictConfig, inner_train_rows: int) -> str:
    """Построить суффикс имени Optuna study по конфигу и объёму inner train.

    В payload входят параметры, влияющие на матрицу ``train_features`` /
    TSCV, которую видит objective. При их изменении получается новый SQLite
    файл study (новое имя), старые прогоны не смешиваются с новыми.

    Опционально: ``hyper.optuna_study_tag`` — произвольная строка; меняя её,
    можно принудительно начать новый study при неизменном остальном конфиге.

    Args:
        cfg: Полная Hydra-конфигурация эксперимента.
        inner_train_rows: Число строк, передаваемых в Optuna (inner train).

    Returns:
        Короткая строка ``d`` + 12 hex символов SHA-256 (буквы нижнего регистра).
    """
    payload: dict[str, Any] = {
        "inner_train_rows": int(inner_train_rows),
    }

    if (
        hasattr(cfg, "tournament")
        and cfg.tournament is not None
        and hasattr(cfg.tournament, "train_eval_split")
        and not OmegaConf.is_missing(cfg.tournament, "train_eval_split")
    ):
        te = cfg.tournament.train_eval_split
        payload["train_eval_split"] = _to_jsonable(te)

    if hasattr(cfg, "split") and cfg.split is not None:
        payload["split"] = _to_jsonable(cfg.split)

    if hasattr(cfg, "features") and cfg.features is not None:
        payload["features_name"] = str(cfg.features.get("name", ""))

    hyper = cfg.get("hyper")
    if hyper is not None:
        tag = hyper.get("optuna_study_tag")
        if tag is not None and str(tag).strip():
            payload["optuna_study_tag"] = str(tag).strip()
        # Метрика objective меняет ranking — отдельный study
        payload["hyper_metric"] = str(hyper.get("metric", "logloss"))
        sampler = hyper.get("sampler")
        if OmegaConf.is_config(sampler) or isinstance(sampler, dict):
            sc = _to_jsonable(sampler)
            if isinstance(sc, dict) and "seed" in sc:
                payload["sampler_seed"] = sc["seed"]

    raw = json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
    return f"d{digest}"


def build_optuna_study_name(
    tournament: str,
    market_spec: str,
    algorithm: str,
    cfg: DictConfig,
    inner_train_rows: int,
) -> str:
    """Полное имя study: базовая часть + суффикс данных/сплита.

    Args:
        tournament: Имя турнира.
        market_spec: Имя market_spec.
        algorithm: Имя алгоритма (как в конфиге).
        cfg: Hydra-конфигурация.
        inner_train_rows: Размер выборки для Optuna.

    Returns:
        Строка вида ``nhl_train__winner_withOT__catboost_reg__dabc123def456``.
    """
    suffix = build_optuna_study_suffix(cfg, inner_train_rows)
    return f"{tournament}__{market_spec}__{algorithm}__{suffix}"
