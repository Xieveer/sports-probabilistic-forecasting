"""
Repository для работы с предсказаниями в БД.

CRUD операции над таблицей ``predictions``.

Примеры::

    from sports_forecast.service.db.repository import PredictionRepository
    from sports_forecast.service.db.engine import get_session

    with get_session() as session:
        repo = PredictionRepository(session)
        pred = repo.get_latest_prediction("72272", "winner")
        preds = repo.get_upcoming_predictions("uel_kz_1")
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import and_
from sqlalchemy.orm import Session

from sports_forecast.service.db.models import Prediction


class PredictionRepository:
    """Repository для CRUD операций над предсказаниями.

    Args:
        session: SQLAlchemy Session.
    """

    def __init__(self, session: Session) -> None:
        self.session = session

    # ─────────────────────────────────────────────────────────────────
    # READ
    # ─────────────────────────────────────────────────────────────────

    def get_latest_prediction(
        self,
        match_id: str,
        market: str = "winner",
        market_spec: str | None = None,
    ) -> Prediction | None:
        """Получить последнее предсказание для матча.

        Args:
            match_id: ID матча.
            market: Тип рынка.
            market_spec: Спецификация рынка (опционально).

        Returns:
            Prediction или None.
        """
        query = self.session.query(Prediction).filter(
            and_(
                Prediction.match_id == str(match_id),
                Prediction.market == market,
            )
        )

        if market_spec is not None:
            query = query.filter(Prediction.market_spec == market_spec)

        result: Prediction | None = query.order_by(
            Prediction.prediction_ts.desc()  # type: ignore[attr-defined]
        ).first()
        return result

    def get_predictions_by_match(self, match_id: str) -> list[Prediction]:
        """Получить все предсказания для матча (все рынки).

        Args:
            match_id: ID матча.

        Returns:
            Список Prediction.
        """
        rows: list[Prediction] = (
            self.session.query(Prediction)
            .filter(Prediction.match_id == str(match_id))
            .order_by(Prediction.prediction_ts.desc())  # type: ignore[attr-defined]
            .all()
        )
        return rows

    def get_upcoming_predictions(
        self,
        tournament: str | None = None,
        market: str = "winner",
        status: str = "ok",
    ) -> list[Prediction]:
        """Получить актуальные предсказания для предстоящих матчей.

        Args:
            tournament: Фильтр по турниру (опционально).
            market: Тип рынка.
            status: Статус предсказания.

        Returns:
            Список Prediction, отсортированных по match_datetime.
        """
        query = self.session.query(Prediction).filter(
            and_(
                Prediction.market == market,
                Prediction.status == status,
            )
        )

        if tournament is not None:
            query = query.filter(Prediction.tournament == tournament)

        rows: list[Prediction] = query.order_by(
            Prediction.match_datetime.asc()  # type: ignore[attr-defined]
        ).all()
        return rows

    # ─────────────────────────────────────────────────────────────────
    # WRITE
    # ─────────────────────────────────────────────────────────────────

    def upsert_prediction(
        self,
        match_id: str,
        tournament: str,
        market: str,
        market_spec: str,
        predictions: dict[str, float],
        model_version: str,
        algorithm: str,
        featureset: str,
        home_player: str | None = None,
        away_player: str | None = None,
        match_datetime: datetime | None = None,
        proba_home: float | None = None,
        proba_away: float | None = None,
        odds_raw: str | None = None,
        status: str = "ok",
    ) -> Prediction:
        """Создать или обновить предсказание.

        Если предсказание для match_id + market + market_spec уже существует,
        обновляет его. Иначе — создаёт новое.

        Args:
            match_id: ID матча.
            tournament: Турнир.
            market: Рынок.
            market_spec: Спецификация рынка.
            predictions: Словарь вероятностей.
            model_version: Версия модели.
            algorithm: Алгоритм.
            featureset: Набор фичей.
            home_player: Домашний игрок (опционально).
            away_player: Гостевой игрок (опционально).
            match_datetime: Время матча (опционально).
            proba_home: P(home win) (опционально).
            proba_away: P(away win) (опционально).
            odds_raw: Сырые odds (опционально).
            status: Статус предсказания.

        Returns:
            Созданный или обновлённый Prediction.
        """
        existing: Prediction | None = (
            self.session.query(Prediction)
            .filter(
                and_(
                    Prediction.match_id == str(match_id),
                    Prediction.market == market,
                    Prediction.market_spec == market_spec,
                )
            )
            .first()
        )

        predictions_json = json.dumps(predictions, ensure_ascii=False)
        now = datetime.now(tz=timezone.utc)

        if existing is not None:
            # Update
            existing.predictions_json = predictions_json
            existing.model_version = model_version
            existing.algorithm = algorithm
            existing.featureset = featureset
            existing.proba_home = proba_home
            existing.proba_away = proba_away
            existing.odds_raw = odds_raw
            existing.prediction_ts = now
            existing.status = status
            existing.updated_at = now
            if home_player is not None:
                existing.home_player = home_player
            if away_player is not None:
                existing.away_player = away_player
            if match_datetime is not None:
                existing.match_datetime = match_datetime
            return existing

        # Create
        pred = Prediction(
            match_id=str(match_id),
            tournament=tournament,
            market=market,
            market_spec=market_spec,
            home_player=home_player,
            away_player=away_player,
            match_datetime=match_datetime,
            model_version=model_version,
            algorithm=algorithm,
            featureset=featureset,
            predictions_json=predictions_json,
            proba_home=proba_home,
            proba_away=proba_away,
            odds_raw=odds_raw,
            prediction_ts=now,
            status=status,
        )
        self.session.add(pred)
        return pred

    def bulk_upsert(self, records: list[dict[str, Any]]) -> int:
        """Массовая вставка/обновление предсказаний.

        Args:
            records: Список словарей с параметрами для ``upsert_prediction``.

        Returns:
            Количество обработанных записей.
        """
        count = 0
        for rec in records:
            self.upsert_prediction(**rec)
            count += 1
        return count

    def mark_stale(
        self,
        tournament: str | None = None,
        before_ts: datetime | None = None,
    ) -> int:
        """Пометить устаревшие предсказания как stale.

        Args:
            tournament: Турнир (опционально).
            before_ts: Пометить предсказания старше этого времени.

        Returns:
            Количество обновлённых записей.
        """
        query = self.session.query(Prediction).filter(Prediction.status == "ok")

        if tournament is not None:
            query = query.filter(Prediction.tournament == tournament)

        if before_ts is not None:
            query = query.filter(Prediction.prediction_ts < before_ts)

        result: int = query.update({"status": "stale"})
        return result

    def delete_old(self, before_ts: datetime) -> int:
        """Удалить предсказания старше указанного времени.

        Args:
            before_ts: Удалить всё что старше.

        Returns:
            Количество удалённых записей.
        """
        result: int = (
            self.session.query(Prediction).filter(Prediction.prediction_ts < before_ts).delete()
        )
        return result

    def get_stale_predictions(
        self,
        cutoff: datetime,
        tournament: str | None = None,
    ) -> list[Prediction]:
        """Получить предсказания, которые устарели (prediction_ts < cutoff).

        Args:
            cutoff: Порог: предсказания старше этого времени считаются stale.
            tournament: Фильтр по турниру (опционально).

        Returns:
            Список устаревших Prediction.
        """
        query = self.session.query(Prediction).filter(
            and_(
                Prediction.status == "ok",
                Prediction.prediction_ts < cutoff,
            )
        )

        if tournament is not None:
            query = query.filter(Prediction.tournament == tournament)

        rows: list[Prediction] = query.order_by(
            Prediction.prediction_ts.asc()  # type: ignore[attr-defined]
        ).all()
        return rows
