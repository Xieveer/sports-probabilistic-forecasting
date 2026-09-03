"""Сквозные проверки изолированного Research Loop."""

from __future__ import annotations

from collections import deque
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from sports_forecast.research.adapters import ValidatedRoleGateway
from sports_forecast.research.contracts import (
    ArtifactProvenance,
    ContextPackage,
    DataRequirement,
    DataResearchFinding,
    DataResearchResult,
    DataSourceRecord,
    EngineeringReceipt,
    EngineeringRequest,
    EngineeringStatus,
    EvaluationDecision,
    EvaluationNarrative,
    ExperimentResult,
    ExperimentSpec,
    GoalContract,
    HypothesisProposal,
    ResearchMemory,
    ResearchStatus,
)
from sports_forecast.research.evaluation import EvaluationHarness
from sports_forecast.research.orchestrator import ResearchOrchestrator
from sports_forecast.research.storage import ResearchRepository


class ScriptedRoles:
    """Возвращает заранее подготовленные ответы вместо реального LLM runner."""

    def __init__(self) -> None:
        self.hypotheses = deque(
            [
                HypothesisProposal(
                    hypothesis_id="H-001",
                    title="Составы добавляют сигнал",
                    motivation="Рынок может не полностью учесть поздние составы.",
                    mechanism="Рейтинг доступных игроков меняет вероятность победы.",
                    expected_effect="Ниже LogLoss относительно baseline.",
                    falsification_criteria="Нет улучшения LogLoss и ROI.",
                    required_data=[
                        DataRequirement(
                            name="lineups",
                            purpose="Собрать составы до матча.",
                            required_before="allowed information timestamp",
                            leakage_risk="Публикация состава после рынка.",
                        )
                    ],
                    proposed_experiment=ExperimentSpec(
                        experiment_id="E-001",
                        description="Сравнить baseline и lineup feature.",
                        temporal_validation=True,
                    ),
                    leakage_risks=["Состав опубликован после allowed timestamp."],
                    expected_information_gain="Проверяет инкрементальный сигнал составов.",
                    requires_data_research=True,
                ),
                HypothesisProposal(
                    hypothesis_id="H-002",
                    title="Рыночная калибровка",
                    motivation="Систематическое смещение можно калибровать.",
                    mechanism="Калибратор исправляет вероятностное смещение.",
                    expected_effect="Улучшение LogLoss при стабильном ROI.",
                    falsification_criteria="Нет преимущества над baseline.",
                    required_data=[],
                    proposed_experiment=ExperimentSpec(
                        experiment_id="E-002",
                        description="Калибровать baseline на development периоде.",
                        temporal_validation=True,
                    ),
                    leakage_risks=["Fit калибратора на validation периоде."],
                    expected_information_gain="Отделяет калибровку от нового data signal.",
                ),
            ]
        )
        self.context_roles: list[str] = []

    def propose_hypothesis(self, package):  # type: ignore[no-untyped-def]
        self.context_roles.append(package.role)
        return self.hypotheses.popleft()

    def research_data(self, package):  # type: ignore[no-untyped-def]
        self.context_roles.append(package.role)
        return DataResearchResult(
            source=DataSourceRecord(
                source_id="public-lineups",
                source="Публичный lineup feed",
                access_method="public REST",
                documentation="https://example.invalid/docs",
                known_endpoints=["/lineups"],
                entities=["match", "lineup"],
                available_fields=["match_id", "published_at", "player_id"],
                historical_depth="один сезон подтверждён",
                update_frequency="нерегулярно",
                temporal_availability="нужно сверять published_at",
                coverage="NHL",
                missingness="неизвестна",
                pagination="неизвестна",
                rate_limits="неизвестны",
                authentication="не требуется по документации",
                observed_access_restrictions="не обнаружены",
                reliability="не проверена",
                data_quality="нужна валидация",
                potential_leakage="публикация после матча",
                potential_research_value="lineup signal",
                known_problems=["История неполна."],
                last_verified="2026-08-23",
            ),
            findings=[
                DataResearchFinding(
                    finding_id="drf-lineups-001",
                    summary="Исторический endpoint требует feature pipeline.",
                    evidence="Проверен synthetic source record.",
                    temporal_risk="Нужно проверять published_at.",
                    research_implication="Нужна обычная Engineering TASK.",
                    provenance=ArtifactProvenance(
                        artifact_id="public-lineups:drf-001",
                        role="data-researcher",
                        context_package_id=package.package_id,
                        as_of=package.as_of,
                    ),
                )
            ],
            engineering_request=EngineeringRequest(
                request_id="ER-001",
                title="Добавить исторические lineup snapshots",
                rationale="Нужны timestamped составы для честного backtest.",
                required_artifacts=["REQ", "TASK"],
            ),
        )

    def interpret_evaluation(self, package, result):  # type: ignore[no-untyped-def]
        self.context_roles.append(package.role)
        return EvaluationNarrative(
            conclusion=f"{result.decision.value}: результат интерпретирован независимо.",
            caveats=["Нужна проверка на следующем сезоне."],
        )


class VerifiedEngineering:
    """Имитирует только подтверждённый handoff существующего workflow."""

    def submit(self, request: EngineeringRequest) -> EngineeringReceipt:
        return EngineeringReceipt(
            request_id=request.request_id,
            status=EngineeringStatus.VERIFIED,
            task_reference="docs/backlog/tasks/TASK-999-1-lineups.md",
        )

    def status(self, request_id: str) -> EngineeringReceipt:
        return EngineeringReceipt(
            request_id=request_id,
            status=EngineeringStatus.VERIFIED,
            task_reference="docs/backlog/tasks/TASK-999-1-lineups.md",
        )


class ScriptedExperiments:
    """Первый эксперимент отвергается, второй проходит цель."""

    def __init__(self) -> None:
        self.results = deque(
            [
                ExperimentResult(
                    experiment_id="E-001",
                    temporal_validation=True,
                    log_loss=0.61,
                    baseline_log_loss=0.60,
                    brier=0.22,
                    roi=-0.02,
                    turnover=100.0,
                    number_of_bets=80,
                    max_drawdown=0.12,
                    used_locked_holdout=False,
                ),
                ExperimentResult(
                    experiment_id="E-002",
                    temporal_validation=True,
                    log_loss=0.55,
                    baseline_log_loss=0.60,
                    brier=0.19,
                    roi=0.03,
                    turnover=120.0,
                    number_of_bets=100,
                    max_drawdown=0.08,
                    used_locked_holdout=False,
                ),
            ]
        )

    def run(self, spec: ExperimentSpec) -> ExperimentResult:
        result = self.results.popleft()
        assert result.experiment_id == spec.experiment_id
        return result


def _goal() -> GoalContract:
    return GoalContract(
        goal_id="research-nhl-moneyline",
        scientific_objective="Найти воспроизводимое улучшение вероятности NHL moneyline.",
        betting_business_objective="Проверить экономическую применимость без утверждения edge.",
        target="home_win",
        prediction_horizon="pre-match",
        betting_market="NHL moneyline",
        bookmaker_odds_source="historical odds fixture",
        allowed_information_timestamp="до открытия рынка",
        development_data="сезоны 2022-2024",
        validation_strategy="walk-forward",
        locked_holdout="сезон 2025",
        prediction_metrics=["LogLoss", "Brier"],
        economic_metrics=["ROI", "turnover"],
        robustness_criteria=["стабильность по сезонам"],
        min_roi=0.01,
        max_log_loss=0.58,
        min_bets=50,
        experiment_budget=2,
        compute_budget="локальный smoke",
        api_budget="0 запросов",
        stop_conditions=["budget", "external decision"],
    )


def _orchestrator(
    root: Path,
    roles: ScriptedRoles,
    experiments: ScriptedExperiments,
) -> ResearchOrchestrator:
    return ResearchOrchestrator(
        repository=ResearchRepository(root),
        roles=roles,
        engineering=VerifiedEngineering(),
        experiments=experiments,
    )


def test_research_loop_survives_isolated_orchestrator_instances(tmp_path: Path) -> None:
    """Две итерации восстанавливаются только из persistent state, а не из чата."""
    roles = ScriptedRoles()
    experiments = ScriptedExperiments()
    root = tmp_path / "research-workspace"
    run_id = _orchestrator(root, roles, experiments).start(_goal())

    for _ in range(8):
        state = _orchestrator(root, roles, experiments).advance(run_id)

    assert state.status is ResearchStatus.SUCCESS
    assert state.iteration == 2
    assert [finding.hypothesis_id for finding in state.memory.findings] == ["H-001", "H-002"]
    assert state.memory.data_sources == ["public-lineups"]
    assert state.memory.data_research_findings[0].summary == (
        "Исторический endpoint требует feature pipeline."
    )
    assert state.memory.data_research_findings[0].provenance.role == "data-researcher"
    assert state.engineering_receipts[0].task_reference.endswith("TASK-999-1-lineups.md")
    assert roles.context_roles == [
        "research-scientist",
        "data-researcher",
        "research-evaluator",
        "research-scientist",
        "research-evaluator",
    ]
    assert (root / "runs" / run_id / "state.json").is_file()


def test_experiment_waits_for_verified_engineering_task(tmp_path: Path) -> None:
    """EngineeringRequest не может перейти к experiment без verified существующей TASK."""
    roles = ScriptedRoles()
    experiments = ScriptedExperiments()
    root = tmp_path / "research-workspace"
    orchestrator = _orchestrator(root, roles, experiments)
    run_id = orchestrator.start(_goal())

    orchestrator.advance(run_id)
    orchestrator.advance(run_id)

    state = ResearchRepository(root).load(run_id)

    assert state.status is ResearchStatus.ENGINEERING
    assert not state.experiments


def test_goal_identifier_cannot_escape_research_workspace() -> None:
    """Идентификатор run не допускает path traversal из внешнего Goal Contract."""
    with pytest.raises(ValidationError):
        GoalContract(**(_goal().model_dump() | {"goal_id": "../outside"}))


def test_validated_role_gateway_retries_invalid_json_with_feedback() -> None:
    """Adapter не пропускает невалидный ответ и повторяет isolated role call один раз."""
    valid = ScriptedRoles().hypotheses[0].model_dump_json()
    invoker = ScriptedRawInvoker(['{"hypothesis_id":"H-invalid"}', valid])
    gateway = ValidatedRoleGateway(invoker, max_attempts=2)
    package = ContextPackage(
        schema_version=1,
        package_id="pilot:1:research-scientist",
        as_of=datetime(2026, 8, 24, tzinfo=UTC),
        role="research-scientist",
        goal=_goal(),
        run_id="pilot",
        iteration=1,
        current_status=ResearchStatus.SCIENTIST,
        task="Сформулировать гипотезу.",
    )

    proposal = gateway.propose_hypothesis(package)

    assert proposal.hypothesis_id == "H-001"
    assert invoker.feedback[0] is None
    assert invoker.feedback[1] is not None
    assert "validation" in invoker.feedback[1]


def test_exhausted_validation_retry_fails_before_state_transition(tmp_path: Path) -> None:
    """После последней validation error orchestrator не переходит к data research."""
    root = tmp_path / "research-workspace"
    orchestrator = ResearchOrchestrator(
        repository=ResearchRepository(root),
        roles=ValidatedRoleGateway(ScriptedRawInvoker(['{"hypothesis_id":"invalid"}'])),
        engineering=VerifiedEngineering(),
        experiments=ScriptedExperiments(),
    )
    run_id = orchestrator.start(_goal())

    state = orchestrator.advance(run_id)

    assert state.status is ResearchStatus.FAILED
    assert state.active_hypothesis is None
    assert state.schema_version == 1
    assert state.as_of.tzinfo is UTC


def test_evaluation_is_invalid_when_required_robustness_metric_is_missing() -> None:
    """Goal не может получить PASS, если runner не вернул обязательный robustness metric."""
    goal = _goal().model_copy(update={"min_bootstrap_ci_low": 0.01, "max_concentration": 0.30})
    result = ExperimentResult(
        experiment_id="E-required-metrics",
        temporal_validation=True,
        log_loss=0.55,
        baseline_log_loss=0.60,
        brier=0.19,
        roi=0.03,
        turnover=120.0,
        number_of_bets=100,
        max_drawdown=0.08,
        used_locked_holdout=False,
    )

    evaluation = EvaluationHarness().evaluate(goal, result, ResearchMemory())

    assert evaluation.decision is EvaluationDecision.INVALID
    assert any("bootstrap" in reason for reason in evaluation.reasons)
    assert any("concentration" in reason for reason in evaluation.reasons)


def test_engineering_receipt_for_another_request_cannot_start_experiment(tmp_path: Path) -> None:
    """Verified TASK другого EngineeringRequest не открывает experiment boundary."""
    root = tmp_path / "research-workspace"
    orchestrator = ResearchOrchestrator(
        repository=ResearchRepository(root),
        roles=ScriptedRoles(),
        engineering=WrongEngineeringReceipt(),
        experiments=ScriptedExperiments(),
    )
    run_id = orchestrator.start(_goal())

    orchestrator.advance(run_id)
    orchestrator.advance(run_id)
    state = orchestrator.advance(run_id)

    assert state.status is ResearchStatus.FAILED
    assert not state.experiments


def test_stale_experiment_result_cannot_be_evaluated_for_active_hypothesis(tmp_path: Path) -> None:
    """Result другого experiment_id не становится evidence активной гипотезы."""
    root = tmp_path / "research-workspace"
    orchestrator = ResearchOrchestrator(
        repository=ResearchRepository(root),
        roles=ScriptedRoles(),
        engineering=VerifiedEngineering(),
        experiments=WrongExperimentResult(),
    )
    run_id = orchestrator.start(_goal())

    orchestrator.advance(run_id)
    orchestrator.advance(run_id)
    orchestrator.advance(run_id)
    state = orchestrator.advance(run_id)

    assert state.status is ResearchStatus.FAILED
    assert not state.experiments


def test_experiment_result_must_match_temporal_validation_specification(tmp_path: Path) -> None:
    """Runner не может подменить temporal validation, указанную в ExperimentSpec."""
    root = tmp_path / "research-workspace"
    orchestrator = ResearchOrchestrator(
        repository=ResearchRepository(root),
        roles=ScriptedRoles(),
        engineering=VerifiedEngineering(),
        experiments=WrongTemporalExperimentResult(),
    )
    run_id = orchestrator.start(_goal())

    for _ in range(4):
        state = orchestrator.advance(run_id)

    assert state.status is ResearchStatus.FAILED
    assert not state.experiments


class WrongExperimentResult:
    """Возвращает успешные метрики чужого experiment, как stale внешний runner."""

    def run(self, spec: ExperimentSpec) -> ExperimentResult:
        return ExperimentResult(
            experiment_id="E-unrelated",
            temporal_validation=True,
            log_loss=0.55,
            baseline_log_loss=0.60,
            brier=0.19,
            roi=0.03,
            turnover=120.0,
            number_of_bets=100,
            max_drawdown=0.08,
            used_locked_holdout=False,
        )


class WrongTemporalExperimentResult:
    """Возвращает верный ID, но меняет temporal validation specification."""

    def run(self, spec: ExperimentSpec) -> ExperimentResult:
        return ExperimentResult(
            experiment_id=spec.experiment_id,
            temporal_validation=False,
            log_loss=0.55,
            baseline_log_loss=0.60,
            brier=0.19,
            roi=0.03,
            turnover=120.0,
            number_of_bets=100,
            max_drawdown=0.08,
            used_locked_holdout=False,
        )


def test_validation_payload_is_not_persisted_or_logged(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Невалидный внешний JSON не раскрывается в state, retry feedback или логах."""
    marker = "SECRET-EXTERNAL-PAYLOAD"
    invoker = ScriptedRawInvoker([f'{{"hypothesis_id":["{marker}"]}}'])
    root = tmp_path / "research-workspace"
    orchestrator = ResearchOrchestrator(
        repository=ResearchRepository(root),
        roles=ValidatedRoleGateway(invoker, max_attempts=1),
        engineering=VerifiedEngineering(),
        experiments=ScriptedExperiments(),
    )
    run_id = orchestrator.start(_goal())

    state = orchestrator.advance(run_id)

    assert marker not in (state.failure_reason or "")
    assert marker not in caplog.text


class WrongEngineeringReceipt:
    """Возвращает verified receipt для другого request, как ошибочный внешний gateway."""

    def submit(self, request: EngineeringRequest) -> EngineeringReceipt:
        return EngineeringReceipt(
            request_id="ER-unrelated",
            status=EngineeringStatus.VERIFIED,
            task_reference="docs/backlog/tasks/TASK-999-1-unrelated.md",
        )

    def status(self, request_id: str) -> EngineeringReceipt:
        return self.submit(
            EngineeringRequest(
                request_id=request_id,
                title="unused",
                rationale="unused",
                required_artifacts=["TASK"],
            )
        )


class ScriptedRawInvoker:
    """Имитирует изолированный runtime, возвращающий raw JSON по очереди."""

    def __init__(self, responses: list[str]) -> None:
        self.responses = deque(responses)
        self.feedback: list[str | None] = []

    def invoke(self, role, package, retry_feedback):  # type: ignore[no-untyped-def]
        self.feedback.append(retry_feedback)
        return self.responses.popleft()
