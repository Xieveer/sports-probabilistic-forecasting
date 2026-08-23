"""Типизированные контракты Research Mode.

Все объекты этого модуля сериализуемы и являются единственным допустимым форматом
перехода между изолированными ролями и Research Orchestrator.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class ResearchStatus(StrEnum):
    """Допустимые состояния state machine исследования."""

    SCIENTIST = "scientist"
    DATA_RESEARCH = "data_research"
    ENGINEERING = "engineering"
    WAITING_ENGINEERING = "waiting_engineering"
    EXPERIMENT = "experiment"
    EVALUATION = "evaluation"
    SUCCESS = "success"
    BLOCKED = "blocked"
    EXHAUSTED = "exhausted"
    FAILED = "failed"


class EvaluationDecision(StrEnum):
    """Научное решение, доступное только Evaluation Harness."""

    PASS = "pass"
    FAIL = "fail"
    INVALID = "invalid"


class EngineeringStatus(StrEnum):
    """Статус обычной engineering-задачи, нужный Research Loop."""

    WAITING = "waiting"
    VERIFIED = "verified"
    BLOCKED = "blocked"


class GoalContract(BaseModel):
    """Формализованная цель одного исследования."""

    goal_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    scientific_objective: str
    betting_business_objective: str
    target: str
    prediction_horizon: str
    betting_market: str
    bookmaker_odds_source: str
    allowed_information_timestamp: str
    development_data: str
    validation_strategy: str
    locked_holdout: str
    prediction_metrics: list[str] = Field(min_length=1)
    economic_metrics: list[str] = Field(min_length=1)
    robustness_criteria: list[str] = Field(min_length=1)
    min_roi: float
    max_log_loss: float
    min_bets: int = Field(ge=1)
    max_drawdown: float | None = Field(default=None, ge=0)
    min_bootstrap_ci_low: float | None = None
    max_concentration: float | None = Field(default=None, ge=0, le=1)
    experiment_budget: int = Field(ge=1)
    compute_budget: str
    api_budget: str
    stop_conditions: list[str] = Field(min_length=1)


class ExperimentSpec(BaseModel):
    """Воспроизводимая спецификация одного эксперимента."""

    experiment_id: str
    description: str
    temporal_validation: bool


class EngineeringRequest(BaseModel):
    """Запрос в существующий Engineering Workflow, а не новая engineering-задача."""

    request_id: str
    title: str
    rationale: str
    required_artifacts: list[str] = Field(min_length=1)


class DataRequirement(BaseModel):
    """Минимальная потребность гипотезы в данных и их времени доступности."""

    name: str
    purpose: str
    required_before: str
    leakage_risk: str


class HumanDecisionRequest(BaseModel):
    """Явный blocker, который может снять только внешнее решение."""

    reason: str
    required_decision: str
    options: list[str] = Field(min_length=1)


class ArtifactProvenance(BaseModel):
    """Происхождение артефакта, передаваемого между изолированными сессиями."""

    schema_version: int = Field(default=1, ge=1)
    artifact_id: str = Field(pattern=r"^[a-z0-9][a-z0-9:.-]*$")
    role: str
    context_package_id: str = Field(pattern=r"^[a-z0-9][a-z0-9:.-]*$")
    as_of: datetime


class HypothesisProposal(BaseModel):
    """Ответ research-scientist с фальсифицируемой гипотезой."""

    hypothesis_id: str
    title: str
    motivation: str
    mechanism: str
    expected_effect: str
    falsification_criteria: str
    required_data: list[DataRequirement]
    proposed_experiment: ExperimentSpec
    leakage_risks: list[str]
    expected_information_gain: str
    requires_data_research: bool = False
    engineering_request: EngineeringRequest | None = None


class DataSourceRecord(BaseModel):
    """Каноническая карточка исследованного публичного источника."""

    source_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    source: str
    access_method: str
    documentation: str
    known_endpoints: list[str]
    entities: list[str]
    available_fields: list[str]
    historical_depth: str
    update_frequency: str
    temporal_availability: str
    coverage: str
    missingness: str
    pagination: str
    rate_limits: str
    authentication: str
    observed_access_restrictions: str
    reliability: str
    data_quality: str
    potential_leakage: str
    potential_research_value: str
    known_problems: list[str]
    last_verified: str


class DataResearchResult(BaseModel):
    """Проверенный результат data-researcher для одной гипотезы."""

    source: DataSourceRecord
    findings: list[DataResearchFinding]
    engineering_request: EngineeringRequest | None = None
    blocked_reason: str | None = None
    human_decision_request: HumanDecisionRequest | None = None


class DataResearchFinding(BaseModel):
    """Проверяемое finding data-researcher с временной точкой и provenance."""

    finding_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    summary: str
    evidence: str
    temporal_risk: str
    research_implication: str
    provenance: ArtifactProvenance


class EngineeringReceipt(BaseModel):
    """Evidence существующего Engineering Workflow для Research Loop."""

    request_id: str
    status: EngineeringStatus
    task_reference: str | None = None
    reason: str | None = None


class ExperimentResult(BaseModel):
    """Raw metrics, вычисленные experiment runner детерминированно."""

    experiment_id: str
    temporal_validation: bool
    log_loss: float
    baseline_log_loss: float
    brier: float
    roi: float
    turnover: float = Field(ge=0)
    number_of_bets: int = Field(ge=0)
    max_drawdown: float = Field(ge=0)
    used_locked_holdout: bool
    calibration_error: float | None = Field(default=None, ge=0)
    bootstrap_ci_low: float | None = None
    bootstrap_ci_high: float | None = None
    season_roi: dict[str, float] = Field(default_factory=dict)
    tournament_roi: dict[str, float] = Field(default_factory=dict)
    threshold_roi: dict[str, float] = Field(default_factory=dict)
    odds_bucket_roi: dict[str, float] = Field(default_factory=dict)
    max_selection_share: float | None = Field(default=None, ge=0, le=1)
    closing_line_value: float | None = None


class EvaluationResult(BaseModel):
    """Детерминированный результат Evaluation Harness."""

    decision: EvaluationDecision
    reasons: list[str]


class EvaluationNarrative(BaseModel):
    """Научная интерпретация evaluator, не меняющая decision harness."""

    conclusion: str
    caveats: list[str]


class ResearchFinding(BaseModel):
    """Каноническая запись знания после завершения итерации."""

    hypothesis_id: str
    experiment_id: str
    decision: EvaluationDecision
    summary: str
    caveats: list[str]
    provenance: ArtifactProvenance


class ResearchMemory(BaseModel):
    """Минимальная каноническая память run, не зависящая от чата."""

    findings: list[ResearchFinding] = Field(default_factory=list)
    data_sources: list[str] = Field(default_factory=list)
    data_research_findings: list[DataResearchFinding] = Field(default_factory=list)
    locked_holdout_revealed: bool = False


class ContextPackage(BaseModel):
    """Минимальный контекст изолированного role call."""

    schema_version: int = Field(default=1, ge=1)
    package_id: str = Field(pattern=r"^[a-z0-9][a-z0-9:.-]*$")
    as_of: datetime
    role: str
    goal: GoalContract
    run_id: str
    iteration: int
    current_status: ResearchStatus
    active_hypothesis: HypothesisProposal | None = None
    relevant_findings: list[ResearchFinding] = Field(default_factory=list)
    data_source_ids: list[str] = Field(default_factory=list)
    data_research_findings: list[DataResearchFinding] = Field(default_factory=list)
    task: str


class ResearchState(BaseModel):
    """Полное durable state одного research run."""

    schema_version: int = Field(default=1, ge=1)
    run_id: str
    goal: GoalContract
    status: ResearchStatus = ResearchStatus.SCIENTIST
    iteration: int = 0
    active_hypothesis: HypothesisProposal | None = None
    active_experiment: ExperimentResult | None = None
    memory: ResearchMemory = Field(default_factory=ResearchMemory)
    engineering_receipts: list[EngineeringReceipt] = Field(default_factory=list)
    experiments: list[ExperimentResult] = Field(default_factory=list)
    failure_reason: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    as_of: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
