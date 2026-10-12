"""Вероятностные метрики для полного исхода 1X2."""

from __future__ import annotations

import numpy as np
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
