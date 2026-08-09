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
    Boolean,
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase


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
