"""Программно управляемый opt-in Research Loop."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from sports_forecast.research.contracts import (
    ArtifactProvenance,
    ContextPackage,
    DataResearchResult,
    EngineeringReceipt,
    EngineeringRequest,
    EngineeringStatus,
    EvaluationDecision,
    EvaluationNarrative,
    EvaluationResult,
    ExperimentResult,
    ExperimentSpec,
    GoalContract,
    HypothesisProposal,
    ResearchFinding,
    ResearchState,
    ResearchStatus,
)
from sports_forecast.research.evaluation import EvaluationHarness
from sports_forecast.research.storage import ResearchRepository
from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)


class ResearchRoleGateway(Protocol):
    """Граница вызовов изолированных research roles."""

    def propose_hypothesis(self, package: ContextPackage) -> HypothesisProposal: ...

    def research_data(self, package: ContextPackage) -> DataResearchResult: ...

    def interpret_evaluation(
        self, package: ContextPackage, result: EvaluationResult
    ) -> EvaluationNarrative: ...


class EngineeringWorkflowGateway(Protocol):
    """Граница existing Engineering Workflow; orchestrator не запускает его роли."""

    def submit(self, request: EngineeringRequest) -> EngineeringReceipt: ...

    def status(self, request_id: str) -> EngineeringReceipt: ...


class ExperimentRunner(Protocol):
    """Детерминированный executor ExperimentSpec."""

    def run(self, spec: ExperimentSpec) -> ExperimentResult: ...


class ResearchOrchestrator:
    """Выполняет ровно один валидированный переход Research Loop за вызов.

    Конструктор намеренно получает gateways извне: в production они могут создавать
    изолированные LLM sessions, а unit-тест заменяет их детерминированными adapters.
    """

    def __init__(
        self,
        repository: ResearchRepository,
        roles: ResearchRoleGateway,
        engineering: EngineeringWorkflowGateway,
        experiments: ExperimentRunner,
        harness: EvaluationHarness | None = None,
    ) -> None:
        self.repository = repository
        self.roles = roles
        self.engineering = engineering
        self.experiments = experiments
        self.harness = harness or EvaluationHarness()

    def start(self, goal: GoalContract) -> str:
        """Создать явный opt-in Research Mode run и вернуть его идентификатор."""
        run_id = f"{goal.goal_id}-{uuid4().hex[:8]}"
        self.repository.create(ResearchState(run_id=run_id, goal=goal))
        logger.info("Создан Research Mode run %s", run_id)
        return run_id

    def advance(self, run_id: str) -> ResearchState:
        """Выполнить один переход state machine и persist результат.

        Args:
            run_id: Идентификатор ранее созданного исследования.

        Returns:
            Состояние после одного перехода.
        """
        state = self.repository.load(run_id)
        if state.status in {
            ResearchStatus.SUCCESS,
            ResearchStatus.BLOCKED,
            ResearchStatus.EXHAUSTED,
            ResearchStatus.FAILED,
        }:
            return state
        try:
            self._advance(state)
        except Exception as error:  # noqa: BLE001
            state.status = ResearchStatus.FAILED
            state.failure_reason = "Ошибка выполнения этапа Research Loop."
            logger.error(
                "Research run %s завершён внутренней ошибкой: %s",
                run_id,
                type(error).__name__,
            )
        state.updated_at = datetime.now(UTC)
        state.as_of = state.updated_at
        self.repository.save(state)
        return state

    def _advance(self, state: ResearchState) -> None:
        if state.status is ResearchStatus.SCIENTIST:
            self._request_hypothesis(state)
        elif state.status is ResearchStatus.DATA_RESEARCH:
            self._research_data(state)
        elif state.status in {ResearchStatus.ENGINEERING, ResearchStatus.WAITING_ENGINEERING}:
            self._request_engineering(state)
        elif state.status is ResearchStatus.EXPERIMENT:
            self._run_experiment(state)
        elif state.status is ResearchStatus.EVALUATION:
            self._evaluate(state)

    def _request_hypothesis(self, state: ResearchState) -> None:
        if state.iteration >= state.goal.experiment_budget:
            state.status = ResearchStatus.EXHAUSTED
            return
        proposal = self.roles.propose_hypothesis(
            self._package(state, "research-scientist", "Сформулировать следующую гипотезу.")
        )
        state.active_hypothesis = proposal
        state.status = (
            ResearchStatus.DATA_RESEARCH
            if proposal.requires_data_research
            else ResearchStatus.ENGINEERING
            if proposal.engineering_request is not None
            else ResearchStatus.EXPERIMENT
        )

    def _research_data(self, state: ResearchState) -> None:
        result = self.roles.research_data(
            self._package(state, "data-researcher", "Исследовать доступность требуемых данных.")
        )
        self.repository.save_source(result.source)
        if result.source.source_id not in state.memory.data_sources:
            state.memory.data_sources.append(result.source.source_id)
        state.memory.data_research_findings.extend(result.findings)
        if result.blocked_reason is not None or result.human_decision_request is not None:
            state.status = ResearchStatus.BLOCKED
            state.failure_reason = result.blocked_reason or result.human_decision_request.reason
            return
        assert state.active_hypothesis is not None
        if result.engineering_request is not None:
            state.active_hypothesis.engineering_request = result.engineering_request
        state.status = (
            ResearchStatus.ENGINEERING
            if state.active_hypothesis.engineering_request is not None
            else ResearchStatus.EXPERIMENT
        )

    def _request_engineering(self, state: ResearchState) -> None:
        assert state.active_hypothesis is not None
        request = state.active_hypothesis.engineering_request
        assert request is not None
        receipt = self._engineering_receipt(state, request)
        if receipt.request_id != request.request_id:
            state.status = ResearchStatus.FAILED
            state.failure_reason = "Engineering receipt не соответствует активному request."
        elif receipt.status is EngineeringStatus.VERIFIED and receipt.task_reference:
            state.status = ResearchStatus.EXPERIMENT
        elif receipt.status is EngineeringStatus.BLOCKED:
            state.status = ResearchStatus.BLOCKED
            state.failure_reason = receipt.reason or "Engineering Workflow заблокирован."
        else:
            state.status = ResearchStatus.WAITING_ENGINEERING

    def _engineering_receipt(
        self, state: ResearchState, request: EngineeringRequest
    ) -> EngineeringReceipt:
        prior = next(
            (
                receipt
                for receipt in reversed(state.engineering_receipts)
                if receipt.request_id == request.request_id
            ),
            None,
        )
        receipt = (
            self.engineering.status(request.request_id)
            if prior is not None
            else self.engineering.submit(request)
        )
        state.engineering_receipts.append(receipt)
        return receipt

    def _run_experiment(self, state: ResearchState) -> None:
        assert state.active_hypothesis is not None
        specification = state.active_hypothesis.proposed_experiment
        result = self.experiments.run(specification)
        if result.experiment_id != specification.experiment_id:
            state.status = ResearchStatus.FAILED
            state.failure_reason = "Experiment result не соответствует активной specification."
            return
        if result.temporal_validation != specification.temporal_validation:
            state.status = ResearchStatus.FAILED
            state.failure_reason = "Experiment result нарушает temporal validation contract."
            return
        state.active_experiment = result
        state.experiments.append(result)
        state.status = ResearchStatus.EVALUATION

    def _evaluate(self, state: ResearchState) -> None:
        assert state.active_hypothesis is not None
        assert state.active_experiment is not None
        result = self.harness.evaluate(state.goal, state.active_experiment, state.memory)
        narrative = self.roles.interpret_evaluation(
            self._package(
                state, "research-evaluator", "Интерпретировать raw metrics и решение harness."
            ),
            result,
        )
        state.memory.findings.append(
            ResearchFinding(
                hypothesis_id=state.active_hypothesis.hypothesis_id,
                experiment_id=state.active_experiment.experiment_id,
                decision=result.decision,
                summary=narrative.conclusion,
                caveats=[*result.reasons, *narrative.caveats],
                provenance=ArtifactProvenance(
                    artifact_id=f"{state.run_id}:finding:{state.iteration + 1}",
                    role="research-evaluator",
                    context_package_id=f"{state.run_id}:{state.iteration + 1}:research-evaluator",
                    as_of=state.as_of,
                ),
            )
        )
        if state.active_experiment.used_locked_holdout:
            state.memory.locked_holdout_revealed = True
        state.iteration += 1
        state.active_hypothesis = None
        state.active_experiment = None
        if result.decision is EvaluationDecision.PASS:
            state.status = ResearchStatus.SUCCESS
        elif state.memory.locked_holdout_revealed:
            state.status = ResearchStatus.BLOCKED
            state.failure_reason = "Нужен новый locked holdout до следующей гипотезы."
        elif state.iteration >= state.goal.experiment_budget:
            state.status = ResearchStatus.EXHAUSTED
        else:
            state.status = ResearchStatus.SCIENTIST

    @staticmethod
    def _package(state: ResearchState, role: str, task: str) -> ContextPackage:
        return ContextPackage(
            package_id=f"{state.run_id}:{state.iteration + 1}:{role}",
            as_of=state.as_of,
            role=role,
            goal=state.goal,
            run_id=state.run_id,
            iteration=state.iteration + 1,
            current_status=state.status,
            active_hypothesis=state.active_hypothesis,
            relevant_findings=state.memory.findings[-5:],
            data_source_ids=state.memory.data_sources,
            data_research_findings=state.memory.data_research_findings[-5:],
            task=task,
        )
