"""Типизированные контракты Research Mode.

Все объекты этого модуля сериализуемы и являются единственным допустимым форматом
перехода между изолированными ролями и Research Orchestrator.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


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


class ApiParameterRecord(BaseModel):
    """Параметр публично исследованного API-метода."""

    name: str = Field(min_length=1)
    location: Literal["path", "query", "header", "body"]
    required: bool
    data_type: str = Field(min_length=1)
    description: str = Field(min_length=1)
    allowed_values: list[str] = Field(default_factory=list)

    @field_validator("name", "data_type", "description")
    @classmethod
    def validate_text(cls, value: str) -> str:
        """Отклонить пустую после trim семантику параметра."""
        if not value.strip():
            raise ValueError("семантическое поле не может состоять только из пробелов")
        return value


class ApiEvidenceRecord(BaseModel):
    """Проверяемое безопасное evidence API-наблюдения."""

    reference: str = Field(min_length=1)
    as_of: datetime
    evidence_level: str = Field(min_length=1)

    @field_validator("reference", "evidence_level")
    @classmethod
    def validate_text(cls, value: str) -> str:
        """Отклонить пустую после trim provenance-запись."""
        if not value.strip():
            raise ValueError("evidence не может состоять только из пробелов")
        return value


class ApiEndpointRecord(BaseModel):
    """Проверяемое описание одного API endpoint без полного внешнего payload."""

    endpoint_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
    path: str = Field(pattern=r"^/")
    purpose: str = Field(min_length=1)
    schema_status: Literal["observed", "unobserved", "denied"] = "observed"
    parameters: list[ApiParameterRecord] = Field(default_factory=list)
    response_root: str = Field(min_length=1)
    pagination: str = Field(min_length=1)
    access_restrictions: str = Field(min_length=1)
    evidence: ApiEvidenceRecord

    @field_validator("purpose", "response_root", "pagination", "access_restrictions")
    @classmethod
    def validate_text(cls, value: str) -> str:
        """Отклонить пустую после trim семантику метода."""
        if not value.strip():
            raise ValueError("семантическое поле не может состоять только из пробелов")
        return value


class ApiFieldRecord(BaseModel):
    """Семантика одного поля ответа API для scientist и engineering handoff."""

    field_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    endpoint_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    entity: str = Field(min_length=1)
    json_path: str = Field(min_length=1)
    data_type: str = Field(min_length=1)
    nullable: bool
    description: str = Field(min_length=1)
    key_role: Literal["primary", "foreign", "natural", "none"]
    usage: Literal["feature", "target", "label", "odds", "metadata", "unknown"]
    temporal_availability: Literal[
        "pre_event",
        "pre_event_if_timestamp_checked",
        "live",
        "post_event",
        "unknown",
    ]
    leakage_risk: str = Field(min_length=1)
    units: str = Field(min_length=1)
    domain: str = Field(min_length=1)
    evidence: ApiEvidenceRecord

    @field_validator(
        "entity", "json_path", "data_type", "description", "leakage_risk", "units", "domain"
    )
    @classmethod
    def validate_text(cls, value: str) -> str:
        """Отклонить пустую после trim семантику поля."""
        if not value.strip():
            raise ValueError("семантическое поле не может состоять только из пробелов")
        return value


class ApiCatalogScope(BaseModel):
    """Явная граница полноты изученного публичного API surface."""

    observed_endpoint_ids: list[str] = Field(min_length=1)
    unobserved_endpoint_ids: list[str] = Field(default_factory=list)
    field_coverage: str = Field(min_length=1)
    limitations: str = Field(min_length=1)


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
    catalog_schema_version: int = Field(default=1, ge=1)
    catalog_completeness: Literal["partial", "complete"] = "partial"
    catalog_scope: ApiCatalogScope | None = None
    api_endpoints: list[ApiEndpointRecord] = Field(default_factory=list)
    api_fields: list[ApiFieldRecord] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_complete_catalog(self) -> DataSourceRecord:
        """Не допустить выдачу summary-списков за полный контракт API."""
        if self.catalog_completeness != "complete":
            return self
        if not self.api_endpoints:
            raise ValueError("complete catalog требует непустой api_endpoints")
        if not self.api_fields:
            raise ValueError("complete catalog требует непустой api_fields")
        if self.catalog_scope is None:
            raise ValueError("complete catalog требует catalog_scope")

        endpoint_ids = {endpoint.endpoint_id for endpoint in self.api_endpoints}
        if len(endpoint_ids) != len(self.api_endpoints):
            raise ValueError("duplicate endpoint_id")
        field_ids = {field.field_id for field in self.api_fields}
        if len(field_ids) != len(self.api_fields):
            raise ValueError("duplicate field_id")
        unknown_endpoint_ids = {
            field.endpoint_id for field in self.api_fields if field.endpoint_id not in endpoint_ids
        }
        if unknown_endpoint_ids:
            unknown_ids = ", ".join(sorted(unknown_endpoint_ids))
            raise ValueError(f"api_fields ссылаются на неизвестные api_endpoints: {unknown_ids}")
        described_endpoint_ids = {field.endpoint_id for field in self.api_fields}
        undocumented_endpoint_ids = {
            endpoint.endpoint_id
            for endpoint in self.api_endpoints
            if endpoint.schema_status == "observed"
            and endpoint.endpoint_id not in described_endpoint_ids
        }
        if undocumented_endpoint_ids:
            endpoint_names = ", ".join(sorted(undocumented_endpoint_ids))
            raise ValueError(f"api_endpoints без api_fields: {endpoint_names}")
        observed_ids = {
            endpoint.endpoint_id
            for endpoint in self.api_endpoints
            if endpoint.schema_status == "observed"
        }
        unobserved_ids = endpoint_ids - observed_ids
        if set(self.catalog_scope.observed_endpoint_ids) != observed_ids:
            raise ValueError("catalog_scope.observed_endpoint_ids не совпадает с observed endpoint")
        if set(self.catalog_scope.unobserved_endpoint_ids) != unobserved_ids:
            missing = ", ".join(
                sorted(unobserved_ids - set(self.catalog_scope.unobserved_endpoint_ids))
            )
            raise ValueError(f"catalog_scope.unobserved_endpoint_ids не содержит: {missing}")
        for field in self.api_fields:
            if (
                field.usage == "unknown"
                and field.temporal_availability == "unknown"
                and field.leakage_risk == "unknown"
            ):
                raise ValueError(
                    "api_field не готов: usage, temporal_availability и leakage_risk одновременно unknown"
                )
        return self


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
