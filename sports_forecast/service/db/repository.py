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
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import and_
from sqlalchemy.orm import Session

from sports_forecast.service.db.models import (
    LineupNotificationOutbox,
    LineupPredictionRevision,
    ModelDeployment,
    NotificationCycle,
    NotificationDelivery,
    NotificationLineState,
    Prediction,
    WorkerExecution,
)


def _utc_naive_for_query(dt: datetime) -> datetime:
    """Привести момент времени к naive UTC для сравнения с ``DateTime`` в БД.

    В dev чаще SQLite без таймзоны; витрина хранит ``match_datetime`` как UTC wall time.
    """
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(UTC).replace(tzinfo=None)


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
        market_spec: str | None = None,
        status: str = "ok",
        hours: int = 48,
        *,
        now_utc: datetime | None = None,
    ) -> list[Prediction]:
        """Получить актуальные предсказания для предстоящих матчей.

        Учитываются только строки с непустым ``match_datetime`` в окне
        ``[now_utc, now_utc + hours]`` (границы в UTC). Строки без времени матча
        в выборку не попадают.

        Args:
            tournament: Фильтр по турниру (опционально).
            market: Тип рынка.
            market_spec: Спецификация рынка (опционально; если задана — точное совпадение).
            status: Статус предсказания.
            hours: Длина окна в часах от ``now_utc`` вперёд (по умолчанию 48).
            now_utc: Опорный момент «сейчас» в UTC (для тестов); иначе ``datetime.now(UTC)``.

        Returns:
            Список Prediction, отсортированных по match_datetime.
        """
        now = now_utc if now_utc is not None else datetime.now(tz=UTC)
        start = _utc_naive_for_query(now)
        end = _utc_naive_for_query(now + timedelta(hours=hours))

        query = self.session.query(Prediction).filter(
            and_(
                Prediction.market == market,
                Prediction.status == status,
                Prediction.match_datetime.isnot(None),  # type: ignore[attr-defined]
                Prediction.match_datetime >= start,  # type: ignore[operator]
                Prediction.match_datetime <= end,  # type: ignore[operator]
            )
        )

        if tournament is not None:
            query = query.filter(Prediction.tournament == tournament)

        if market_spec is not None:
            query = query.filter(Prediction.market_spec == market_spec)

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
        model_pool: str | None = None,
        immutable_model_version: str | None = None,
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
        now = datetime.now(tz=UTC)

        if existing is not None:
            # Update
            existing.predictions_json = predictions_json
            existing.model_version = model_version
            existing.algorithm = algorithm
            existing.featureset = featureset
            existing.model_pool = model_pool
            existing.immutable_model_version = immutable_model_version
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
            model_pool=model_pool,
            immutable_model_version=immutable_model_version,
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

    def publish_showcase(
        self,
        records: list[dict[str, Any]],
        *,
        tournament: str,
        market: str,
        market_spec: str,
    ) -> int:
        """Атомарно заменить один срез витрины внутри внешней DB-транзакции.

        Исключение не перехватывается: ``get_session`` откатит и stale-метки,
        и уже записанные строки, сохранив прежнюю валидную витрину.
        """
        self.mark_stale(tournament=tournament, market=market, market_spec=market_spec)
        return self.bulk_upsert(records)

    def count_showcase(self, *, tournament: str, market: str, market_spec: str) -> int:
        """Вернуть число опубликованных строк одного serving-среза."""
        return int(
            self.session.query(Prediction)
            .filter(
                and_(
                    Prediction.tournament == tournament,
                    Prediction.market == market,
                    Prediction.market_spec == market_spec,
                    Prediction.status == "ok",
                )
            )
            .count()
        )

    def mark_stale(
        self,
        tournament: str | None = None,
        before_ts: datetime | None = None,
        *,
        market: str | None = None,
        market_spec: str | None = None,
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
        if market is not None:
            query = query.filter(Prediction.market == market)
        if market_spec is not None:
            query = query.filter(Prediction.market_spec == market_spec)

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


class WorkerExecutionRepository:
    """Хранилище безопасного idempotency и outcome state Worker."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, run_id: str) -> WorkerExecution | None:
        """Вернуть состояние запуска по scheduler-safe идентификатору."""
        return cast(
            WorkerExecution | None,
            self.session.query(WorkerExecution).filter_by(run_id=run_id).one_or_none(),
        )

    def start(self, run_id: str) -> bool:
        """Создать running state; вернуть False для уже завершённого запуска."""
        if self.get(run_id) is not None:
            return False
        self.session.add(WorkerExecution(run_id=run_id, status="running"))
        self.session.flush()
        return True

    def succeed(self, run_id: str, *, predictions_count: int) -> None:
        """Сохранить безопасный итог успешного запуска."""
        state = self._require_running(run_id)
        state.status = "succeeded"
        state.predictions_count = predictions_count
        state.completed_at = datetime.now(tz=UTC)

    def fail(self, run_id: str, *, failure_code: str) -> None:
        """Сохранить только allow-listed код неуспеха без текста ошибки."""
        state = self._require_running(run_id)
        state.status = "failed"
        state.failure_code = failure_code
        state.completed_at = datetime.now(tz=UTC)

    def _require_running(self, run_id: str) -> WorkerExecution:
        state = self.get(run_id)
        if state is None or state.status != "running":
            raise ValueError(f"Worker run недоступен для завершения: {run_id}")
        return state


class ModelRegistryRepository:
    """Хранилище immutable версий и явных production pointers."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def promote(
        self,
        *,
        model_pool: str,
        market_spec: str,
        model_identity: str,
        candidate_report_ref: str,
        artifact_ref: str,
    ) -> ModelDeployment:
        """Явно создать новую immutable версию и сделать её production pointer."""
        if not model_identity.startswith(f"pool:{model_pool}:{market_spec}:"):
            raise ValueError("model_identity не соответствует model_pool/market_spec")
        if not candidate_report_ref or not artifact_ref:
            raise ValueError("Promotion требует ссылки на report кандидата и артефакт")
        if self.get_by_identity(model_identity) is not None:
            raise ValueError("Immutable model_identity уже зарегистрирован")
        self.session.query(ModelDeployment).filter(
            ModelDeployment.model_pool == model_pool,
            ModelDeployment.market_spec == market_spec,
            ModelDeployment.is_active.is_(True),  # type: ignore[attr-defined]
        ).update({"is_active": False})
        deployment = ModelDeployment(
            model_pool=model_pool,
            market_spec=market_spec,
            model_identity=model_identity,
            candidate_report_ref=candidate_report_ref,
            artifact_ref=artifact_ref,
            is_active=True,
        )
        self.session.add(deployment)
        self.session.flush()
        return deployment

    def get_active(self, model_pool: str, market_spec: str) -> ModelDeployment | None:
        """Вернуть текущий production pointer пула или ``None``."""
        return cast(
            ModelDeployment | None,
            self.session.query(ModelDeployment)
            .filter(
                ModelDeployment.model_pool == model_pool,
                ModelDeployment.market_spec == market_spec,
                ModelDeployment.is_active.is_(True),  # type: ignore[attr-defined]
            )
            .one_or_none(),
        )

    def rollback(self, model_pool: str, market_spec: str, model_identity: str) -> ModelDeployment:
        """Явно вернуть pointer к ранее сохранённой версии без удаления записей."""
        deployment = self.get_by_identity(model_identity)
        if (
            deployment is None
            or deployment.model_pool != model_pool
            or deployment.market_spec != market_spec
        ):
            raise ValueError("Версия для rollback не найдена в указанном model pool")
        self.session.query(ModelDeployment).filter(
            ModelDeployment.model_pool == model_pool,
            ModelDeployment.market_spec == market_spec,
            ModelDeployment.is_active.is_(True),  # type: ignore[attr-defined]
        ).update({"is_active": False})
        deployment.is_active = True
        self.session.flush()
        return deployment

    def get_by_identity(self, model_identity: str) -> ModelDeployment | None:
        """Найти сохранённую immutable версию по её identity."""
        return cast(
            ModelDeployment | None,
            self.session.query(ModelDeployment)
            .filter(ModelDeployment.model_identity == model_identity)
            .one_or_none(),
        )


class LineupFastPathRepository:
    """DB-first запись confirmed состава и outbox для retry-доставки."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def record_confirmed_lineup(
        self,
        *,
        match_id: str,
        tournament: str,
        model_pool: str,
        immutable_model_version: str,
        lineup_source: str,
        lineup_received_at: datetime,
        lineup_fingerprint: str,
        prediction_json: str,
    ) -> tuple[LineupPredictionRevision, bool]:
        """Создать revision и pending outbox либо вернуть прежнюю по fingerprint."""
        existing = cast(
            LineupPredictionRevision | None,
            self.session.query(LineupPredictionRevision)
            .filter(LineupPredictionRevision.lineup_fingerprint == lineup_fingerprint)
            .one_or_none(),
        )
        if existing is not None:
            return existing, False
        revision = LineupPredictionRevision(
            match_id=match_id,
            tournament=tournament,
            model_pool=model_pool,
            immutable_model_version=immutable_model_version,
            lineup_source=lineup_source,
            lineup_received_at=lineup_received_at,
            lineup_fingerprint=lineup_fingerprint,
            prediction_json=prediction_json,
        )
        self.session.add(revision)
        self.session.flush()
        self.session.add(LineupNotificationOutbox(revision_id=revision.id))
        self.session.flush()
        return revision, True

    def pending_delivery_count(self) -> int:
        """Вернуть число pending outbox записей для проверки и worker-а."""
        return int(
            self.session.query(LineupNotificationOutbox)
            .filter(LineupNotificationOutbox.status == "pending")
            .count()
        )

    def get_pending_deliveries(self) -> list[LineupNotificationOutbox]:
        """Вернуть outbox deliveries, ожидающие Telegram retry."""
        return cast(
            list[LineupNotificationOutbox],
            self.session.query(LineupNotificationOutbox)
            .filter(LineupNotificationOutbox.status == "pending")
            .order_by(LineupNotificationOutbox.id.asc())  # type: ignore[attr-defined]
            .all(),
        )

    def mark_delivery_sent(self, delivery: LineupNotificationOutbox) -> None:
        """Зафиксировать успешную доставку без изменения revision."""
        delivery.status = "sent"
        delivery.attempts += 1
        self.session.flush()

    def record_delivery_failure(self, delivery: LineupNotificationOutbox) -> None:
        """Зафиксировать неуспешную попытку, оставив outbox доступным для retry."""
        delivery.attempts += 1
        self.session.flush()


class NotificationStateRepository:
    """Repository персистентного состояния и delivery ledger уведомлений."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_line(self, profile_id: str, match_id: str) -> NotificationLineState | None:
        """Вернуть последнюю валидную линию матча."""
        return cast(
            NotificationLineState | None,
            self.session.query(NotificationLineState)
            .filter(
                NotificationLineState.profile_id == profile_id,
                NotificationLineState.match_id == match_id,
            )
            .one_or_none(),
        )

    def save_line(self, profile_id: str, match_id: str, line_json: str) -> None:
        """Сохранить или обновить последнюю валидную линию матча."""
        existing = self.get_line(profile_id, match_id)
        if existing is None:
            self.session.add(
                NotificationLineState(
                    profile_id=profile_id,
                    match_id=match_id,
                    line_json=line_json,
                )
            )
            self.session.flush()
            return
        existing.line_json = line_json
        existing.updated_at = datetime.now(tz=UTC).replace(tzinfo=None)

    def get_cycle(self, profile_id: str, logical_cycle: str) -> NotificationCycle | None:
        """Найти агрегированное событие логического цикла."""
        return cast(
            NotificationCycle | None,
            self.session.query(NotificationCycle)
            .filter(
                NotificationCycle.profile_id == profile_id,
                NotificationCycle.logical_cycle == logical_cycle,
            )
            .one_or_none(),
        )

    def create_cycle(
        self,
        profile_id: str,
        logical_cycle: str,
        changes_json: str,
    ) -> NotificationCycle:
        """Создать единственное агрегированное событие цикла."""
        cycle = NotificationCycle(
            profile_id=profile_id,
            logical_cycle=logical_cycle,
            changes_json=changes_json,
        )
        self.session.add(cycle)
        self.session.flush()
        return cycle

    def reserve_delivery(self, cycle_id: int, chat_id: str) -> NotificationDelivery | None:
        """Зарезервировать доставку или вернуть pending-запись для повторной попытки.

        Успешно отправленная запись возвращает ``None`` и не может быть отправлена
        повторно в том же логическом цикле.
        """
        delivery = cast(
            NotificationDelivery | None,
            self.session.query(NotificationDelivery)
            .filter(
                NotificationDelivery.cycle_id == cycle_id,
                NotificationDelivery.chat_id == str(chat_id),
            )
            .one_or_none(),
        )
        if delivery is not None:
            if delivery.status == "sent":
                return None
            delivery.attempts += 1
            delivery.updated_at = datetime.now(tz=UTC).replace(tzinfo=None)
            return delivery

        delivery = NotificationDelivery(cycle_id=cycle_id, chat_id=str(chat_id), attempts=1)
        self.session.add(delivery)
        self.session.flush()
        return delivery

    def mark_delivery_sent(self, delivery: NotificationDelivery) -> None:
        """Надёжно зафиксировать успех до доставки следующему получателю."""
        sent_at = datetime.now(tz=UTC).replace(tzinfo=None)
        delivery.status = "sent"
        delivery.sent_at = sent_at
        delivery.updated_at = sent_at
        self.session.commit()

    def mark_delivery_failed(self, delivery: NotificationDelivery) -> None:
        """Надёжно зафиксировать неуспех, оставив получателя доступным для retry."""
        delivery.status = "failed"
        delivery.updated_at = datetime.now(tz=UTC).replace(tzinfo=None)
        self.session.commit()
