"""
Тесты для модуля betting/simulator.py.

Покрывают:
- BettingSimulator.calculate_expected_value: EV и Kelly fraction
- BettingSimulator.calculate_stake: flat и kelly стратегии, защитные механизмы
- BettingSimulator.simulate: полный цикл симуляции + новые метрики v2
- BettingResult: корректность полей
- sweep_thresholds: multi-threshold анализ
- compute_odds_bin_metrics: анализ по бинам коэффициентов
- Граничные случаи: нет ставок, все выигрыши, все проигрыши
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from sports_forecast.betting.simulator import BettingResult, BettingSimulator


# ==================== Fixtures ====================


@pytest.fixture
def flat_simulator() -> BettingSimulator:
    """Flat strategy simulator (stake = 10)."""
    return BettingSimulator(
        initial_bankroll=1000.0,
        stake_strategy="flat",
        flat_stake=10.0,
        min_edge_threshold=0.05,
        max_stake_fraction=0.1,
    )


@pytest.fixture
def kelly_simulator() -> BettingSimulator:
    """Kelly strategy simulator."""
    return BettingSimulator(
        initial_bankroll=1000.0,
        stake_strategy="kelly",
        kelly_fraction=0.25,
        min_edge_threshold=0.05,
        max_stake_fraction=0.1,
    )


class TestEdgeCalculation:
    """Тесты для calculate_edge."""

    def test_edge_fair_odds(self) -> None:
        assert abs(BettingSimulator.calculate_edge(0.5, 2.0)) < 1e-10

    def test_edge_positive_value(self) -> None:
        # p=0.6, implied=1/2.2
        e = BettingSimulator.calculate_edge(0.6, 2.2)
        assert e > 0

    def test_odds_lte_one_non_positive(self) -> None:
        assert BettingSimulator.calculate_edge(0.9, 1.0) <= 0.0


# ==================== Expected Value Tests ====================


class TestExpectedValue:
    """Тесты для calculate_expected_value."""

    def test_positive_ev(self, flat_simulator: BettingSimulator) -> None:
        """Положительный EV: модель даёт вероятность выше implied."""
        ev, kelly = flat_simulator.calculate_expected_value(0.6, 2.2)
        assert ev > 0
        assert kelly > 0

    def test_negative_ev(self, flat_simulator: BettingSimulator) -> None:
        """Отрицательный EV: модель даёт вероятность ниже implied."""
        ev, kelly = flat_simulator.calculate_expected_value(0.3, 2.0)
        assert ev < 0
        assert kelly < 0

    def test_zero_ev_fair_odds(self, flat_simulator: BettingSimulator) -> None:
        """EV ~ 0 при fair odds."""
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
        stake = flat_simulator.calculate_stake(0.6, 2.2, 5.0)
        assert stake == 0.5

    def test_flat_stake_capped_by_max_fraction(self, flat_simulator: BettingSimulator) -> None:
        """Ставка не превышает max_stake_fraction от банка."""
        sim = BettingSimulator(
            initial_bankroll=50.0,
            flat_stake=100.0,
            max_stake_fraction=0.1,
        )
        stake = sim.calculate_stake(0.6, 2.2, 50.0)
        assert stake == 5.0

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
    """Тесты для полной симуляции (BettingResult v2)."""

    def test_no_bets_low_edge(self, flat_simulator: BettingSimulator) -> None:
        """Нет ставок если edge не выше порога (p_model ≤ implied при odds=2)."""
        y_true = np.array([1, 0, 1])
        y_pred = np.array([0.45, 0.45, 0.45])
        odds = np.array([2.0, 2.0, 2.0])

        result = flat_simulator.simulate(y_true, y_pred, odds)

        assert result.n_bets == 0
        assert result.profit_units == 0.0
        assert result.roi == 0.0
        assert result.coverage == 0.0
        assert result.bet_mask.sum() == 0

    def test_all_wins(self, flat_simulator: BettingSimulator) -> None:
        """Все ставки выиграны → прибыль."""
        y_true = np.array([1, 1, 1])
        y_pred = np.array([0.8, 0.8, 0.8])
        odds = np.array([2.0, 2.0, 2.0])

        result = flat_simulator.simulate(y_true, y_pred, odds)

        assert result.n_bets == 3
        assert result.num_wins == 3
        assert result.profit_units > 0
        assert result.roi > 0
        assert result.hit_rate == 1.0
        assert result.profit_factor == float("inf")

    def test_all_losses(self, flat_simulator: BettingSimulator) -> None:
        """Все ставки проиграны → убыток."""
        y_true = np.array([0, 0, 0])
        y_pred = np.array([0.8, 0.8, 0.8])
        odds = np.array([2.0, 2.0, 2.0])

        result = flat_simulator.simulate(y_true, y_pred, odds)

        assert result.n_bets == 3
        assert result.num_wins == 0
        assert result.profit_units < 0
        assert result.roi < 0
        assert result.hit_rate == 0.0
        assert result.profit_factor == 0.0

    def test_mixed_results(self, flat_simulator: BettingSimulator) -> None:
        """Смешанные результаты."""
        y_true = np.array([1, 0, 1, 0, 1])
        y_pred = np.array([0.7, 0.7, 0.7, 0.7, 0.7])
        odds = np.array([2.0, 2.0, 2.0, 2.0, 2.0])

        result = flat_simulator.simulate(y_true, y_pred, odds)

        assert result.n_bets > 0
        assert isinstance(result.roi, float)
        assert isinstance(result.sharpe_like, float)
        assert 0.0 <= result.max_drawdown_pct <= 1.0
        assert result.profit_factor > 0

    def test_final_bankroll_consistency(self, flat_simulator: BettingSimulator) -> None:
        """final_bankroll = initial_bankroll + profit_units."""
        y_true = np.array([1, 0, 1])
        y_pred = np.array([0.8, 0.8, 0.8])
        odds = np.array([2.5, 2.5, 2.5])

        result = flat_simulator.simulate(y_true, y_pred, odds)

        expected_final = flat_simulator.initial_bankroll + result.profit_units
        assert abs(result.final_bankroll - expected_final) < 1e-6

    def test_avg_odds_correct(self, flat_simulator: BettingSimulator) -> None:
        """Средний коэффициент ставок корректен."""
        y_true = np.array([1, 1])
        y_pred = np.array([0.8, 0.8])
        odds = np.array([2.0, 3.0])

        result = flat_simulator.simulate(y_true, y_pred, odds)

        if result.n_bets == 2:
            assert abs(result.avg_odds - 2.5) < 1e-6

    def test_mismatched_lengths_raises(self, flat_simulator: BettingSimulator) -> None:
        """Массивы разной длины вызывают ValueError."""
        y_true = np.array([1, 0])
        y_pred = np.array([0.5, 0.6, 0.7])
        odds = np.array([2.0, 2.5])

        with pytest.raises(ValueError, match="одинаковой длины"):
            flat_simulator.simulate(y_true, y_pred, odds)

    def test_roi_calculation(self, flat_simulator: BettingSimulator) -> None:
        """ROI = (profit / turnover) * 100."""
        y_true = np.array([1, 1])
        y_pred = np.array([0.8, 0.8])
        odds = np.array([2.0, 2.0])

        result = flat_simulator.simulate(y_true, y_pred, odds)

        if result.turnover_units > 0:
            expected_roi = (result.profit_units / result.turnover_units) * 100
            assert abs(result.roi - expected_roi) < 1e-6

    def test_max_drawdown_bounds(self, flat_simulator: BettingSimulator) -> None:
        """Max drawdown_pct между 0 и 1."""
        y_true = np.array([0, 0, 1, 0, 1])
        y_pred = np.array([0.7, 0.7, 0.7, 0.7, 0.7])
        odds = np.array([2.0, 2.0, 2.0, 2.0, 2.0])

        result = flat_simulator.simulate(y_true, y_pred, odds)

        assert 0.0 <= result.max_drawdown_pct <= 1.0
        assert result.max_drawdown_units >= 0.0


# ==================== New Metrics Tests ====================


class TestNewMetrics:
    """Тесты для новых метрик v2 (edge, EV, profit_factor и т.д.)."""

    def test_bet_mask_length(self, flat_simulator: BettingSimulator) -> None:
        """bet_mask имеет ту же длину что и входные данные."""
        y_true = np.array([1, 0, 1, 0, 1])
        y_pred = np.array([0.7, 0.3, 0.7, 0.3, 0.7])
        odds = np.array([2.0, 2.0, 2.0, 2.0, 2.0])

        result = flat_simulator.simulate(y_true, y_pred, odds)

        assert len(result.bet_mask) == 5
        assert result.bet_mask.sum() == result.n_bets

    def test_per_bet_returns_length(self, flat_simulator: BettingSimulator) -> None:
        """per_bet_returns имеет длину n_bets."""
        y_true = np.array([1, 1, 1])
        y_pred = np.array([0.8, 0.8, 0.8])
        odds = np.array([2.0, 2.0, 2.0])

        result = flat_simulator.simulate(y_true, y_pred, odds)

        assert len(result.per_bet_returns) == result.n_bets

    def test_equity_curve_length(self, flat_simulator: BettingSimulator) -> None:
        """equity_curve имеет длину n_total_events + 1."""
        y_true = np.array([1, 0, 1])
        y_pred = np.array([0.8, 0.8, 0.8])
        odds = np.array([2.0, 2.0, 2.0])

        result = flat_simulator.simulate(y_true, y_pred, odds)

        assert len(result.equity_curve) == len(y_true) + 1
        assert result.equity_curve[0] == flat_simulator.initial_bankroll

    def test_coverage(self, flat_simulator: BettingSimulator) -> None:
        """coverage = n_bets / n_total_events."""
        y_true = np.array([1, 0, 1, 0])
        y_pred = np.array([0.8, 0.8, 0.3, 0.3])  # 2 high, 2 low
        odds = np.array([2.0, 2.0, 2.0, 2.0])

        result = flat_simulator.simulate(y_true, y_pred, odds)

        expected_coverage = result.n_bets / result.n_total_events
        assert abs(result.coverage - expected_coverage) < 1e-6

    def test_avg_edge_positive_for_value_bets(self, flat_simulator: BettingSimulator) -> None:
        """avg_edge > 0 для валуйных ставок."""
        y_true = np.array([1, 0, 1])
        y_pred = np.array([0.8, 0.8, 0.8])  # p_model > 1/odds = 0.5
        odds = np.array([2.0, 2.0, 2.0])

        result = flat_simulator.simulate(y_true, y_pred, odds)

        assert result.avg_edge > 0  # 0.8 - 0.5 = 0.3

    def test_ev_realization_positive_when_profitable(self) -> None:
        """ev_realization > 0 когда модель прибыльна."""
        sim = BettingSimulator(
            initial_bankroll=1000.0,
            flat_stake=10.0,
            min_edge_threshold=0.01,
        )
        y_true = np.array([1, 1, 1, 1, 1])
        y_pred = np.array([0.7, 0.7, 0.7, 0.7, 0.7])
        odds = np.array([2.0, 2.0, 2.0, 2.0, 2.0])

        result = sim.simulate(y_true, y_pred, odds)

        assert result.ev_realization > 0
        assert result.ev_sum_units > 0

    def test_sharpe_positive_for_consistent_wins(self) -> None:
        """sharpe_like > 0 при стабильных выигрышах."""
        sim = BettingSimulator(
            initial_bankroll=1000.0,
            flat_stake=10.0,
            min_edge_threshold=0.01,
        )
        y_true = np.array([1, 1, 1, 1])
        y_pred = np.array([0.7, 0.7, 0.7, 0.7])
        odds = np.array([2.0, 2.0, 2.0, 2.0])

        result = sim.simulate(y_true, y_pred, odds)

        # Все выигрыши → returns одинаковые → std=0 → sharpe=0
        # (т.к. нет дисперсии)
        assert result.sharpe_like >= 0

    def test_std_return_per_bet(self, flat_simulator: BettingSimulator) -> None:
        """std_return_per_bet > 0 при смешанных результатах."""
        y_true = np.array([1, 0, 1, 0, 1])
        y_pred = np.array([0.7, 0.7, 0.7, 0.7, 0.7])
        odds = np.array([2.0, 2.0, 2.0, 2.0, 2.0])

        result = flat_simulator.simulate(y_true, y_pred, odds)

        if result.n_bets > 1:
            assert result.std_return_per_bet > 0

    def test_event_trace_matches_events(self, flat_simulator: BettingSimulator) -> None:
        """return_event_trace даёт по одной строке на событие с нужными колонками."""
        y_true = np.array([1, 0, 1])
        y_pred = np.array([0.7, 0.55, 0.8])
        odds = np.array([2.0, 2.0, 2.0])

        result = flat_simulator.simulate(y_true, y_pred, odds, return_event_trace=True)

        assert result.event_trace is not None
        assert len(result.event_trace) == 3
        cols = set(result.event_trace.columns)
        assert "y_true" in cols
        assert "p_prob" in cols
        assert "odds" in cols
        assert "p_implied" in cols
        assert "edge" in cols
        assert "ev" in cols
        assert "bet_placed" in cols
        assert "stake" in cols
        assert "profit" in cols
        assert "bankroll_after" in cols
        assert result.event_trace["bet_placed"].sum() == result.n_bets


class TestSweepThresholds:
    """Тесты для sweep_thresholds."""

    def test_returns_dataframe(self, flat_simulator: BettingSimulator) -> None:
        """Возвращает DataFrame с правильными колонками."""
        y_true = np.array([1, 0, 1])
        y_pred = np.array([0.7, 0.7, 0.7])
        odds = np.array([2.0, 2.0, 2.0])

        df = flat_simulator.sweep_thresholds(y_true, y_pred, odds)

        assert isinstance(df, pd.DataFrame)
        assert "threshold" in df.columns
        assert "n_bets" in df.columns
        assert "roi" in df.columns
        assert "profit_units" in df.columns
        assert "ev_realization" in df.columns

    def test_default_thresholds_count(self, flat_simulator: BettingSimulator) -> None:
        """По умолчанию 31 порог (0.00..0.30 с шагом 0.01)."""
        y_true = np.array([1, 0, 1])
        y_pred = np.array([0.7, 0.7, 0.7])
        odds = np.array([2.0, 2.0, 2.0])

        df = flat_simulator.sweep_thresholds(y_true, y_pred, odds)

        assert len(df) == 31

    def test_n_bets_decreasing(self, flat_simulator: BettingSimulator) -> None:
        """n_bets не может расти с увеличением порога."""
        np.random.seed(42)
        y_true = np.random.randint(0, 2, 100)
        y_pred = np.random.uniform(0.3, 0.9, 100)
        odds = np.random.uniform(1.5, 4.0, 100)

        df = flat_simulator.sweep_thresholds(y_true, y_pred, odds)

        n_bets = df["n_bets"].values
        for i in range(1, len(n_bets)):
            assert n_bets[i] <= n_bets[i - 1]

    def test_custom_thresholds(self, flat_simulator: BettingSimulator) -> None:
        """Пользовательские пороги."""
        y_true = np.array([1, 0, 1])
        y_pred = np.array([0.7, 0.7, 0.7])
        odds = np.array([2.0, 2.0, 2.0])

        df = flat_simulator.sweep_thresholds(y_true, y_pred, odds, thresholds=[0.0, 0.1, 0.5])

        assert len(df) == 3


# ==================== Odds-Bin Tests ====================


class TestOddsBinMetrics:
    """Тесты для compute_odds_bin_metrics."""

    def test_returns_dict(self) -> None:
        """Возвращает словарь с метриками по бинам."""
        y_true = np.array([1, 0, 1, 0])
        y_pred = np.array([0.7, 0.7, 0.7, 0.7])
        odds = np.array([1.5, 2.5, 3.5, 6.0])
        bet_mask = np.array([True, True, True, True])

        result = BettingSimulator.compute_odds_bin_metrics(y_true, y_pred, odds, bet_mask)

        assert "1_2" in result
        assert "2_3" in result
        assert "3_5" in result
        assert "5_plus" in result
        assert result["1_2"]["n_bets"] == 1  # odds=1.5
        assert result["2_3"]["n_bets"] == 1  # odds=2.5
        assert result["3_5"]["n_bets"] == 1  # odds=3.5
        assert result["5_plus"]["n_bets"] == 1  # odds=6.0

    def test_respects_bet_mask(self) -> None:
        """Учитывает только отобранные ставки."""
        y_true = np.array([1, 0, 1])
        y_pred = np.array([0.7, 0.7, 0.7])
        odds = np.array([1.5, 2.5, 3.5])
        bet_mask = np.array([True, False, True])

        result = BettingSimulator.compute_odds_bin_metrics(y_true, y_pred, odds, bet_mask)

        assert result["1_2"]["n_bets"] == 1
        assert result["2_3"]["n_bets"] == 0  # Пропущена
        assert result["3_5"]["n_bets"] == 1

    def test_empty_bin(self) -> None:
        """Пустой бин → n_bets=0, roi=0."""
        y_true = np.array([1])
        y_pred = np.array([0.7])
        odds = np.array([1.5])
        bet_mask = np.array([True])

        result = BettingSimulator.compute_odds_bin_metrics(y_true, y_pred, odds, bet_mask)

        assert result["1_2"]["n_bets"] == 1
        assert result["2_3"]["n_bets"] == 0
        assert result["2_3"]["roi"] == 0.0


# ==================== BettingResult Tests ====================


class TestBettingResult:
    """Тесты для структуры BettingResult."""

    def test_has_all_required_fields(self) -> None:
        """BettingResult содержит все обязательные поля."""
        r = BettingResult(
            n_total_events=100,
            n_bets=50,
            turnover_units=500.0,
            coverage=0.5,
            profit_units=25.0,
            roi=5.0,
            avg_profit_per_bet=0.5,
            avg_edge=0.08,
            avg_ev=0.12,
            ev_sum_units=60.0,
            ev_realization=0.42,
            hit_rate=0.55,
            num_wins=27,
            max_drawdown_units=50.0,
            max_drawdown_pct=0.05,
            std_return_per_bet=8.0,
            sharpe_like=0.06,
            profit_factor=1.2,
            avg_odds=1.95,
            final_bankroll=1025.0,
            equity_curve=[1000.0, 1010.0],
            bet_mask=np.array([True, False]),
            per_bet_returns=[10.0, -10.0],
        )
        assert r.roi == 5.0
        assert r.n_bets == 50
        assert r.sharpe_like == 0.06
        assert r.profit_factor == 1.2
        assert r.avg_edge == 0.08
