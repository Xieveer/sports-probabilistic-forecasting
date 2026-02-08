"""
Betting Simulator для валуйных ставок.

Этот модуль симулирует ставки на спортивные события на основе предсказанных вероятностей
и реальных коэффициентов букмекеров, вычисляя метрики прибыльности.

Examples:
    >>> simulator = BettingSimulator(
    ...     initial_bankroll=1000,
    ...     stake_strategy="flat",
    ...     flat_stake=10,
    ...     min_value_threshold=0.05,
    ... )
    >>> metrics = simulator.simulate(y_true, y_pred_proba, odds)
    >>> print(f"ROI: {metrics['roi']:.2%}, Profit: ${metrics['profit']:.2f}")
"""

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)


@dataclass
class BettingMetrics:
    """Метрики betting симуляции."""

    roi: float  # Return on Investment (%)
    profit: float  # Чистая прибыль/убыток
    total_staked: float  # Общая сумма поставленных денег
    num_bets: int  # Количество ставок
    num_wins: int  # Количество выигрышных ставок
    win_rate: float  # Процент выигрышных ставок
    avg_odds: float  # Средний коэффициент
    avg_value: float  # Средний expected value
    sharpe_ratio: float  # Sharpe ratio (риск-adjusted return)
    max_drawdown: float  # Максимальная просадка
    final_bankroll: float  # Финальный размер банка


class BettingSimulator:
    """
    Симулятор ставок на валуйные события.

    Вычисляет Expected Value (EV) для каждого события и делает ставки только
    на события с положительным EV (где модель оценивает вероятность выше, чем букмекер).

    Args:
        initial_bankroll: Начальный размер банка.
        stake_strategy: Стратегия ставок ('flat' или 'kelly').
        flat_stake: Размер ставки для flat strategy.
        kelly_fraction: Доля Kelly для kelly strategy (по умолчанию 0.25 = quarter Kelly).
        min_value_threshold: Минимальный порог EV для ставки (например, 0.05 = 5% EV).
        max_stake_fraction: Максимальная доля банка на одну ставку (для защиты).

    Examples:
        >>> simulator = BettingSimulator(
        ...     initial_bankroll=1000,
        ...     stake_strategy="flat",
        ...     flat_stake=10,
        ...     min_value_threshold=0.05,
        ... )
        >>> # y_true: реальные исходы (0/1)
        >>> # y_pred_proba: предсказанные вероятности [0.0-1.0]
        >>> # odds: букмекерские коэффициенты [1.5, 2.0, ...]
        >>> metrics = simulator.simulate(y_true, y_pred_proba, odds)
        >>> print(f"ROI: {metrics.roi:.2%}")
    """

    def __init__(
        self,
        initial_bankroll: float = 1000.0,
        stake_strategy: Literal["flat", "kelly"] = "flat",
        flat_stake: float = 10.0,
        kelly_fraction: float = 0.25,
        min_value_threshold: float = 0.05,
        max_stake_fraction: float = 0.1,
    ):
        self.initial_bankroll = initial_bankroll
        self.stake_strategy = stake_strategy
        self.flat_stake = flat_stake
        self.kelly_fraction = kelly_fraction
        self.min_value_threshold = min_value_threshold
        self.max_stake_fraction = max_stake_fraction

        logger.info(
            "BettingSimulator инициализирован: bankroll=%.2f, strategy=%s, min_value=%.2f%%",
            initial_bankroll,
            stake_strategy,
            min_value_threshold * 100,
        )

    def calculate_expected_value(self, predicted_prob: float, odds: float) -> tuple[float, float]:
        """
        Вычислить Expected Value (EV) и долю Kelly.

        EV = p * (odds - 1) - (1 - p)
        где p - предсказанная вероятность, odds - коэффициент букмекера.

        Kelly fraction = (p * odds - 1) / (odds - 1)

        Args:
            predicted_prob: Предсказанная вероятность события [0.0-1.0].
            odds: Букмекерский коэффициент (например, 2.5).

        Returns:
            Tuple (expected_value, kelly_fraction).

        Examples:
            >>> simulator = BettingSimulator()
            >>> ev, kelly = simulator.calculate_expected_value(0.5, 2.2)
            >>> # Если модель даёт 50%, а букмекер 2.2 (implied prob ~45%), есть value!
        """
        if odds <= 1.0:
            return 0.0, 0.0

        # Expected Value: насколько выгодна ставка
        ev = predicted_prob * (odds - 1) - (1 - predicted_prob)

        # Kelly Criterion: оптимальная доля банка для ставки
        kelly = (predicted_prob * odds - 1) / (odds - 1) if odds > 1 else 0.0

        return ev, kelly

    def calculate_stake(self, predicted_prob: float, odds: float, current_bankroll: float) -> float:
        """
        Вычислить размер ставки согласно выбранной стратегии.

        Args:
            predicted_prob: Предсказанная вероятность.
            odds: Коэффициент букмекера.
            current_bankroll: Текущий размер банка.

        Returns:
            Размер ставки в деньгах.
        """
        if self.stake_strategy == "flat":
            stake = self.flat_stake
        elif self.stake_strategy == "kelly":
            _, kelly_fraction = self.calculate_expected_value(predicted_prob, odds)
            # Применяем fractional Kelly для снижения риска
            stake = current_bankroll * kelly_fraction * self.kelly_fraction
        else:
            raise ValueError(f"Неизвестная стратегия: {self.stake_strategy}")

        # Защита: не более max_stake_fraction от банка
        max_stake = current_bankroll * self.max_stake_fraction
        stake = min(stake, max_stake)

        # Защита: не более текущего банка
        stake = min(stake, current_bankroll)

        return max(0.0, stake)

    def simulate(
        self,
        y_true: np.ndarray | pd.Series,
        y_pred_proba: np.ndarray,
        odds: np.ndarray | pd.Series,
    ) -> BettingMetrics:
        """
        Симулировать ставки на всех событиях и вычислить метрики.

        Args:
            y_true: Реальные исходы (0 или 1).
            y_pred_proba: Предсказанные вероятности [0.0-1.0].
            odds: Букмекерские коэффициенты для события.

        Returns:
            BettingMetrics с результатами симуляции.

        Examples:
            >>> y_true = np.array([1, 0, 1, 1, 0])
            >>> y_pred = np.array([0.7, 0.4, 0.6, 0.8, 0.3])
            >>> odds = np.array([2.0, 2.5, 1.8, 1.9, 3.0])
            >>> metrics = simulator.simulate(y_true, y_pred, odds)
            >>> print(f"ROI: {metrics.roi:.2%}, Profit: {metrics.profit:.2f}")
        """
        y_true = np.asarray(y_true)
        y_pred_proba = np.asarray(y_pred_proba)
        odds = np.asarray(odds)

        if len(y_true) != len(y_pred_proba) or len(y_true) != len(odds):
            raise ValueError("y_true, y_pred_proba, odds должны быть одинаковой длины")

        bankroll = self.initial_bankroll
        total_staked = 0.0
        num_bets = 0
        num_wins = 0
        bets_odds = []
        bets_values = []
        bankroll_history = [bankroll]

        logger.info("Начинаю симуляцию ставок на %d событиях", len(y_true))

        for outcome, prob, odd in zip(y_true, y_pred_proba, odds, strict=True):
            # Вычисляем EV
            ev, _ = self.calculate_expected_value(prob, odd)

            # Ставим только если EV > threshold
            if ev <= self.min_value_threshold:
                bankroll_history.append(bankroll)
                continue

            # Вычисляем размер ставки
            stake = self.calculate_stake(prob, odd, bankroll)

            if stake <= 0:
                bankroll_history.append(bankroll)
                continue

            # Делаем ставку
            num_bets += 1
            total_staked += stake
            bets_odds.append(odd)
            bets_values.append(ev)

            # Результат ставки
            if outcome == 1:
                # Выиграли
                profit = stake * (odd - 1)
                bankroll += profit
                num_wins += 1
            else:
                # Проиграли
                bankroll -= stake

            bankroll_history.append(bankroll)

        # Вычисляем метрики
        net_profit = bankroll - self.initial_bankroll
        roi = (net_profit / total_staked * 100) if total_staked > 0 else 0.0
        win_rate = (num_wins / num_bets) if num_bets > 0 else 0.0
        avg_odds = float(np.mean(bets_odds)) if bets_odds else 0.0
        avg_value = float(np.mean(bets_values)) if bets_values else 0.0

        # Sharpe Ratio (упрощённая версия)
        if len(bankroll_history) > 1:
            returns = np.diff(bankroll_history)
            sharpe = (
                (np.mean(returns) / np.std(returns)) * np.sqrt(len(returns))
                if np.std(returns) > 0
                else 0.0
            )
        else:
            sharpe = 0.0

        # Max Drawdown
        peak = self.initial_bankroll
        max_dd = 0.0
        for value in bankroll_history:
            if value > peak:
                peak = value
            dd = (peak - value) / peak if peak > 0 else 0.0
            max_dd = max(max_dd, dd)

        metrics = BettingMetrics(
            roi=roi,
            profit=net_profit,
            total_staked=total_staked,
            num_bets=num_bets,
            num_wins=num_wins,
            win_rate=win_rate,
            avg_odds=avg_odds,
            avg_value=avg_value,
            sharpe_ratio=sharpe,
            max_drawdown=max_dd,
            final_bankroll=bankroll,
        )

        logger.info("Симуляция завершена:")
        logger.info("  Ставок: %d", num_bets)
        logger.info("  Выигрышей: %d (%.1f%%)", num_wins, win_rate * 100)
        logger.info("  ROI: %.2f%%", roi)
        logger.info("  Profit: %.2f", net_profit)
        logger.info("  Final bankroll: %.2f", bankroll)

        return metrics
