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
