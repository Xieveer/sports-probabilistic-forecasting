"""
SQLAlchemy ORM-модели для Prediction Store.

Таблица ``predictions`` хранит предвычисленные предсказания,
которые API отдаёт клиентам без тяжёлых вычислений.

Пример записи::

    match_id:         "72272"
    tournament:       "uel_kz_1"
    market:           "winner"
    predictions_json: {"home_win": 0.53, "away_win": 0.47}
    model_version:    "catboost_basic_prod"
    status:           "ok"
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    """Базовый класс для всех ORM-моделей."""

    pass


class Prediction(Base):
    """Предвычисленное предсказание для одного матча + рынка.

    Attributes:
        id: Автоинкрементный PK.
        match_id: Идентификатор матча (из source).
        tournament: Название турнира (e.g. ``uel_kz_1``).
        market: Тип рынка (e.g. ``winner``, ``total``).
        market_spec: Спецификация рынка (e.g. ``winner``, ``total_over``).
        home_player: Имя домашнего игрока/команды.
        away_player: Имя гостевого игрока/команды.
        match_datetime: Время начала матча.
        model_version: Версия модели (e.g. ``catboost_basic_prod``).
        algorithm: Алгоритм (e.g. ``catboost``).
        featureset: Набор фичей (e.g. ``basic``).
        predictions_json: JSON-строка с вероятностями.
        proba_home: Вероятность победы home (для быстрой фильтрации).
        proba_away: Вероятность победы away.
        odds_raw: Сырые коэффициенты букмекера (JSON-строка).
        prediction_ts: Время расчёта предсказания.
        status: Статус предсказания (ok, stale, error).
        created_at: Время создания записи.
        updated_at: Время последнего обновления.
    """

    __tablename__ = "predictions"

    id: int = Column(Integer, primary_key=True, autoincrement=True)

    # Match identification
    match_id: str = Column(String(64), nullable=False, index=True)
    tournament: str = Column(String(64), nullable=False, index=True)
    market: str = Column(String(32), nullable=False)
    market_spec: str = Column(String(32), nullable=False)

    # Players / Teams
    home_player: str | None = Column(String(128), nullable=True)
    away_player: str | None = Column(String(128), nullable=True)
    match_datetime: datetime | None = Column(DateTime, nullable=True)

    # Model info
    model_version: str = Column(String(128), nullable=False)
    model_pool: str | None = Column(String(128), nullable=True, index=True)
    immutable_model_version: str | None = Column(String(192), nullable=True, index=True)
    refresh_run_id: str | None = Column(String(128), nullable=True, index=True)
    canonical_snapshot_id: str | None = Column(String(128), nullable=True, index=True)
    feature_contract_id: str | None = Column(String(128), nullable=True)
    algorithm: str = Column(String(32), nullable=False)
    featureset: str = Column(String(32), nullable=False)
    model_tag: str = Column(
        String(16), nullable=False, default="prod"
    )  # prod / shadow / challenger

    # Predictions
    predictions_json: str = Column(Text, nullable=False)
    proba_home: float | None = Column(Float, nullable=True)
    proba_away: float | None = Column(Float, nullable=True)

    # Odds
    odds_raw: str | None = Column(Text, nullable=True)

    # Metadata
    prediction_ts: datetime = Column(
        DateTime,
        nullable=False,
        server_default=func.now(),
    )
    status: str = Column(String(16), nullable=False, default="ok")

    created_at: datetime = Column(
        DateTime,
        nullable=False,
        server_default=func.now(),
    )
    updated_at: datetime = Column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # Composite indexes for fast lookups
    __table_args__ = (
        Index("ix_pred_match_market", "match_id", "market", "market_spec"),
        Index("ix_pred_tournament_status", "tournament", "status"),
        Index("ix_pred_prediction_ts", "prediction_ts"),
    )

    def __repr__(self) -> str:
        return (
            f"<Prediction(match_id={self.match_id!r}, "
            f"tournament={self.tournament!r}, "
            f"market={self.market!r}, "
            f"status={self.status!r})>"
        )


class ModelDeployment(Base):
    """Неизменяемая версия модели и её явное состояние в registry.

    ``is_active`` — указатель production для пары ``model_pool/market_spec``.
    Предыдущие записи не удаляются: rollback переключает указатель на одну из
    сохранённых версий.
    """

    __tablename__ = "model_deployments"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    model_pool: str = Column(String(128), nullable=False, index=True)
    market_spec: str = Column(String(64), nullable=False)
    model_identity: str = Column(String(192), nullable=False, unique=True)
    candidate_report_ref: str = Column(String(512), nullable=False)
    artifact_ref: str = Column(String(512), nullable=False)
    is_active: bool = Column(Boolean, nullable=False, default=False)
    promoted_at: datetime = Column(DateTime, nullable=False, server_default=func.now())

    __table_args__ = (
        Index("ix_model_deployment_pool_spec_active", "model_pool", "market_spec", "is_active"),
    )


class WorkerExecution(Base):
    """Безопасный lifecycle одного bounded запуска materialization Worker."""

    __tablename__ = "worker_executions"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    run_id: str = Column(String(128), nullable=False, unique=True)
    status: str = Column(String(16), nullable=False)
    predictions_count: int | None = Column(Integer, nullable=True)
    failure_code: str | None = Column(String(64), nullable=True)
    started_at: datetime = Column(DateTime, nullable=False, server_default=func.now())
    completed_at: datetime | None = Column(DateTime, nullable=True)

    __table_args__ = (Index("ix_worker_executions_status", "status"),)


class CanonicalEvent(Base):
    """Текущее canonical-состояние спортивного события от поставщика данных."""

    __tablename__ = "canonical_events"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    sport: str = Column(String(64), nullable=False, index=True)
    tournament: str = Column(String(64), nullable=False, index=True)
    source: str = Column(String(128), nullable=False)
    source_event_id: str = Column(String(128), nullable=False)
    scheduled_at: datetime = Column(DateTime, nullable=False, index=True)
    status: str = Column(String(16), nullable=False)
    current_revision_sha256: str = Column(String(64), nullable=False)
    home_participant: str | None = Column(String(128), nullable=True)
    away_participant: str | None = Column(String(128), nullable=True)
    first_ingested_at: datetime = Column(DateTime, nullable=False, server_default=func.now())
    last_ingested_at: datetime = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "tournament", "source", "source_event_id", name="uq_canonical_event_source"
        ),
        Index("ix_canonical_event_tournament_schedule", "tournament", "scheduled_at"),
    )


class CanonicalEventRevision(Base):
    """Неизменяемая revision canonical event с provider payload и результатом."""

    __tablename__ = "canonical_event_revisions"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    canonical_event_id: int = Column(ForeignKey("canonical_events.id"), nullable=False, index=True)
    revision_sha256: str = Column(String(64), nullable=False)
    payload_json: str = Column(Text, nullable=False)
    result_json: str = Column(Text, nullable=False)
    source_observed_at: datetime = Column(DateTime, nullable=False)
    ingested_at: datetime = Column(DateTime, nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint(
            "canonical_event_id", "revision_sha256", name="uq_canonical_event_revision"
        ),
    )


class RegistryIdentitySnapshot(Base):
    """Полный immutable projection локальной идентичности в server DB."""

    __tablename__ = "registry_identity_snapshots"

    snapshot_id: str = Column(String(68), primary_key=True)
    snapshot_kind: str = Column(String(32), nullable=False)
    projection_sha256: str = Column(String(64), nullable=False)
    projection_schema_version: int = Column(Integer, nullable=False)
    policy_version: str = Column(String(64), nullable=False)
    normalization_version: str = Column(String(64), nullable=False)
    projection_json: str = Column(Text, nullable=False)
    manifest_json: str | None = Column(Text, nullable=True)
    created_at: datetime = Column(DateTime, nullable=False, server_default=func.now())


class RegistrySnapshotRecord(Base):
    """Неизменяемая строка одного JSONL файла установленного полного snapshot."""

    __tablename__ = "registry_snapshot_records"

    snapshot_id: str = Column(
        ForeignKey("registry_identity_snapshots.snapshot_id"), primary_key=True
    )
    file_name: str = Column(String(32), primary_key=True)
    record_key: str = Column(String(256), primary_key=True)
    payload_json: str = Column(Text, nullable=False)


class RegistryPublication(Base):
    """Неизменяемая запись установленной Object Storage publication."""

    __tablename__ = "registry_publications"

    publication_sequence: int = Column(BigInteger, primary_key=True)
    publication_id: str = Column(String(128), nullable=False, unique=True)
    snapshot_id: str = Column(ForeignKey("registry_identity_snapshots.snapshot_id"), nullable=False)
    previous_publication_id: str | None = Column(String(128), nullable=True)
    published_at: datetime = Column(DateTime, nullable=False)
    actor: str = Column(String(64), nullable=False)
    created_at: datetime = Column(DateTime, nullable=False, server_default=func.now())


class ActiveRegistryInstallation(Base):
    """Один атомарный указатель на активную публикацию registry."""

    __tablename__ = "active_registry_installation"

    id: int = Column(Integer, primary_key=True)
    publication_sequence: int = Column(BigInteger, nullable=False)
    publication_id: str = Column(String(128), nullable=False)
    snapshot_id: str = Column(ForeignKey("registry_identity_snapshots.snapshot_id"), nullable=False)
    activated_at: datetime = Column(DateTime, nullable=False, server_default=func.now())


class RegistryInstallationLock(Base):
    """Сериализует installer включая первоначальное создание active pointer."""

    __tablename__ = "registry_installation_locks"

    id: int = Column(Integer, primary_key=True)
    lock_version: int = Column(Integer, nullable=False, default=0)


class RegistryEventResolverProjection(Base):
    """Проверяемая ev1 проекция, производная от полного ir1 snapshot."""

    __tablename__ = "registry_event_resolver_projections"

    snapshot_id: str = Column(
        ForeignKey("registry_identity_snapshots.snapshot_id"), primary_key=True
    )
    event_snapshot_id: str = Column(String(68), nullable=False)
    projection_sha256: str = Column(String(64), nullable=False)
    projection_json: str = Column(Text, nullable=False)


class EventRegistryMapping(Base):
    """Project event bridge закреплённого registry snapshot."""

    __tablename__ = "registry_canonical_event_mappings"

    snapshot_id: str = Column(
        String(80), ForeignKey("registry_identity_snapshots.snapshot_id"), primary_key=True
    )
    canonical_event_id: int = Column(
        ForeignKey("canonical_events.id"), primary_key=True, nullable=False
    )
    project_event_id: str | None = Column(String(36), nullable=True)
    status: str = Column(String(16), nullable=False)
    reason: str = Column(Text, nullable=False)
    policy_version: str = Column(String(64), nullable=False)
    decision_id: str | None = Column(String(36), nullable=True)

    __table_args__ = (
        CheckConstraint("status IN ('resolved','unresolved','ambiguous','conflict')"),
        CheckConstraint(
            "(status = 'resolved' AND project_event_id IS NOT NULL) OR "
            "(status <> 'resolved' AND project_event_id IS NULL)"
        ),
        Index("ix_registry_event_mapping_canonical", "canonical_event_id", "snapshot_id"),
    )


class CalendarCoverage(Base):
    """Последняя проверка полноты календарного окна по источнику."""

    __tablename__ = "calendar_coverages"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    tournament: str = Column(String(64), nullable=False)
    source: str = Column(String(128), nullable=False)
    covered_from: datetime = Column(DateTime, nullable=False)
    covered_until: datetime = Column(DateTime, nullable=False)
    complete: bool = Column(Boolean, nullable=False)
    checked_at: datetime = Column(DateTime, nullable=False)
    last_successful_at: datetime | None = Column(DateTime, nullable=True)
    failure_code: str | None = Column(String(64), nullable=True)

    __table_args__ = (
        UniqueConstraint("tournament", "source", name="uq_calendar_coverage_source"),
        Index("ix_calendar_coverages_window", "tournament", "covered_from", "covered_until"),
    )


class OddsObservation(Base):
    """Последняя подтверждённая линия для canonical event, рынка и букмекера."""

    __tablename__ = "odds_observations"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    canonical_event_id: int = Column(ForeignKey("canonical_events.id"), nullable=False, index=True)
    market: str = Column(String(32), nullable=False)
    market_spec: str = Column(String(64), nullable=False)
    bookmaker: str = Column(String(64), nullable=False)
    event_scheduled_at: datetime = Column(DateTime, nullable=False)
    event_home_participant: str = Column(String(128), nullable=False)
    event_away_participant: str = Column(String(128), nullable=False)
    observed_at: datetime = Column(DateTime, nullable=False)
    observed_at_source: str | None = Column(String(64), nullable=True)
    retrieved_at: datetime | None = Column(DateTime, nullable=True)
    provider_event_id: str | None = Column(String(128), nullable=True)
    values_json: str = Column(Text, nullable=False)
    source: str = Column(String(128), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "canonical_event_id",
            "market",
            "market_spec",
            "bookmaker",
            name="uq_odds_observation_event_market_bookmaker",
        ),
        Index("ix_odds_observation_event", "canonical_event_id", "observed_at"),
    )


class OddsAcquisitionAttempt(Base):
    """Безопасный outcome одной batch-попытки получения будущих odds."""

    __tablename__ = "odds_acquisition_attempts"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    run_id: str = Column(ForeignKey("data_cycle_runs.run_id"), nullable=False)
    tournament: str = Column(String(64), nullable=False)
    provider: str = Column(String(64), nullable=False)
    status: str = Column(String(16), nullable=False)
    failure_code: str | None = Column(String(64), nullable=True)
    retrieved_at: datetime = Column(DateTime, nullable=False)
    window_from: datetime | None = Column(DateTime, nullable=True)
    window_to: datetime | None = Column(DateTime, nullable=True)
    provider_events: int = Column(Integer, nullable=False, default=0)
    matched_events: int = Column(Integer, nullable=False, default=0)
    missing_events: int = Column(Integer, nullable=False, default=0)
    rejected_events: int = Column(Integer, nullable=False, default=0)
    requests_remaining: int | None = Column(Integer, nullable=True)
    requests_used: int | None = Column(Integer, nullable=True)

    __table_args__ = (
        CheckConstraint("status IN ('success','partial_success','failed')"),
        UniqueConstraint("run_id", "provider", name="uq_odds_attempt_run_provider"),
        Index("ix_odds_acquisition_attempt_tournament", "tournament", "retrieved_at"),
    )


class DataCycleRun(Base):
    """Долговечный итог полного цикла сбора данных и публикации."""

    __tablename__ = "data_cycle_runs"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    run_id: str = Column(String(128), nullable=False, unique=True)
    tournament: str = Column(String(64), nullable=False, index=True)
    reason: str = Column(String(16), nullable=False)
    status: str = Column(String(24), nullable=False, server_default="waiting")
    current_stage: str | None = Column(String(32), nullable=True)
    failure_code: str | None = Column(String(64), nullable=True)
    summary_json: str | None = Column(Text, nullable=True)
    scheduled_for: datetime | None = Column(DateTime, nullable=True)
    requested_at: datetime = Column(DateTime, nullable=False, server_default=func.now())
    started_at: datetime | None = Column(DateTime, nullable=True)
    heartbeat_at: datetime | None = Column(DateTime, nullable=True)
    completed_at: datetime | None = Column(DateTime, nullable=True)
    executor_generation: int = Column(Integer, nullable=False, default=0, server_default="0")
    executor_owner_id: str | None = Column(String(64), nullable=True)
    executor_stalled_at: datetime | None = Column(DateTime, nullable=True)
    owner_stop_verified_at: datetime | None = Column(DateTime, nullable=True)
    stopped_container_count: int | None = Column(Integer, nullable=True)

    stages = relationship(
        "DataCycleStageResult", back_populates="run", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("status IN ('waiting','running','success','partial_success','failed')"),
        CheckConstraint("reason IN ('scheduled','manual','retry')"),
        CheckConstraint("executor_generation >= 0"),
        CheckConstraint("stopped_container_count IS NULL OR stopped_container_count >= 0"),
        Index(
            "uq_data_cycle_active_tournament",
            "tournament",
            unique=True,
            sqlite_where=text("status IN ('waiting', 'running')"),
            postgresql_where=text("status IN ('waiting', 'running')"),
        ),
        Index("ix_data_cycle_runs_requested", "tournament", "requested_at"),
    )


class DataCycleStageResult(Base):
    """Состояние и счётчики одной фиксированной стадии Data Cycle."""

    __tablename__ = "data_cycle_stage_results"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    run_id: str = Column(ForeignKey("data_cycle_runs.run_id"), nullable=False, index=True)
    stage: str = Column(String(32), nullable=False)
    status: str = Column(String(24), nullable=False, server_default="waiting")
    failure_code: str | None = Column(String(64), nullable=True)
    counts_json: str | None = Column(Text, nullable=True)
    started_at: datetime | None = Column(DateTime, nullable=True)
    completed_at: datetime | None = Column(DateTime, nullable=True)
    run = relationship("DataCycleRun", back_populates="stages")

    __table_args__ = (
        UniqueConstraint("run_id", "stage", name="uq_data_cycle_stage"),
        CheckConstraint(
            "stage IN ('calendar','data_odds','quality','predictions','publication','archive_sync')"
        ),
        CheckConstraint(
            "status IN ('waiting','running','success','partial_success','failed','skipped')"
        ),
        Index("ix_data_cycle_stages_run_status", "run_id", "status"),
    )


class PipelineSchedule(Base):
    """Персистентная бизнес-настройка расписания pipeline."""

    __tablename__ = "pipeline_schedules"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    pipeline_id: str = Column(String(64), nullable=False, unique=True)
    enabled: bool = Column(Boolean, nullable=False, default=False)
    base_time: str = Column(String(5), nullable=False, default="10:00")
    timezone: str = Column(String(64), nullable=False, default="Europe/Moscow")
    interval_hours: int = Column(Integer, nullable=False, default=24)
    revision: int = Column(Integer, nullable=False, default=1)
    next_run_at: datetime | None = Column(DateTime, nullable=True)
    last_run_at: datetime | None = Column(DateTime, nullable=True)
    last_missed_slots: int = Column(Integer, nullable=False, default=0)
    updated_at: datetime = Column(DateTime, nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint("interval_hours IN (4,6,8,12,24)"),
        CheckConstraint("revision >= 1"),
        CheckConstraint("last_missed_slots >= 0"),
    )


class DataCycleControlRequest(Base):
    """Идемпотентный ключ принятого API/dispatcher запроса на Data Cycle."""

    __tablename__ = "data_cycle_control_requests"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    idempotency_key: str = Column(String(192), nullable=False, unique=True)
    pipeline_id: str = Column(String(64), nullable=False)
    run_id: str = Column(ForeignKey("data_cycle_runs.run_id"), nullable=False)
    created_at: datetime = Column(DateTime, nullable=False, server_default=func.now())

    __table_args__ = (Index("ix_data_cycle_control_requests_run", "run_id"),)


class DataCycleDispatcherState(Base):
    """Heartbeat host dispatcher для объяснимости просроченного scheduler."""

    __tablename__ = "data_cycle_dispatcher_state"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    dispatcher_id: str = Column(String(64), nullable=False, unique=True)
    heartbeat_at: datetime = Column(DateTime, nullable=False)


class DataCycleNotificationOutbox(Base):
    """Durable terminal notification per Data Cycle run and safe destination alias."""

    __tablename__ = "data_cycle_notification_outbox"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    run_id: str = Column(ForeignKey("data_cycle_runs.run_id"), nullable=False)
    destination_alias: str = Column(String(64), nullable=False)
    status: str = Column(String(16), nullable=False, server_default="pending")
    attempts: int = Column(Integer, nullable=False, server_default="0")
    available_at: datetime = Column(DateTime, nullable=False, server_default=func.now())
    lease_token: str | None = Column(String(36), nullable=True)
    lease_until: datetime | None = Column(DateTime, nullable=True)
    last_error_code: str | None = Column(String(32), nullable=True)
    created_at: datetime = Column(DateTime, nullable=False, server_default=func.now())
    delivered_at: datetime | None = Column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "run_id", "destination_alias", name="uq_data_cycle_notification_run_alias"
        ),
        CheckConstraint("status IN ('pending','leased','delivered')"),
        CheckConstraint("attempts >= 0"),
        CheckConstraint("length(destination_alias) BETWEEN 1 AND 64"),
        Index(
            "ix_data_cycle_notification_claim",
            "status",
            "available_at",
            "lease_until",
            "created_at",
        ),
    )


class RefreshWatermark(Base):
    """Последний успешно imported canonical snapshot одного турнира."""

    __tablename__ = "refresh_watermarks"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    tournament: str = Column(String(64), nullable=False, unique=True)
    source: str = Column(String(128), nullable=False)
    snapshot_id: str = Column(String(80), nullable=False)
    updated_at: datetime = Column(DateTime, nullable=False, server_default=func.now())


class BootstrapImport(Base):
    """Идемпотентный audit одной immutable initial bootstrap поставки."""

    __tablename__ = "bootstrap_imports"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    artifact_id: str = Column(String(80), nullable=False, unique=True)
    tournament: str = Column(String(64), nullable=False, index=True)
    source: str = Column(String(128), nullable=False)
    status: str = Column(String(16), nullable=False)
    events_count: int = Column(Integer, nullable=False)
    imported_at: datetime = Column(DateTime, nullable=False, server_default=func.now())


class RefreshFailureAlert(Base):
    """Pending admin-only alert одного failed refresh run без внешнего payload."""

    __tablename__ = "refresh_failure_alerts"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    run_id: str = Column(String(128), nullable=False, unique=True)
    tournament: str = Column(String(64), nullable=False, index=True)
    failure_code: str = Column(String(64), nullable=False)
    status: str = Column(String(16), nullable=False, default="pending")
    attempts: int = Column(Integer, nullable=False, default=0)
    created_at: datetime = Column(DateTime, nullable=False, server_default=func.now())


class RefreshLock(Base):
    """Durable ownership одного tournament refresh."""

    __tablename__ = "refresh_locks"
    id: int = Column(Integer, primary_key=True, autoincrement=True)
    tournament: str = Column(String(64), nullable=False, unique=True)
    run_id: str = Column(String(128), nullable=False)
    acquired_at: datetime = Column(DateTime, nullable=False, server_default=func.now())


class TournamentPublicationState(Base):
    """Eligibility public-витрины одного tournament/market/spec среза."""

    __tablename__ = "tournament_publication_states"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    tournament: str = Column(String(64), nullable=False)
    market: str = Column(String(32), nullable=False)
    market_spec: str = Column(String(32), nullable=False)
    status: str = Column(String(16), nullable=False)
    run_id: str | None = Column(String(128), nullable=True)
    updated_at: datetime = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("tournament", "market", "market_spec", name="uq_publication_slice"),
        Index("ix_publication_state_tournament", "tournament", "status"),
    )


class LineupPredictionRevision(Base):
    """Версия прогноза, созданная для confirmed состава одного матча."""

    __tablename__ = "lineup_prediction_revisions"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    match_id: str = Column(String(64), nullable=False)
    tournament: str = Column(String(64), nullable=False)
    model_pool: str = Column(String(128), nullable=False)
    immutable_model_version: str = Column(String(192), nullable=False)
    lineup_state: str = Column(String(16), nullable=False, default="confirmed")
    lineup_source: str = Column(String(128), nullable=False)
    lineup_received_at: datetime = Column(DateTime, nullable=False)
    lineup_fingerprint: str = Column(String(192), nullable=False, unique=True)
    prediction_json: str = Column(Text, nullable=False)
    created_at: datetime = Column(DateTime, nullable=False, server_default=func.now())


class LineupNotificationOutbox(Base):
    """Outbox Telegram-доставки после надёжной записи lineup revision."""

    __tablename__ = "lineup_notification_outbox"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    revision_id: int = Column(Integer, nullable=False, unique=True)
    status: str = Column(String(16), nullable=False, default="pending")
    attempts: int = Column(Integer, nullable=False, default=0)
    created_at: datetime = Column(DateTime, nullable=False, server_default=func.now())


class NotificationLineState(Base):
    """Последняя валидная линия для матча в notification-профиле."""

    __tablename__ = "notification_line_states"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    profile_id: str = Column(String(128), nullable=False)
    match_id: str = Column(String(64), nullable=False)
    line_json: str = Column(Text, nullable=False)
    updated_at: datetime = Column(DateTime, nullable=False, server_default=func.now())

    __table_args__ = (
        Index("uq_notification_line_profile_match", "profile_id", "match_id", unique=True),
    )


class NotificationCycle(Base):
    """Одно агрегированное событие изменения линий за логический цикл."""

    __tablename__ = "notification_cycles"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    profile_id: str = Column(String(128), nullable=False)
    logical_cycle: str = Column(String(128), nullable=False)
    changes_json: str = Column(Text, nullable=False)
    created_at: datetime = Column(DateTime, nullable=False, server_default=func.now())

    __table_args__ = (
        Index("uq_notification_cycle_profile_cycle", "profile_id", "logical_cycle", unique=True),
    )


class NotificationDelivery(Base):
    """Состояние доставки агрегированного события одному получателю."""

    __tablename__ = "notification_deliveries"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    cycle_id: int = Column(Integer, nullable=False, index=True)
    chat_id: str = Column(String(64), nullable=False)
    status: str = Column(String(16), nullable=False, default="pending")
    attempts: int = Column(Integer, nullable=False, default=0)
    sent_at: datetime | None = Column(DateTime, nullable=True)
    updated_at: datetime = Column(DateTime, nullable=False, server_default=func.now())

    __table_args__ = (
        Index("uq_notification_delivery_cycle_chat", "cycle_id", "chat_id", unique=True),
    )
