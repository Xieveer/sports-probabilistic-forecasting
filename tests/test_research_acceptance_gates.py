"""Проверки business gates нового контракта Research Mode."""

from __future__ import annotations

import pytest

from sports_forecast.research.contracts import (
    EvaluationDecision,
    ExperimentResult,
    GoalContract,
    ResearchAcceptanceCriteria,
    ResearchGoalContract,
    ResearchMemory,
    ResearchState,
)
from sports_forecast.research.evaluation import EvaluationHarness
from sports_forecast.research.orchestrator import ResearchOrchestrator
from sports_forecast.research.storage import ResearchRepository


def _goal(**updates: object) -> ResearchGoalContract:
    """Создать новый контракт без обязательных ML-порогов до разведки данных."""
    values: dict[str, object] = {
        "goal_id": "research-nhl-profit",
        "scientific_objective": "Найти устойчиво прибыльный сигнал.",
        "betting_business_objective": "Превзойти reference на holdout.",
        "target": "home_win",
        "prediction_horizon": "pre-match",
        "betting_market": "NHL moneyline",
        "bookmaker_odds_source": "historical odds",
        "allowed_information_timestamp": "до начала матча",
        "development_data": "сезоны 2022-2024",
        "validation_strategy": "walk-forward",
        "locked_holdout": "сезон 2025",
        "prediction_metrics": ["LogLoss"],
        "economic_metrics": ["ROI", "profit", "coverage"],
        "robustness_criteria": ["bootstrap"],
        "min_bets": 50,
        "experiment_budget": 5,
        "compute_budget": "100 trials",
        "api_budget": "0 запросов",
        "stop_conditions": ["budget"],
    }
    values.update(updates)
    return ResearchGoalContract(**values)


def _result(**updates: object) -> ExperimentResult:
    """Создать результат, который проходит новые financial gates."""
    values: dict[str, object] = {
        "experiment_id": "E-profit",
        "temporal_validation": True,
        "log_loss": 0.65,
        "baseline_log_loss": 0.60,
        "brier": 0.21,
        "roi": 0.03,
        "turnover": 120.0,
        "number_of_bets": 100,
        "max_drawdown": 0.08,
        "used_locked_holdout": False,
        "positive_roi_bootstrap_fraction": 0.82,
        "bet_coverage": 0.24,
        "simulated_profit": 12.0,
        "baseline_simulated_profit": 8.0,
    }
    values.update(updates)
    return ExperimentResult(**values)


def test_research_acceptance_criteria_have_agreed_business_defaults() -> None:
    """Новый контракт по умолчанию требует 80% positive ROI и 20% coverage."""
    criteria = ResearchAcceptanceCriteria()

    assert criteria.min_positive_roi_bootstrap_fraction == 0.8
    assert criteria.min_bet_coverage == 0.2
    assert criteria.require_current_model_profit_superiority is False


def test_new_research_goal_reserves_five_full_attempts() -> None:
    """Новый research run не исчерпывает бюджет до пяти полных циклов."""
    with pytest.raises(ValueError, match="experiment_budget"):
        _goal(experiment_budget=4)

    assert _goal(experiment_budget=5).experiment_budget == 5


def test_new_run_cannot_start_with_legacy_goal(tmp_path) -> None:
    """Чтение старых запусков не позволяет создавать новые без financial gates."""
    orchestrator = ResearchOrchestrator(ResearchRepository(tmp_path), None, None, None)  # type: ignore[arg-type]

    with pytest.raises(TypeError, match="ResearchGoalContract"):
        orchestrator.start(GoalContract.model_validate(_goal().model_dump()))

    assert orchestrator.start(_goal()).startswith("research-nhl-profit-")


def test_new_contract_does_not_require_ml_threshold_before_data_exploration() -> None:
    """Плохой LogLoss сам по себе не блокирует business gate без заданного ML-порога."""
    evaluation = EvaluationHarness().evaluate(_goal(), _result(), ResearchMemory())

    assert evaluation.decision is EvaluationDecision.PASS


@pytest.mark.parametrize("roi", [-0.01, 0.0])
def test_new_contract_rejects_non_positive_observed_roi(roi: float) -> None:
    """Даже высокий bootstrap success не оправдывает неприбыльный итоговый ROI."""
    evaluation = EvaluationHarness().evaluate(_goal(), _result(roi=roi), ResearchMemory())

    assert evaluation.decision is EvaluationDecision.FAIL


def test_new_contract_preserves_business_gates_after_research_state_roundtrip(tmp_path) -> None:
    """Повторный запуск не может потерять agreed financial gates из durable state."""
    repository = ResearchRepository(tmp_path)
    repository.create(ResearchState(run_id="profit-run", goal=_goal()))

    loaded_goal = repository.load("profit-run").goal

    assert isinstance(loaded_goal, ResearchGoalContract)
    assert loaded_goal.research_acceptance_criteria.min_bet_coverage == 0.2


@pytest.mark.parametrize(
    ("result_update", "expected_reason"),
    [
        ({"positive_roi_bootstrap_fraction": None}, "positive ROI bootstrap"),
        ({"bet_coverage": None}, "coverage"),
        ({"simulated_profit": None}, "simulated profit кандидата"),
        ({"baseline_simulated_profit": None}, "simulated profit baseline"),
    ],
)
def test_new_contract_marks_missing_business_gate_metrics_invalid(
    result_update: dict[str, object], expected_reason: str
) -> None:
    """Нельзя получить PASS, если runner не вернул обязательную financial metric."""
    evaluation = EvaluationHarness().evaluate(_goal(), _result(**result_update), ResearchMemory())

    assert evaluation.decision is EvaluationDecision.INVALID
    assert any(expected_reason in reason for reason in evaluation.reasons)


@pytest.mark.parametrize(
    ("result_update", "expected_reason"),
    [
        ({"positive_roi_bootstrap_fraction": 0.79}, "bootstrap-прогонов"),
        ({"bet_coverage": 0.19}, "coverage"),
        ({"simulated_profit": 8.0}, "baseline"),
    ],
)
def test_new_contract_requires_financial_thresholds_and_strict_baseline_profit_superiority(
    result_update: dict[str, object], expected_reason: str
) -> None:
    """Равный baseline profit не является улучшением кандидата."""
    evaluation = EvaluationHarness().evaluate(_goal(), _result(**result_update), ResearchMemory())

    assert evaluation.decision is EvaluationDecision.FAIL
    assert any(expected_reason in reason for reason in evaluation.reasons)


def test_new_contract_requires_current_model_profit_when_comparison_is_configured() -> None:
    """Для турнира с production-моделью current model обязателен и должен уступать."""
    criteria = ResearchAcceptanceCriteria(require_current_model_profit_superiority=True)
    goal = _goal(research_acceptance_criteria=criteria)

    missing = EvaluationHarness().evaluate(goal, _result(), ResearchMemory())
    equal = EvaluationHarness().evaluate(
        goal, _result(current_model_simulated_profit=12.0), ResearchMemory()
    )
    better = EvaluationHarness().evaluate(
        goal, _result(current_model_simulated_profit=9.0), ResearchMemory()
    )

    assert missing.decision is EvaluationDecision.INVALID
    assert equal.decision is EvaluationDecision.FAIL
    assert better.decision is EvaluationDecision.PASS


def test_new_contract_rejects_known_current_model_profit_even_without_flag() -> None:
    """Наличие действующей модели нельзя игнорировать из-за неверного флага."""
    evaluation = EvaluationHarness().evaluate(
        _goal(), _result(current_model_simulated_profit=20.0), ResearchMemory()
    )

    assert evaluation.decision is EvaluationDecision.FAIL
