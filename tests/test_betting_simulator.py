"""
Тесты для модуля betting/simulator.py.

Покрывают:
- BettingSimulator.calculate_expected_value: EV и Kelly fraction
- BettingSimulator.calculate_stake: flat и kelly стратегии, защитные механизмы
- BettingSimulator.simulate: полный цикл симуляции
- BettingMetrics: корректность метрик (ROI, Sharpe, Max Drawdown)
- Граничные случаи: нет ставок, все выигрыши, все проигрыши
"""

from __future__ import annotations

import numpy as np
import pytest

from sports_forecast.betting.simulator import BettingMetrics, BettingSimulator


# ==================== Fixtures ====================


@pytest.fixture
def flat_simulator() -> BettingSimulator:
    """Flat strategy simulator (stake = 10)."""
    return BettingSimulator(
        initial_bankroll=1000.0,
        stake_strategy="flat",
        flat_stake=10.0,
        min_value_threshold=0.05,
        max_stake_fraction=0.1,
    )


@pytest.fixture
def kelly_simulator() -> BettingSimulator:
    """Kelly strategy simulator."""
    return BettingSimulator(
        initial_bankroll=1000.0,
        stake_strategy="kelly",
        kelly_fraction=0.25,
        min_value_threshold=0.05,
        max_stake_fraction=0.1,
    )


# ==================== Expected Value Tests ====================


class TestExpectedValue:
    """Тесты для calculate_expected_value."""

    def test_positive_ev(self, flat_simulator: BettingSimulator) -> None:
        """Положительный EV: модель даёт вероятность выше implied."""
        # p=0.6, odds=2.2 → implied_prob=0.4545, EV = 0.6*(2.2-1) - 0.4 = 0.32
        ev, kelly = flat_simulator.calculate_expected_value(0.6, 2.2)
        assert ev > 0
        assert kelly > 0

    def test_negative_ev(self, flat_simulator: BettingSimulator) -> None:
        """Отрицательный EV: модель даёт вероятность ниже implied."""
        # p=0.3, odds=2.0 → implied_prob=0.5, EV = 0.3*1 - 0.7 = -0.4
        ev, kelly = flat_simulator.calculate_expected_value(0.3, 2.0)
        assert ev < 0
        assert kelly < 0

    def test_zero_ev_fair_odds(self, flat_simulator: BettingSimulator) -> None:
        """EV ~ 0 при fair odds."""
        # p=0.5, odds=2.0 → EV = 0.5*1 - 0.5 = 0
        ev, kelly = flat_simulator.calculate_expected_value(0.5, 2.0)
        assert abs(ev) < 1e-10

    def test_odds_lte_one(self, flat_simulator: BettingSimulator) -> None:
        """Коэффициент <= 1 → EV=0, kelly=0."""
        ev, kelly = flat_simulator.calculate_expected_value(0.9, 1.0)
        assert ev == 0.0
        assert kelly == 0.0

        ev, kelly = flat_simulator.calculate_expected_value(0.9, 0.5)
        assert ev == 0.0
        assert kelly == 0.0

    def test_high_probability_high_odds(self, flat_simulator: BettingSimulator) -> None:
        """Высокая вероятность + высокие коэффициенты = большой EV."""
        ev, kelly = flat_simulator.calculate_expected_value(0.8, 3.0)
        # EV = 0.8*2 - 0.2 = 1.4
        assert abs(ev - 1.4) < 1e-10
        assert kelly > 0.5


# ==================== Stake Calculation Tests ====================


class TestStakeCalculation:
    """Тесты для calculate_stake."""

    def test_flat_stake(self, flat_simulator: BettingSimulator) -> None:
        """Flat strategy возвращает фиксированный размер ставки."""
        stake = flat_simulator.calculate_stake(0.6, 2.2, 1000.0)
        assert stake == 10.0

    def test_flat_stake_capped_by_bankroll(self, flat_simulator: BettingSimulator) -> None:
        """Ставка не превышает текущий банкролл."""
        # bankroll=5.0, max_stake_fraction=0.1 → max_stake=0.5
        # flat_stake=10 → min(10, 0.5) = 0.5, min(0.5, 5.0) = 0.5
        stake = flat_simulator.calculate_stake(0.6, 2.2, 5.0)
        assert stake == 0.5

    def test_flat_stake_capped_by_max_fraction(self, flat_simulator: BettingSimulator) -> None:
        """Ставка не превышает max_stake_fraction от банка."""
        sim = BettingSimulator(
            initial_bankroll=50.0,
            flat_stake=100.0,  # Больше max_fraction * bankroll
            max_stake_fraction=0.1,
        )
        stake = sim.calculate_stake(0.6, 2.2, 50.0)
        assert stake == 5.0  # 50 * 0.1

    def test_kelly_stake_positive_ev(self, kelly_simulator: BettingSimulator) -> None:
        """Kelly stake: положительный для выгодной ставки."""
        stake = kelly_simulator.calculate_stake(0.6, 2.2, 1000.0)
        assert stake > 0

    def test_kelly_stake_negative_ev(self, kelly_simulator: BettingSimulator) -> None:
        """Kelly stake: 0 для невыгодной ставки."""
        stake = kelly_simulator.calculate_stake(0.3, 2.0, 1000.0)
        assert stake == 0.0

    def test_unknown_strategy_raises(self) -> None:
        """Неизвестная стратегия вызывает ValueError."""
        sim = BettingSimulator(stake_strategy="flat")
        sim.stake_strategy = "martingale"  # type: ignore[assignment]
        with pytest.raises(ValueError, match="Неизвестная стратегия"):
            sim.calculate_stake(0.5, 2.0, 1000.0)


# ==================== Simulate Tests ====================


class TestSimulate:
    """Тесты для полной симуляции."""

    def test_no_bets_low_ev(self, flat_simulator: BettingSimulator) -> None:
        """Нет ставок если EV ниже порога."""
        y_true = np.array([1, 0, 1])
        y_pred = np.array([0.45, 0.45, 0.45])  # Близко к implied, EV < threshold
        odds = np.array([2.0, 2.0, 2.0])

        metrics = flat_simulator.simulate(y_true, y_pred, odds)

        assert metrics.num_bets == 0
        assert metrics.profit == 0.0
        assert metrics.roi == 0.0

    def test_all_wins(self, flat_simulator: BettingSimulator) -> None:
        """Все ставки выиграны → прибыль."""
        y_true = np.array([1, 1, 1])
        y_pred = np.array([0.8, 0.8, 0.8])  # Высокая уверенность
        odds = np.array([2.0, 2.0, 2.0])

        metrics = flat_simulator.simulate(y_true, y_pred, odds)

        assert metrics.num_bets == 3
        assert metrics.num_wins == 3
        assert metrics.profit > 0
        assert metrics.roi > 0
        assert metrics.win_rate == 1.0

    def test_all_losses(self, flat_simulator: BettingSimulator) -> None:
        """Все ставки проиграны → убыток."""
        y_true = np.array([0, 0, 0])
        y_pred = np.array([0.8, 0.8, 0.8])  # Модель была уверена, но ошиблась
        odds = np.array([2.0, 2.0, 2.0])

        metrics = flat_simulator.simulate(y_true, y_pred, odds)

        assert metrics.num_bets == 3
        assert metrics.num_wins == 0
        assert metrics.profit < 0
        assert metrics.roi < 0
        assert metrics.win_rate == 0.0

    def test_mixed_results(self, flat_simulator: BettingSimulator) -> None:
        """Смешанные результаты."""
        y_true = np.array([1, 0, 1, 0, 1])
        y_pred = np.array([0.7, 0.7, 0.7, 0.7, 0.7])
        odds = np.array([2.0, 2.0, 2.0, 2.0, 2.0])

        metrics = flat_simulator.simulate(y_true, y_pred, odds)

        assert metrics.num_bets > 0
        assert isinstance(metrics.roi, float)
        assert isinstance(metrics.sharpe_ratio, float)
        assert 0.0 <= metrics.max_drawdown <= 1.0

    def test_final_bankroll_consistency(self, flat_simulator: BettingSimulator) -> None:
        """final_bankroll = initial_bankroll + profit."""
        y_true = np.array([1, 0, 1])
        y_pred = np.array([0.8, 0.8, 0.8])
        odds = np.array([2.5, 2.5, 2.5])

        metrics = flat_simulator.simulate(y_true, y_pred, odds)

        expected_final = flat_simulator.initial_bankroll + metrics.profit
        assert abs(metrics.final_bankroll - expected_final) < 1e-6

    def test_avg_odds_correct(self, flat_simulator: BettingSimulator) -> None:
        """Средний коэффициент ставок корректен."""
        y_true = np.array([1, 1])
        y_pred = np.array([0.8, 0.8])
        odds = np.array([2.0, 3.0])

        metrics = flat_simulator.simulate(y_true, y_pred, odds)

        if metrics.num_bets == 2:
            assert abs(metrics.avg_odds - 2.5) < 1e-6

    def test_mismatched_lengths_raises(self, flat_simulator: BettingSimulator) -> None:
        """Массивы разной длины вызывают ValueError."""
        y_true = np.array([1, 0])
        y_pred = np.array([0.5, 0.6, 0.7])  # Разная длина
        odds = np.array([2.0, 2.5])

        with pytest.raises(ValueError, match="одинаковой длины"):
            flat_simulator.simulate(y_true, y_pred, odds)

    def test_roi_calculation(self, flat_simulator: BettingSimulator) -> None:
        """ROI = (profit / total_staked) * 100."""
        y_true = np.array([1, 1])
        y_pred = np.array([0.8, 0.8])
        odds = np.array([2.0, 2.0])

        metrics = flat_simulator.simulate(y_true, y_pred, odds)

        if metrics.total_staked > 0:
            expected_roi = (metrics.profit / metrics.total_staked) * 100
            assert abs(metrics.roi - expected_roi) < 1e-6

    def test_max_drawdown_bounds(self, flat_simulator: BettingSimulator) -> None:
        """Max drawdown между 0 и 1."""
        y_true = np.array([0, 0, 1, 0, 1])
        y_pred = np.array([0.7, 0.7, 0.7, 0.7, 0.7])
        odds = np.array([2.0, 2.0, 2.0, 2.0, 2.0])

        metrics = flat_simulator.simulate(y_true, y_pred, odds)

        assert 0.0 <= metrics.max_drawdown <= 1.0


# ==================== BettingMetrics Tests ====================


class TestBettingMetrics:
    """Тесты для структуры BettingMetrics."""

    def test_dataclass_fields(self) -> None:
        """BettingMetrics содержит все необходимые поля."""
        m = BettingMetrics(
            roi=5.0,
            profit=50.0,
            total_staked=1000.0,
            num_bets=100,
            num_wins=55,
            win_rate=0.55,
            avg_odds=1.95,
            avg_value=0.03,
            sharpe_ratio=1.2,
            max_drawdown=0.05,
            final_bankroll=1050.0,
        )
        assert m.roi == 5.0
        assert m.num_bets == 100
        assert m.sharpe_ratio == 1.2
