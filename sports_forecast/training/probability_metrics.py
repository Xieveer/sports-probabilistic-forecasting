"""Вероятностные метрики для полного исхода 1X2."""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, log_loss


def evaluate_multiclass_probabilities(
    target: np.ndarray, probabilities: np.ndarray, classes: np.ndarray
) -> dict[str, float]:
    """Оценить П1/Х/П2 с явной привязкой столбцов к `classes_` модели."""
    labels = np.asarray(classes)
    values = np.asarray(probabilities, dtype=float)
    truth = np.asarray(target)
    if values.ndim != 2 or values.shape != (len(truth), 3) or set(labels.tolist()) != {0, 1, 2}:
        raise ValueError("1X2 требует три столбца и классы 0, 1, 2")
    if not np.isfinite(values).all() or (values < 0).any() or (values > 1).any():
        raise ValueError("Вероятности 1X2 выходят за допустимые границы")
    if not np.allclose(values.sum(axis=1), 1.0, atol=1e-6):
        raise ValueError("Вероятности 1X2 не суммируются в единицу")
    if not {int(value) for value in truth} <= {0, 1, 2}:
        raise ValueError("Таргет 1X2 содержит неизвестный класс")
    order = [list(labels).index(label) for label in (0, 1, 2)]
    canonical = values[:, order]
    prediction = canonical.argmax(axis=1)
    one_hot = np.array([[float(int(value) == label) for label in (0, 1, 2)] for value in truth])
    return {
        "logloss": float(log_loss(truth, canonical, labels=[0, 1, 2])),
        "accuracy": float(accuracy_score(truth, prediction)),
        "brier": float(np.mean(np.sum((canonical - one_hot) ** 2, axis=1))),
    }


def compose_long_1x2_probabilities(
    events: pd.DataFrame, win_probabilities: np.ndarray
) -> pd.DataFrame:
    """Собрать П1/Х/П2 из двух оценок победы без нормировки П1 и П2."""
    valid, rejected = audit_long_1x2_probabilities(events, win_probabilities)
    if not rejected.empty:
        raise ValueError(
            "Long 1X2 содержит невалидные вероятности или отрицательный остаток ничьей"
        )
    return valid


def audit_long_1x2_probabilities(
    events: pd.DataFrame, win_probabilities: np.ndarray
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Вернуть валидные распределения и отдельные матчи с невалидными оценками."""
    if not {"id", "is_home"} <= set(events.columns):
        raise ValueError("Long 1X2 требует id и is_home")
    values = np.asarray(win_probabilities, dtype=float)
    if values.ndim != 1 or len(values) != len(events):
        raise ValueError("Число вероятностей не совпадает с long-строками")
    prepared = events[["id", "is_home"]].copy()
    prepared["p_win"] = values
    if prepared["id"].isna().any() or prepared.duplicated(["id", "is_home"]).any():
        raise ValueError("Long 1X2 содержит пустой ID или повторную сторону")
    if not set(prepared["is_home"].unique()) <= {0, 1}:
        raise ValueError("Long 1X2 содержит неизвестную сторону")
    if prepared.groupby("id").size().ne(2).any():
        raise ValueError("Long 1X2 требует обе стороны каждого матча")
    pivot = prepared.pivot(index="id", columns="is_home", values="p_win")
    if not {0, 1} <= set(pivot.columns):
        raise ValueError("Long 1X2 требует обе стороны каждого матча")
    result = pd.DataFrame(index=pivot.index)
    result["home_win"] = pivot[1]
    result["away_win"] = pivot[0]
    result["draw"] = 1.0 - result["home_win"] - result["away_win"]
    invalid = (
        ~np.isfinite(result["home_win"])
        | ~np.isfinite(result["away_win"])
        | ~result["home_win"].between(0, 1)
        | ~result["away_win"].between(0, 1)
    )
    negative_draw = result["draw"] < -1e-10
    rejected = result.loc[invalid | negative_draw, ["home_win", "draw", "away_win"]].copy()
    rejected["reason"] = np.where(
        invalid.loc[rejected.index], "invalid_win_probability", "negative_draw_residual"
    )
    valid = result.loc[~(invalid | negative_draw), ["home_win", "draw", "away_win"]].copy()
    valid["draw"] = valid["draw"].clip(lower=0)
    return valid, rejected
