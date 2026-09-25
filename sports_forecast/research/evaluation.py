"""Детерминированные минимальные gates Research Evaluator."""

from __future__ import annotations

from sports_forecast.research.contracts import (
    EvaluationDecision,
    EvaluationResult,
    ExperimentResult,
    ResearchGoal,
    ResearchGoalContract,
    ResearchMemory,
)


class EvaluationHarness:
    """Вычисляет допустимое научное решение независимо от Scientist."""

    def evaluate(
        self,
        goal: ResearchGoal,
        result: ExperimentResult,
        memory: ResearchMemory,
    ) -> EvaluationResult:
        """Проверить temporal split, locked holdout и минимальные критерии goal.

        Args:
            goal: Контракт исследовательской цели.
            result: Raw metrics experiment runner.
            memory: Ранее раскрытые knowledge и holdout exposure.

        Returns:
            Детерминированное решение `PASS`, `FAIL` или `INVALID`.
        """
        if not result.temporal_validation:
            return EvaluationResult(
                decision=EvaluationDecision.INVALID,
                reasons=["Эксперимент не подтвердил temporal validation."],
            )
        if result.used_locked_holdout and memory.locked_holdout_revealed:
            return EvaluationResult(
                decision=EvaluationDecision.INVALID,
                reasons=["Locked holdout уже раскрыт и не может быть повторным evidence."],
            )

        missing_metrics: list[str] = []
        if isinstance(goal, ResearchGoalContract):
            criteria = goal.research_acceptance_criteria
            if result.positive_roi_bootstrap_fraction is None:
                missing_metrics.append("Не получена доля positive ROI bootstrap-прогонов.")
            if result.bet_coverage is None:
                missing_metrics.append("Не получена обязательная bet coverage.")
            if result.simulated_profit is None:
                missing_metrics.append("Не получен simulated profit кандидата.")
            if result.baseline_simulated_profit is None:
                missing_metrics.append("Не получен simulated profit baseline.")
            if (
                criteria.require_current_model_profit_superiority
                and result.current_model_simulated_profit is None
            ):
                missing_metrics.append("Не получен simulated profit current model.")
        if goal.min_bootstrap_ci_low is not None and result.bootstrap_ci_low is None:
            missing_metrics.append("Не получена обязательная bootstrap lower bound.")
        if goal.max_concentration is not None and result.max_selection_share is None:
            missing_metrics.append("Не получена обязательная concentration metric.")
        if missing_metrics:
            return EvaluationResult(
                decision=EvaluationDecision.INVALID,
                reasons=missing_metrics,
            )

        reasons: list[str] = []
        if goal.max_log_loss is not None and result.log_loss > goal.max_log_loss:
            reasons.append("LogLoss не достиг целевого порога.")
        if goal.max_log_loss is not None and result.log_loss >= result.baseline_log_loss:
            reasons.append("Нет улучшения относительно baseline LogLoss.")
        if goal.min_roi is not None and result.roi < goal.min_roi:
            reasons.append("ROI не достиг целевого порога.")
        if result.number_of_bets < goal.min_bets:
            reasons.append("Недостаточно ставок для economic evidence.")
        if goal.max_drawdown is not None and result.max_drawdown > goal.max_drawdown:
            reasons.append("Max drawdown превысил допустимый предел.")
        if (
            goal.min_bootstrap_ci_low is not None
            and result.bootstrap_ci_low is not None
            and result.bootstrap_ci_low < goal.min_bootstrap_ci_low
        ):
            reasons.append("Нижняя граница bootstrap interval не достигла порога.")
        if (
            goal.max_concentration is not None
            and result.max_selection_share is not None
            and result.max_selection_share > goal.max_concentration
        ):
            reasons.append("Стратегия чрезмерно концентрирована.")
        if isinstance(goal, ResearchGoalContract):
            criteria = goal.research_acceptance_criteria
            assert result.positive_roi_bootstrap_fraction is not None
            assert result.bet_coverage is not None
            assert result.simulated_profit is not None
            assert result.baseline_simulated_profit is not None
            if result.roi <= 0:
                reasons.append("Итоговый ROI не положителен.")
            if (
                result.positive_roi_bootstrap_fraction
                < criteria.min_positive_roi_bootstrap_fraction
            ):
                reasons.append("Доля положительных ROI bootstrap-прогонов ниже порога.")
            if result.bet_coverage < criteria.min_bet_coverage:
                reasons.append("Bet coverage ниже согласованного порога.")
            if result.simulated_profit <= result.baseline_simulated_profit:
                reasons.append("Simulated profit не превзошёл baseline.")
            if (
                result.current_model_simulated_profit is not None
                and result.simulated_profit <= result.current_model_simulated_profit
            ):
                reasons.append("Simulated profit не превзошёл current model.")
        if reasons:
            return EvaluationResult(decision=EvaluationDecision.FAIL, reasons=reasons)
        return EvaluationResult(
            decision=EvaluationDecision.PASS,
            reasons=["Минимальные prediction и economic criteria достигнуты."],
        )
