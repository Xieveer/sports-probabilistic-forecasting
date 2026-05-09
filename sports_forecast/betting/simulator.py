"""
Betting Simulator для валуйных ставок.

Симулирует ставки на спортивные события на основе предсказанных вероятностей
и реальных коэффициентов букмекеров. Возвращает полный набор метрик:

- Volume: n_bets, turnover, coverage
- Profit: profit_units, ROI, avg_profit_per_bet
- Edge/EV: avg_edge, avg_ev, ev_sum, ev_realization
- Risk: max_drawdown, sharpe_like, profit_factor, std_return
- Calibration on selected: brier, logloss, ECE
- Odds-bin breakdown
- Multi-threshold sweep (по edge)

Examples:
    >>> simulator = BettingSimulator(min_edge_threshold=0.05)
    >>> result = simulator.simulate(y_true, y_pred_proba, odds)
    >>> print(f"ROI: {result.roi:.2f}%, Bets: {result.n_bets}")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np
import pandas as pd

from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Dataclasses
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class BettingResult:
    """Полный результат беттинг-симуляции.

    Все «units»-метрики выражены в валюте ставки
    (при flat_stake=1 совпадают с unit-based анализом).

    Attributes:
        n_total_events: Общее кол-во событий с валидными odds.
        n_bets: Кол-во отобранных ставок.
        turnover_units: Оборот (сумма ставок).
        coverage: Доля матчей со ставкой (n_bets / n_total_events).
        profit_units: Чистая прибыль.
        roi: ROI = profit / turnover * 100 (%).
        avg_profit_per_bet: Средний профит на ставку.
        avg_edge: Средний edge (p_model - p_implied) на отобранных.
        avg_ev: Средний EV на отобранных.
        ev_sum_units: Сумма EV * stake на отобранных.
        ev_realization: profit / ev_sum (насколько реализовался EV).
        hit_rate: Доля выигрышей на отобранных.
        num_wins: Кол-во выигрышей.
        max_drawdown_units: Макс. просадка в абсолюте.
        max_drawdown_pct: Макс. просадка в % от пика equity.
        std_return_per_bet: Стд. отклонение return per bet.
        sharpe_like: mean_return / std_return (на ставку, без annualization).
        profit_factor: sum(wins) / abs(sum(losses)).
        avg_odds: Средний коэффициент на отобранных.
        final_bankroll: Финальный размер банка.
        equity_curve: История банкролла.
        bet_mask: Boolean-маска отобранных ставок (длина = n_total_events).
        per_bet_returns: Профит каждой ставки (длина = n_bets).
        event_trace: Построчная таблица симуляции (если запрошено в ``simulate``).
    """

    # ── Volume ───────────────────────────────────────────────────────────
    n_total_events: int
    n_bets: int
    turnover_units: float
    coverage: float

    # ── Profit ───────────────────────────────────────────────────────────
    profit_units: float
    roi: float
    avg_profit_per_bet: float

    # ── Edge / EV ────────────────────────────────────────────────────────
    avg_edge: float
    avg_ev: float
    ev_sum_units: float
    ev_realization: float

    # ── Win / Loss ───────────────────────────────────────────────────────
    hit_rate: float
    num_wins: int

    # ── Risk ─────────────────────────────────────────────────────────────
    max_drawdown_units: float
    max_drawdown_pct: float
    std_return_per_bet: float
    sharpe_like: float
    profit_factor: float

    # ── Averages ─────────────────────────────────────────────────────────
    avg_odds: float
    final_bankroll: float

    # ── Raw data для артефактов ───────────────────────────────────────────
    equity_curve: list[float] = field(repr=False)
    bet_mask: np.ndarray = field(repr=False)
    per_bet_returns: list[float] = field(repr=False)
    event_trace: pd.DataFrame | None = field(default=None, repr=False)


# Backward-compatible alias
BettingMetrics = BettingResult


# ─────────────────────────────────────────────────────────────────────────────
# Simulator
# ─────────────────────────────────────────────────────────────────────────────


class BettingSimulator:
    """Симулятор ставок на валуйные события.

    Отбор ставок по **edge** (model prob минус implied prob): ``p_model - 1/odds``.
    Ставка принимается только если ``edge > min_edge_threshold`` и ``odds > 1``.
    EV по-прежнему считается для Kelly и метрик ``avg_ev`` / ``ev_realization``.

    Args:
        initial_bankroll: Начальный размер банка.
        stake_strategy: Стратегия ставок (``'flat'`` / ``'kelly'``).
        flat_stake: Размер flat-ставки.
        kelly_fraction: Доля Kelly (quarter Kelly = 0.25).
        min_edge_threshold: Минимальный порог edge (в долях вероятности) для ставки.
        max_stake_fraction: Максимальная доля банка на одну ставку.

    Examples:
        >>> sim = BettingSimulator(flat_stake=1.0, min_edge_threshold=0.05)
        >>> result = sim.simulate(y_true, y_pred, odds)
        >>> print(f"ROI: {result.roi:.2f}%")
    """

    def __init__(
        self,
        initial_bankroll: float = 1000.0,
        stake_strategy: Literal["flat", "kelly"] = "flat",
        flat_stake: float = 10.0,
        kelly_fraction: float = 0.25,
        min_edge_threshold: float = 0.05,
        max_stake_fraction: float = 0.1,
    ):
        self.initial_bankroll = initial_bankroll
        self.stake_strategy = stake_strategy
        self.flat_stake = flat_stake
        self.kelly_fraction = kelly_fraction
        self.min_edge_threshold = min_edge_threshold
        self.max_stake_fraction = max_stake_fraction

        logger.info(
            "BettingSimulator инициализирован: bankroll=%.2f, strategy=%s, min_edge=%.4f",
            initial_bankroll,
            stake_strategy,
            min_edge_threshold,
        )

    # ─── EV / Kelly ──────────────────────────────────────────────────────

    def calculate_expected_value(self, predicted_prob: float, odds: float) -> tuple[float, float]:
        """Вычислить Expected Value (EV) и долю Kelly.

        EV = p * (odds - 1) - (1 - p)
        Kelly = (p * odds - 1) / (odds - 1)

        Args:
            predicted_prob: Предсказанная вероятность [0.0-1.0].
            odds: Букмекерский коэффициент.

        Returns:
            ``(expected_value, kelly_fraction)``.
        """
        if odds <= 1.0:
            return 0.0, 0.0
        ev = predicted_prob * (odds - 1) - (1 - predicted_prob)
        kelly = (predicted_prob * odds - 1) / (odds - 1)
        return ev, kelly

    @staticmethod
    def calculate_edge(predicted_prob: float, odds: float) -> float:
        """Edge = p_model - p_implied, где p_implied = 1/odds.

        Для ``odds <= 1`` возвращает ``predicted_prob - 1.0`` (неположительный при p∈[0,1]),
        чтобы такие строки не проходили отбор по положительному порогу edge.

        Args:
            predicted_prob: Предсказанная вероятность [0.0–1.0].
            odds: Коэффициент букмекера.

        Returns:
            Edge в долях вероятности.
        """
        if odds <= 1.0:
            return predicted_prob - 1.0
        return predicted_prob - 1.0 / odds

    def calculate_stake(self, predicted_prob: float, odds: float, current_bankroll: float) -> float:
        """Вычислить размер ставки.

        Args:
            predicted_prob: Предсказанная вероятность.
            odds: Коэффициент букмекера.
            current_bankroll: Текущий размер банка.

        Returns:
            Размер ставки.
        """
        if self.stake_strategy == "flat":
            stake = self.flat_stake
        elif self.stake_strategy == "kelly":
            _, kelly_frac = self.calculate_expected_value(predicted_prob, odds)
            stake = current_bankroll * kelly_frac * self.kelly_fraction
        else:
            raise ValueError(f"Неизвестная стратегия: {self.stake_strategy}")

        max_stake = current_bankroll * self.max_stake_fraction
        stake = min(stake, max_stake, current_bankroll)
        return max(0.0, stake)

    # ─── Main simulation ────────────────────────────────────────────────

    def simulate(
        self,
        y_true: np.ndarray | pd.Series,
        y_pred_proba: np.ndarray,
        odds: np.ndarray | pd.Series,
        *,
        return_event_trace: bool = False,
    ) -> BettingResult:
        """Симулировать ставки и вернуть полный набор метрик.

        Args:
            y_true: Реальные исходы (0 или 1).
            y_pred_proba: Предсказанные вероятности [0.0-1.0].
            odds: Букмекерские коэффициенты.
            return_event_trace: Если ``True``, заполнить ``BettingResult.event_trace``
                построчной таблицей (y_true, p_prob, odds, edge, ставка, профит, …).

        Returns:
            :class:`BettingResult` с полным набором метрик.

        Raises:
            ValueError: Если массивы разной длины.
        """
        y_true = np.asarray(y_true, dtype=float)
        y_pred_proba = np.asarray(y_pred_proba, dtype=float)
        odds = np.asarray(odds, dtype=float)

        if len(y_true) != len(y_pred_proba) or len(y_true) != len(odds):
            raise ValueError("y_true, y_pred_proba, odds должны быть одинаковой длины")

        n_total = len(y_true)
        bankroll = self.initial_bankroll
        equity_curve: list[float] = [bankroll]

        # Per-bet tracking
        bet_mask = np.zeros(n_total, dtype=bool)
        per_bet_returns: list[float] = []
        bets_odds: list[float] = []
        bets_edges: list[float] = []
        bets_evs: list[float] = []
        bets_ev_stakes: list[float] = []  # ev * stake (для ev_sum_units)
        total_staked = 0.0
        num_wins = 0
        trace_rows: list[dict[str, Any]] | None = [] if return_event_trace else None

        for i in range(n_total):
            prob = y_pred_proba[i]
            odd = odds[i]
            outcome = y_true[i]

            ev, _ = self.calculate_expected_value(prob, odd)
            p_implied = float(1.0 / odd) if odd > 1.0 else float("nan")
            edge = self.calculate_edge(prob, odd)

            placed = False
            stake_used = 0.0
            profit_amt = 0.0

            if edge > self.min_edge_threshold:
                stake = self.calculate_stake(prob, odd, bankroll)
                if stake > 0:
                    bet_mask[i] = True
                    placed = True
                    stake_used = float(stake)
                    total_staked += stake

                    bets_edges.append(edge)
                    bets_evs.append(ev)
                    bets_ev_stakes.append(ev * stake)
                    bets_odds.append(odd)

                    if outcome == 1:
                        profit_amt = float(stake * (odd - 1))
                        bankroll += profit_amt
                        num_wins += 1
                    else:
                        profit_amt = float(-stake)
                        bankroll -= stake

                    per_bet_returns.append(profit_amt)

            equity_curve.append(bankroll)

            if trace_rows is not None:
                trace_rows.append(
                    {
                        "sim_step": i,
                        "y_true": int(outcome),
                        "p_prob": float(prob),
                        "odds": float(odd),
                        "p_implied": p_implied,
                        "edge": float(edge),
                        "ev": float(ev),
                        "min_edge_threshold": float(self.min_edge_threshold),
                        "bet_placed": placed,
                        "stake": stake_used,
                        "profit": profit_amt,
                        "bankroll_after": float(bankroll),
                    }
                )

        # ── Aggregate metrics ────────────────────────────────────────────
        n_bets = int(bet_mask.sum())

        # Volume
        turnover = total_staked
        coverage = n_bets / n_total if n_total > 0 else 0.0

        # Profit
        profit = bankroll - self.initial_bankroll
        roi = (profit / turnover * 100) if turnover > 0 else 0.0
        avg_profit_per_bet = profit / n_bets if n_bets > 0 else 0.0

        # Edge / EV
        avg_edge = float(np.mean(bets_edges)) if bets_edges else 0.0
        avg_ev = float(np.mean(bets_evs)) if bets_evs else 0.0
        ev_sum = float(np.sum(bets_ev_stakes)) if bets_ev_stakes else 0.0
        ev_realization = profit / ev_sum if abs(ev_sum) > 1e-9 else 0.0

        # Win / Loss
        hit_rate = num_wins / n_bets if n_bets > 0 else 0.0

        # Risk
        max_dd_units, max_dd_pct = self._compute_drawdown(equity_curve)

        returns_arr = np.array(per_bet_returns, dtype=float) if per_bet_returns else np.array([])
        std_ret = float(np.std(returns_arr)) if len(returns_arr) > 1 else 0.0
        mean_ret = float(np.mean(returns_arr)) if len(returns_arr) > 0 else 0.0
        sharpe = mean_ret / std_ret if std_ret > 1e-9 else 0.0

        # Profit factor = gross_wins / abs(gross_losses)
        wins_sum = float(returns_arr[returns_arr > 0].sum()) if len(returns_arr) > 0 else 0.0
        losses_sum = (
            float(np.abs(returns_arr[returns_arr < 0].sum())) if len(returns_arr) > 0 else 0.0
        )
        profit_factor = (
            wins_sum / losses_sum if losses_sum > 1e-9 else float("inf") if wins_sum > 0 else 0.0
        )

        # Averages
        avg_odds = float(np.mean(bets_odds)) if bets_odds else 0.0

        trace_df = pd.DataFrame(trace_rows) if trace_rows is not None else None

        result = BettingResult(
            n_total_events=n_total,
            n_bets=n_bets,
            turnover_units=turnover,
            coverage=coverage,
            profit_units=profit,
            roi=roi,
            avg_profit_per_bet=avg_profit_per_bet,
            avg_edge=avg_edge,
            avg_ev=avg_ev,
            ev_sum_units=ev_sum,
            ev_realization=ev_realization,
            hit_rate=hit_rate,
            num_wins=num_wins,
            max_drawdown_units=max_dd_units,
            max_drawdown_pct=max_dd_pct,
            std_return_per_bet=std_ret,
            sharpe_like=sharpe,
            profit_factor=profit_factor,
            avg_odds=avg_odds,
            final_bankroll=bankroll,
            equity_curve=equity_curve,
            bet_mask=bet_mask,
            per_bet_returns=per_bet_returns,
            event_trace=trace_df,
        )

        logger.info("Симуляция завершена:")
        logger.info("  Events: %d, Bets: %d (coverage %.1f%%)", n_total, n_bets, coverage * 100)
        logger.info("  ROI: %.2f%%, Profit: %.2f", roi, profit)
        logger.info("  Hit rate: %.1f%%, Avg edge: %.4f", hit_rate * 100, avg_edge)
        logger.info("  Sharpe: %.3f, Profit factor: %.2f", sharpe, profit_factor)
        logger.info("  Max DD: %.2f units (%.2f%%)", max_dd_units, max_dd_pct * 100)

        return result

    # ─── Threshold sweep ─────────────────────────────────────────────────

    def sweep_thresholds(
        self,
        y_true: np.ndarray | pd.Series,
        y_pred_proba: np.ndarray,
        odds: np.ndarray | pd.Series,
        thresholds: list[float] | np.ndarray | None = None,
    ) -> pd.DataFrame:
        """Прогнать отбор по разным порогам edge (unit-based, flat=1).

        Для каждого порога считает: n_bets, roi, profit, ev_realization
        (``ev_realization`` по-прежнему относится к сумме EV отобранных событий).

        Args:
            y_true: Реальные исходы.
            y_pred_proba: Предсказанные вероятности.
            odds: Коэффициенты.
            thresholds: Пороги edge (доли вероятности). По умолчанию 0.00..0.30 с шагом 0.01.

        Returns:
            DataFrame с колонками ``threshold, n_bets, roi, profit_units,
            ev_realization, hit_rate, avg_edge, avg_odds``.
        """
        y_true = np.asarray(y_true, dtype=float)
        y_pred_proba = np.asarray(y_pred_proba, dtype=float)
        odds = np.asarray(odds, dtype=float)

        if thresholds is None:
            thresholds = np.round(np.arange(0.0, 0.31, 0.01), 4).tolist()

        # Pre-compute EV, edge, unit return for every event
        evs = y_pred_proba * (odds - 1) - (1 - y_pred_proba)
        p_implied = np.where(odds > 1.0, 1.0 / odds, 1.0)
        edges = y_pred_proba - p_implied
        # unit return: outcome*(odds-1) - (1-outcome) = outcome*odds - 1
        unit_returns = y_true * (odds - 1) - (1 - y_true)

        rows: list[dict[str, float]] = []
        for thr in thresholds:
            mask = edges > thr
            n_bets = int(mask.sum())
            if n_bets == 0:
                rows.append(
                    {
                        "threshold": thr,
                        "n_bets": 0,
                        "roi": 0.0,
                        "profit_units": 0.0,
                        "ev_realization": 0.0,
                        "hit_rate": 0.0,
                        "avg_edge": 0.0,
                        "avg_odds": 0.0,
                    }
                )
                continue

            sel_returns = unit_returns[mask]
            sel_evs = evs[mask]
            sel_edges = edges[mask]
            sel_odds = odds[mask]
            sel_y = y_true[mask]

            profit = float(sel_returns.sum())
            turnover = float(n_bets)  # flat=1 unit
            ev_sum = float(sel_evs.sum())

            rows.append(
                {
                    "threshold": thr,
                    "n_bets": float(n_bets),
                    "roi": (profit / turnover * 100) if turnover > 0 else 0.0,
                    "profit_units": profit,
                    "ev_realization": profit / ev_sum if abs(ev_sum) > 1e-9 else 0.0,
                    "hit_rate": float(sel_y.sum() / n_bets),
                    "avg_edge": float(sel_edges.mean()),
                    "avg_odds": float(sel_odds.mean()),
                }
            )

        return pd.DataFrame(rows)

    # ─── Odds-bin analysis ───────────────────────────────────────────────

    @staticmethod
    def compute_odds_bin_metrics(
        y_true: np.ndarray,
        _y_pred_proba: np.ndarray,
        odds: np.ndarray,
        bet_mask: np.ndarray,
        bins: list[float] | None = None,
        labels: list[str] | None = None,
    ) -> dict[str, dict[str, float]]:
        """Вычислить метрики по бинам коэффициентов.

        Анализируются только отобранные ставки (``bet_mask=True``).
        Для каждого бина: n_bets, roi, profit_units.

        Args:
            y_true: Реальные исходы.
            y_pred_proba: Предсказанные вероятности.
            odds: Коэффициенты.
            bet_mask: Маска отобранных ставок.
            bins: Границы бинов. По умолчанию ``[1.0, 2.0, 3.0, 5.0, 999.0]``.
            labels: Названия бинов. По умолчанию ``["1_2", "2_3", "3_5", "5_plus"]``.

        Returns:
            Словарь ``{bin_label: {"n_bets": ..., "roi": ..., "profit_units": ...}}``.
        """
        if bins is None:
            bins = [1.0, 2.0, 3.0, 5.0, 999.0]
        if labels is None:
            labels = ["1_2", "2_3", "3_5", "5_plus"]

        y_true = np.asarray(y_true, dtype=float)
        odds = np.asarray(odds, dtype=float)
        bet_mask = np.asarray(bet_mask, dtype=bool)

        # Unit returns (flat=1)
        unit_returns = y_true * (odds - 1) - (1 - y_true)

        result: dict[str, dict[str, float]] = {}
        for i, label in enumerate(labels):
            lo, hi = bins[i], bins[i + 1]
            bin_mask = bet_mask & (odds >= lo) & (odds < hi)
            n = int(bin_mask.sum())
            if n == 0:
                result[label] = {"n_bets": 0, "roi": 0.0, "profit_units": 0.0}
                continue
            profit = float(unit_returns[bin_mask].sum())
            result[label] = {
                "n_bets": float(n),
                "roi": (profit / n * 100),  # flat=1, turnover=n
                "profit_units": profit,
            }
        return result

    # ─── Internal helpers ────────────────────────────────────────────────

    @staticmethod
    def _compute_drawdown(equity_curve: list[float]) -> tuple[float, float]:
        """Вычислить максимальную просадку (абсолют + %).

        Args:
            equity_curve: История банкролла.

        Returns:
            ``(max_dd_units, max_dd_pct)``.
        """
        if len(equity_curve) < 2:
            return 0.0, 0.0

        peak = equity_curve[0]
        max_dd_units = 0.0
        max_dd_pct = 0.0

        for value in equity_curve:
            if value > peak:
                peak = value
            dd_units = peak - value
            dd_pct = dd_units / peak if peak > 0 else 0.0
            if dd_units > max_dd_units:
                max_dd_units = dd_units
            if dd_pct > max_dd_pct:
                max_dd_pct = dd_pct

        return max_dd_units, max_dd_pct
