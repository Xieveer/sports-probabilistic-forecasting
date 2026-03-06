"""A/B Testing — сравнение моделей Shadow vs Prod.

Логика:
    1. Batch pipeline материализует предсказания от обеих моделей
       (prod + shadow) для одних и тех же матчей.
    2. После получения результатов (resolve) — вычисляем метрики
       для каждой модели.
    3. Если shadow побеждает по ключевой метрике → автоматическое
       промотирование или уведомление.

Использование::

    comparator = ModelComparator(tournament="uel_kz_1", market_spec="winner")
    result = comparator.compare(resolved_df)
    if result.should_promote_shadow:
        promote_shadow()
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score

from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)


@dataclass
class ABTestResult:
    """Результат A/B сравнения двух моделей.

    Attributes:
        tournament: Название турнира.
        market_spec: Название market_spec.
        prod_metrics: Метрики prod-модели.
        shadow_metrics: Метрики shadow/challenger модели.
        n_common_matches: Количество матчей с предсказаниями обеих моделей.
        primary_metric: Метрика для принятия решения.
        prod_value: Значение метрики prod.
        shadow_value: Значение метрики shadow.
        should_promote_shadow: Рекомендация промотировать shadow.
        improvement_pct: Процент улучшения shadow vs prod.
    """

    tournament: str
    market_spec: str
    prod_metrics: dict[str, float]
    shadow_metrics: dict[str, float]
    n_common_matches: int
    primary_metric: str
    prod_value: float
    shadow_value: float
    should_promote_shadow: bool
    improvement_pct: float
    metadata: dict[str, Any] = field(default_factory=dict)


def _compute_model_metrics(
    y_true: np.ndarray,
    y_pred: np.ndarray,
) -> dict[str, float]:
    """Вычислить ML-метрики для одной модели.

    Args:
        y_true: Фактические результаты.
        y_pred: Предсказанные вероятности.

    Returns:
        Словарь ML-метрик.
    """
    metrics: dict[str, float] = {}

    try:
        metrics["logloss"] = float(log_loss(y_true, y_pred))
    except Exception:
        metrics["logloss"] = float("inf")

    try:
        metrics["auc"] = float(roc_auc_score(y_true, y_pred))
    except Exception:
        metrics["auc"] = 0.0

    try:
        metrics["brier"] = float(brier_score_loss(y_true, y_pred))
    except Exception:
        metrics["brier"] = float("inf")

    y_class = (y_pred >= 0.5).astype(int)
    metrics["accuracy"] = float(np.mean(y_true == y_class))

    return metrics


class ModelComparator:
    """Сравнивает prod и shadow модели на реальных результатах.

    Args:
        tournament: Название турнира.
        market_spec: Название market_spec.
        primary_metric: Метрика для принятия решения (``"logloss"``, ``"auc"``).
        direction: ``"minimize"`` для logloss/brier, ``"maximize"`` для auc.
        min_improvement_pct: Минимальный % улучшения для промотирования.
        min_samples: Минимальное количество матчей для сравнения.

    Examples:
        >>> comparator = ModelComparator("uel_kz_1", "winner")
        >>> result = comparator.compare_predictions(
        ...     y_true, prod_preds, shadow_preds
        ... )
        >>> if result.should_promote_shadow:
        ...     promote()
    """

    def __init__(
        self,
        tournament: str = "unknown",
        market_spec: str = "unknown",
        primary_metric: str = "logloss",
        direction: str = "minimize",
        min_improvement_pct: float = 5.0,
        min_samples: int = 50,
    ) -> None:
        self.tournament = tournament
        self.market_spec = market_spec
        self.primary_metric = primary_metric
        self.direction = direction
        self.min_improvement_pct = min_improvement_pct
        self.min_samples = min_samples

    def compare_predictions(
        self,
        y_true: np.ndarray,
        prod_predictions: np.ndarray,
        shadow_predictions: np.ndarray,
    ) -> ABTestResult:
        """Сравнить предсказания prod и shadow моделей.

        Args:
            y_true: Фактические результаты (0/1).
            prod_predictions: Предсказания prod модели.
            shadow_predictions: Предсказания shadow/challenger модели.

        Returns:
            ABTestResult с рекомендацией.
        """
        n = len(y_true)

        if n < self.min_samples:
            logger.warning(
                "A/B test: недостаточно данных (%d < %d). Пропускаем.",
                n,
                self.min_samples,
            )
            return ABTestResult(
                tournament=self.tournament,
                market_spec=self.market_spec,
                prod_metrics={},
                shadow_metrics={},
                n_common_matches=n,
                primary_metric=self.primary_metric,
                prod_value=0.0,
                shadow_value=0.0,
                should_promote_shadow=False,
                improvement_pct=0.0,
                metadata={"reason": "insufficient_data"},
            )

        prod_metrics = _compute_model_metrics(y_true, prod_predictions)
        shadow_metrics = _compute_model_metrics(y_true, shadow_predictions)

        prod_value = prod_metrics.get(self.primary_metric, 0.0)
        shadow_value = shadow_metrics.get(self.primary_metric, 0.0)

        # Вычисляем improvement
        if self.direction == "minimize":
            # Для logloss/brier: меньше = лучше
            if prod_value > 0:
                improvement_pct = (prod_value - shadow_value) / prod_value * 100
            else:
                improvement_pct = 0.0
            is_better = shadow_value < prod_value
        else:
            # Для auc: больше = лучше
            if prod_value > 0:
                improvement_pct = (shadow_value - prod_value) / prod_value * 100
            else:
                improvement_pct = 0.0
            is_better = shadow_value > prod_value

        should_promote = is_better and improvement_pct >= self.min_improvement_pct

        logger.info("=" * 60)
        logger.info("A/B TEST: %s / %s", self.tournament, self.market_spec)
        logger.info("  Prod   %s: %.4f", self.primary_metric, prod_value)
        logger.info("  Shadow %s: %.4f", self.primary_metric, shadow_value)
        logger.info("  Improvement: %.1f%% (%s)", improvement_pct, self.direction)
        logger.info("  Recommendation: %s", "PROMOTE" if should_promote else "KEEP PROD")
        logger.info("  Matches compared: %d", n)
        logger.info("=" * 60)

        return ABTestResult(
            tournament=self.tournament,
            market_spec=self.market_spec,
            prod_metrics=prod_metrics,
            shadow_metrics=shadow_metrics,
            n_common_matches=n,
            primary_metric=self.primary_metric,
            prod_value=prod_value,
            shadow_value=shadow_value,
            should_promote_shadow=should_promote,
            improvement_pct=round(improvement_pct, 2),
        )
