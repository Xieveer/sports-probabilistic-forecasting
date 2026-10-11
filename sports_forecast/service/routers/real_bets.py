"""Закрытый API ручного журнала фактических ставок."""

from __future__ import annotations

import hashlib
import json
import math
import os
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal, cast
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from sports_forecast.betting.real_bets import (
    MANUAL_MARKETS_BY_SPORT,
    MARKET_OUTCOMES,
    expected_payout,
    money,
    monthly_summary,
)
from sports_forecast.service.control_auth import require_control_admin
from sports_forecast.service.db.engine import get_control_session, get_session
from sports_forecast.service.db.models import (
    BetCardContext,
    CanonicalEvent,
    PredictionRevision,
    RealBet,
    RealBetAudit,
)


router = APIRouter(prefix="/admin", tags=["real-bets"])


def require_bets_owner(admin: Annotated[str, Depends(require_control_admin)]) -> str:
    """Дополнительно ограничить журнал одним явно настроенным владельцем."""
    owner_id = os.environ.get("SF_BETS_OWNER_ID", "").strip()
    if not owner_id.isdigit() or admin != owner_id:
        raise HTTPException(status_code=403, detail="Журнал доступен только владельцу")
    return admin


class CardContextRequest(BaseModel):
    """Полученный ботом ответ /predict, который будет показан владельцу."""

    prediction: dict[str, Any]


class ManualContextRequest(BaseModel):
    """Выбранный матч календаря без опубликованного прогноза."""

    tournament: str = Field(min_length=1, max_length=64)
    match_id: str = Field(min_length=1, max_length=128)
    source_namespace: str | None = Field(default=None, max_length=128)


class BetCreateRequest(BaseModel):
    """Одно фактическое размещение с отдельным idempotency key."""

    context_id: str = Field(min_length=36, max_length=36)
    outcome: str = Field(min_length=1, max_length=64)
    funding: Literal["cash", "freebet"]
    stake: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    decimal_odds: Decimal = Field(gt=1, max_digits=10, decimal_places=4)
    placed_at: datetime


class BetUpdateRequest(BaseModel):
    """Расчёт или исправление с optimistic revision."""

    expected_revision: int = Field(ge=1)
    outcome: str | None = Field(default=None, min_length=1, max_length=64)
    funding: Literal["cash", "freebet"] | None = None
    stake: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=2)
    decimal_odds: Decimal | None = Field(default=None, gt=1, max_digits=10, decimal_places=4)
    placed_at: datetime | None = None
    status: Literal["open", "settled", "cancelled"] | None = None
    result: Literal["win", "loss", "void"] | None = None
    payout: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    settled_at: datetime | None = None
    cancel_reason: str | None = Field(default=None, max_length=256)


_CARD_FIELDS = frozenset(
    {
        "match_id",
        "tournament",
        "source_namespace",
        "market",
        "market_spec",
        "home_player",
        "away_player",
        "match_datetime",
        "predictions",
        "current_revision_id",
        "model",
        "prediction_ts",
        "status",
        "pinnacle_home_decimal",
        "pinnacle_away_decimal",
        "edge_home",
        "edge_away",
        "bet_decision_home",
        "bet_decision_away",
        "live_odds_status",
        "recommendations",
    }
)


def _validate_card_payload(prediction: dict[str, Any]) -> str:
    """Ограничить сохраняемый payload карточки и числовые значения."""
    if set(prediction) - _CARD_FIELDS:
        raise HTTPException(status_code=422, detail="Неизвестные поля карточки")
    for key in ("home_player", "away_player", "source_namespace", "current_revision_id"):
        value = prediction.get(key)
        if value is not None and (not isinstance(value, str) or len(value) > 256):
            raise HTTPException(status_code=422, detail="Некорректное поле карточки")
    probabilities = prediction["predictions"]
    if not isinstance(probabilities, dict) or len(probabilities) > 16:
        raise HTTPException(status_code=422, detail="Некорректные вероятности")
    if any(
        not isinstance(key, str)
        or len(key) > 64
        or isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not 0 <= value <= 1
        for key, value in probabilities.items()
    ):
        raise HTTPException(status_code=422, detail="Некорректные вероятности")
    for key in ("pinnacle_home_decimal", "pinnacle_away_decimal", "edge_home", "edge_away"):
        value = prediction.get(key)
        if value is None:
            continue
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            raise HTTPException(status_code=422, detail="Некорректная котировка")
        if key.startswith("pinnacle_") and value <= 1:
            raise HTTPException(status_code=422, detail="Некорректная котировка")
    try:
        snapshot = json.dumps(prediction, ensure_ascii=False, sort_keys=True, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="Некорректный контекст карточки") from exc
    if len(snapshot.encode("utf-8")) > 16384:
        raise HTTPException(status_code=422, detail="Карточка слишком большая")
    return snapshot


def _utc_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise HTTPException(status_code=422, detail="Нужно время с часовым поясом")
    return value.astimezone(UTC).replace(tzinfo=None)


def _iso(value: datetime | None) -> str | None:
    return value.replace(tzinfo=UTC).isoformat() if value else None


def _request_hash(body: BaseModel) -> str:
    data = json.dumps(body.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _require_request_id(request_id: str | None) -> str:
    if request_id is None or not 1 <= len(request_id) <= 128:
        raise HTTPException(status_code=400, detail="Требуется Idempotency-Key")
    return request_id


def _bet_dto(bet: RealBet) -> dict[str, Any]:
    expected = (
        expected_payout(
            Decimal(bet.stake),
            Decimal(bet.decimal_odds),
            cast(Literal["cash", "freebet"], bet.funding),
            cast(Literal["win", "loss", "void"], bet.result),
        )
        if bet.result is not None and bet.status == "settled"
        else None
    )
    payout = Decimal(bet.payout) if bet.payout is not None else None
    return {
        "bet_id": bet.bet_id,
        "context_id": bet.context_id,
        "tournament": bet.tournament,
        "source_namespace": bet.source_namespace,
        "match_id": bet.source_event_id,
        "market_spec": bet.market_spec,
        "outcome": bet.outcome,
        "bookmaker": bet.bookmaker,
        "funding": bet.funding,
        "currency": bet.currency,
        "stake": str(bet.stake),
        "decimal_odds": str(bet.decimal_odds),
        "placed_at": _iso(bet.placed_at),
        "status": bet.status,
        "result": bet.result,
        "payout": str(payout) if payout is not None else None,
        "expected_payout": str(expected) if expected is not None else None,
        "payout_difference": str(payout - expected)
        if payout is not None and expected is not None
        else None,
        "settled_at": _iso(bet.settled_at),
        "revision": bet.revision,
    }


def _audit(
    session: Any,
    bet: RealBet,
    *,
    request_id: str,
    request_hash: str,
    operation: str,
    before: dict[str, Any] | None,
    after: dict[str, Any],
    now: datetime,
) -> None:
    session.add(
        RealBetAudit(
            audit_id=str(uuid4()),
            bet_id=bet.bet_id,
            owner_user_id=bet.owner_user_id,
            request_id=request_id,
            request_hash=request_hash,
            operation=operation,
            before_json=json.dumps(before, ensure_ascii=False, sort_keys=True) if before else None,
            after_json=json.dumps(after, ensure_ascii=False, sort_keys=True),
            created_at=now,
        )
    )


@router.post("/bet-contexts", status_code=201)
def create_bet_context(
    body: CardContextRequest,
    owner: Annotated[str, Depends(require_bets_owner)],
) -> dict[str, Any]:
    """Сохранить доверенный снимок публичной карточки до её отправки в Telegram."""
    prediction = body.prediction
    required = ("tournament", "match_id", "market", "market_spec", "predictions")
    if any(not prediction.get(field) for field in required):
        raise HTTPException(status_code=422, detail="Неполный контекст прогноза")
    for key, limit in (("tournament", 64), ("match_id", 128), ("market", 32), ("market_spec", 64)):
        if len(str(prediction[key])) > limit:
            raise HTTPException(status_code=422, detail="Слишком длинный идентификатор")
    revision_id = prediction.get("current_revision_id")
    snapshot_json = _validate_card_payload(prediction)
    now = datetime.now(UTC).replace(tzinfo=None)
    context = BetCardContext(
        context_id=str(uuid4()),
        owner_user_id=owner,
        tournament=str(prediction["tournament"]),
        source_namespace=prediction.get("source_namespace"),
        source_event_id=str(prediction["match_id"]),
        market=str(prediction["market"]),
        market_spec=str(prediction["market_spec"]),
        prediction_revision_id=revision_id,
        quote_observation_id=None,
        snapshot_json=snapshot_json,
        captured_at=now,
    )
    with get_control_session() as session:
        if revision_id is not None:
            revision = session.execute(
                select(
                    PredictionRevision.tournament,
                    PredictionRevision.source_namespace,
                    PredictionRevision.source_event_id,
                    PredictionRevision.market,
                    PredictionRevision.market_spec,
                    PredictionRevision.outcomes_json,
                    PredictionRevision.probabilities_json,
                ).where(PredictionRevision.revision_id == revision_id)
            ).one_or_none()
            if revision is None or (
                revision.tournament,
                revision.source_namespace,
                revision.source_event_id,
                revision.market,
                revision.market_spec,
            ) != (
                context.tournament,
                context.source_namespace,
                context.source_event_id,
                context.market,
                context.market_spec,
            ):
                raise HTTPException(
                    status_code=422, detail="Версия прогноза не соответствует матчу"
                )
            probabilities = json.loads(revision.probabilities_json)
            outcomes = json.loads(revision.outcomes_json)
            if probabilities != prediction["predictions"] or outcomes != sorted(
                prediction["predictions"]
            ):
                raise HTTPException(status_code=422, detail="Вероятности не соответствуют версии")
        session.add(context)
    return {
        "context_id": context.context_id,
        "prediction": prediction,
        "captured_at": _iso(now),
        "prediction_revision_id": revision_id,
        "quote_observation_id": None,
    }


@router.post("/bet-contexts/manual", status_code=201)
def create_manual_bet_context(
    body: ManualContextRequest,
    owner: Annotated[str, Depends(require_bets_owner)],
) -> dict[str, Any]:
    """Подготовить запись из существующего календарного матча без прогноза."""
    with get_session() as session:
        query = select(CanonicalEvent).where(
            CanonicalEvent.tournament == body.tournament,
            CanonicalEvent.source_event_id == body.match_id,
        )
        if body.source_namespace is not None:
            query = query.where(CanonicalEvent.source == body.source_namespace)
        events = session.scalars(query).all()
        if not events:
            raise HTTPException(status_code=404, detail="Матч не найден")
        if len(events) != 1:
            raise HTTPException(status_code=422, detail="Уточните источник матча")
        event = events[0]
        market_rule = MANUAL_MARKETS_BY_SPORT.get(event.sport)
        if market_rule is None:
            raise HTTPException(
                status_code=422, detail="Для вида спорта не задан рынок ручной ставки"
            )
        market_spec, available_outcomes = market_rule
        prediction = {
            "tournament": event.tournament,
            "source_namespace": event.source,
            "match_id": event.source_event_id,
            "market": market_spec,
            "market_spec": market_spec,
            "home_player": event.home_participant,
            "away_player": event.away_participant,
            "match_datetime": _iso(event.scheduled_at),
            "predictions": {},
            "available_outcomes": available_outcomes,
            "current_revision_id": None,
            "live_odds_status": "no_prediction",
        }
    now = datetime.now(UTC).replace(tzinfo=None)
    context = BetCardContext(
        context_id=str(uuid4()),
        owner_user_id=owner,
        tournament=body.tournament,
        source_namespace=prediction["source_namespace"],
        source_event_id=body.match_id,
        market=market_spec,
        market_spec=market_spec,
        prediction_revision_id=None,
        quote_observation_id=None,
        snapshot_json=json.dumps(prediction, ensure_ascii=False, sort_keys=True),
        captured_at=now,
    )
    with get_control_session() as session:
        session.add(context)
    return {
        "context_id": context.context_id,
        "prediction": prediction,
        "captured_at": _iso(now),
        "prediction_revision_id": None,
        "quote_observation_id": None,
    }


@router.get("/bet-contexts/{context_id}")
def get_bet_context(
    context_id: str, owner: Annotated[str, Depends(require_bets_owner)]
) -> dict[str, Any]:
    """Вернуть сохранённую карточку владельцу при нажатии кнопки записи."""
    with get_control_session() as session:
        context = session.get(BetCardContext, context_id)
        if context is None or context.owner_user_id != owner:
            raise HTTPException(status_code=404, detail="Карточка не найдена")
        return {
            "context_id": context.context_id,
            "prediction": json.loads(context.snapshot_json),
            "captured_at": _iso(context.captured_at),
            "prediction_revision_id": context.prediction_revision_id,
            "quote_observation_id": context.quote_observation_id,
        }


@router.post("/bets")
def create_bet(
    body: BetCreateRequest,
    owner: Annotated[str, Depends(require_bets_owner)],
    response: Response,
    request_id: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict[str, Any]:
    """Добавить самостоятельную запись; повторный запрос не создаёт добор."""
    request_id = _require_request_id(request_id)
    request_hash = _request_hash(body)
    stake = money(body.stake)
    if (
        stake <= 0
        or not body.decimal_odds.is_finite()
        or body.decimal_odds <= 1
        or body.decimal_odds != body.decimal_odds.quantize(Decimal("0.0001"))
    ):
        raise HTTPException(status_code=422, detail="Некорректная сумма или коэффициент")
    placed_at = _utc_naive(body.placed_at)
    now = datetime.now(UTC).replace(tzinfo=None)
    with get_control_session() as session:
        existing = session.scalar(select(RealBet).where(RealBet.create_request_id == request_id))
        if existing is not None:
            if existing.owner_user_id != owner or existing.create_request_hash != request_hash:
                raise HTTPException(status_code=409, detail="Ключ запроса уже использован")
            audit = session.scalar(
                select(RealBetAudit).where(RealBetAudit.request_id == request_id)
            )
            if audit is None:
                raise HTTPException(status_code=409, detail="История запроса недоступна")
            return cast(dict[str, Any], json.loads(audit.after_json))
        context = session.get(BetCardContext, body.context_id)
        if context is None or context.owner_user_id != owner:
            raise HTTPException(status_code=404, detail="Карточка не найдена")
        snapshot = json.loads(context.snapshot_json)
        allowed = snapshot.get("available_outcomes") or list(
            (snapshot.get("predictions") or {}).keys()
        )
        if not allowed and context.market_spec == "winner_withOT":
            allowed = ["home_win", "away_win"]
        if allowed and body.outcome not in allowed:
            raise HTTPException(status_code=422, detail="Исход не соответствует рынку")
        bet = RealBet(
            bet_id=str(uuid4()),
            owner_user_id=owner,
            create_request_id=request_id,
            create_request_hash=request_hash,
            context_id=context.context_id,
            tournament=context.tournament,
            source_namespace=context.source_namespace,
            source_event_id=context.source_event_id,
            market_spec=context.market_spec,
            outcome=body.outcome,
            bookmaker="Winline",
            funding=body.funding,
            currency="RUB",
            stake=stake,
            decimal_odds=body.decimal_odds,
            placed_at=placed_at,
            status="open",
            result=None,
            payout=None,
            settled_at=None,
            revision=1,
            created_at=now,
            updated_at=now,
        )
        after = _bet_dto(bet)
        try:
            with session.begin_nested():
                session.add(bet)
                _audit(
                    session,
                    bet,
                    request_id=request_id,
                    request_hash=request_hash,
                    operation="create",
                    before=None,
                    after=after,
                    now=now,
                )
        except IntegrityError as exc:
            existing = session.scalar(
                select(RealBet).where(RealBet.create_request_id == request_id)
            )
            audit = session.scalar(
                select(RealBetAudit).where(RealBetAudit.request_id == request_id)
            )
            if (
                existing is None
                or audit is None
                or existing.owner_user_id != owner
                or existing.create_request_hash != request_hash
            ):
                raise HTTPException(status_code=409, detail="Ключ запроса уже использован") from exc
            return cast(dict[str, Any], json.loads(audit.after_json))
    response.status_code = 201
    return after


@router.get("/bets")
def list_bets(
    owner: Annotated[str, Depends(require_bets_owner)],
    status: Annotated[Literal["open", "settled", "cancelled"] | None, Query()] = None,
) -> dict[str, Any]:
    """Показать только ставки владельца."""
    with get_control_session() as session:
        query = select(RealBet).where(RealBet.owner_user_id == owner)
        if status is not None:
            query = query.where(RealBet.status == status)
        bets = session.scalars(
            query.order_by(RealBet.__table__.c.placed_at.desc(), RealBet.bet_id)
        ).all()
        return {"bets": [_bet_dto(bet) for bet in bets]}


@router.get("/bets/summary")
def get_bet_summary(
    owner: Annotated[str, Depends(require_bets_owner)],
    year: Annotated[int, Query(ge=1, le=9999)],
    month: Annotated[int, Query(ge=1, le=12)],
) -> dict[str, Any]:
    """Посчитать месячный денежный результат по дате расчёта в МСК."""
    with get_control_session() as session:
        bets = session.scalars(
            select(RealBet).where(RealBet.owner_user_id == owner, RealBet.status != "cancelled")
        ).all()
        rows = [
            {
                "status": bet.status,
                "funding": bet.funding,
                "result": bet.result,
                "stake": bet.stake,
                "payout": bet.payout,
                "placed_at": bet.placed_at,
                "settled_at": bet.settled_at,
                "bookmaker": bet.bookmaker,
                "market_spec": bet.market_spec,
                "tournament": bet.tournament,
            }
            for bet in bets
        ]
    return monthly_summary(rows, year, month)


@router.get("/bets/{bet_id}")
def get_bet(bet_id: str, owner: Annotated[str, Depends(require_bets_owner)]) -> dict[str, Any]:
    """Получить одну запись без чужих данных."""
    with get_control_session() as session:
        bet = session.get(RealBet, bet_id)
        if bet is None or bet.owner_user_id != owner:
            raise HTTPException(status_code=404, detail="Ставка не найдена")
        return _bet_dto(bet)


@router.get("/bets/{bet_id}/audit")
def get_bet_audit(
    bet_id: str, owner: Annotated[str, Depends(require_bets_owner)]
) -> dict[str, Any]:
    """Вернуть историю исправлений только владельцу."""
    with get_control_session() as session:
        bet = session.get(RealBet, bet_id)
        if bet is None or bet.owner_user_id != owner:
            raise HTTPException(status_code=404, detail="Ставка не найдена")
        events = session.scalars(
            select(RealBetAudit)
            .where(RealBetAudit.bet_id == bet_id)
            .order_by(RealBetAudit.created_at, RealBetAudit.audit_id)
        ).all()
        return {
            "events": [
                {
                    "operation": event.operation,
                    "before": json.loads(event.before_json) if event.before_json else None,
                    "after": json.loads(event.after_json),
                    "created_at": _iso(event.created_at),
                }
                for event in events
            ]
        }


@router.patch("/bets/{bet_id}")
def update_bet(
    bet_id: str,
    body: BetUpdateRequest,
    owner: Annotated[str, Depends(require_bets_owner)],
    request_id: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict[str, Any]:
    """Рассчитать или исправить ставку с полной историей и revision conflict."""
    request_id = _require_request_id(request_id)
    request_hash = _request_hash(body)
    now = datetime.now(UTC).replace(tzinfo=None)
    with get_control_session() as session:
        audit = session.scalar(select(RealBetAudit).where(RealBetAudit.request_id == request_id))
        if audit is not None:
            if (
                audit.bet_id != bet_id
                or audit.owner_user_id != owner
                or audit.request_hash != request_hash
            ):
                raise HTTPException(status_code=409, detail="Ключ запроса уже использован")
            return cast(dict[str, Any], json.loads(audit.after_json))
        bet = session.scalar(
            select(RealBet)
            .where(RealBet.bet_id == bet_id, RealBet.owner_user_id == owner)
            .with_for_update()
        )
        if bet is None:
            raise HTTPException(status_code=404, detail="Ставка не найдена")
        if bet.revision != body.expected_revision:
            replay = session.scalar(
                select(RealBetAudit).where(RealBetAudit.request_id == request_id)
            )
            if (
                replay is not None
                and replay.bet_id == bet_id
                and replay.owner_user_id == owner
                and replay.request_hash == request_hash
            ):
                return cast(dict[str, Any], json.loads(replay.after_json))
            raise HTTPException(status_code=409, detail="Ставка уже изменена")
        before = _bet_dto(bet)
        changes = body.model_dump(exclude_unset=True)
        changes.pop("expected_revision", None)
        cancel_reason = changes.pop("cancel_reason", None)
        for field in (
            "outcome",
            "funding",
            "stake",
            "decimal_odds",
            "placed_at",
            "status",
            "result",
            "payout",
            "settled_at",
        ):
            if field not in changes:
                continue
            value = changes[field]
            if field in {"placed_at", "settled_at"} and value is not None:
                value = _utc_naive(value)
            if field in {"stake", "payout"} and value is not None:
                value = money(value)
            setattr(bet, field, value)
        if "result" in changes and "status" not in changes:
            bet.status = "settled" if bet.result else "open"
        if bet.status == "cancelled":
            if not cancel_reason or not cancel_reason.strip():
                raise HTTPException(status_code=422, detail="Для отмены нужна причина")
        elif bet.status == "settled":
            if bet.result is None or bet.payout is None or bet.settled_at is None:
                raise HTTPException(status_code=422, detail="Нужны исход, выплата и дата расчёта")
            if bet.settled_at < bet.placed_at:
                raise HTTPException(status_code=422, detail="Расчёт раньше размещения")
        else:
            bet.result = None
            bet.payout = None
            bet.settled_at = None
        if bet.stake <= 0 or bet.decimal_odds <= 1:
            raise HTTPException(status_code=422, detail="Некорректная сумма или коэффициент")
        allowed_outcomes = MARKET_OUTCOMES.get(bet.market_spec)
        if allowed_outcomes is not None and bet.outcome not in allowed_outcomes:
            raise HTTPException(status_code=422, detail="Исход не соответствует рынку")
        bet.revision += 1
        bet.updated_at = now
        after = _bet_dto(bet)
        operation = (
            "cancel"
            if bet.status == "cancelled"
            else "settle"
            if before["status"] == "open" and bet.status == "settled"
            else "correct"
        )
        if cancel_reason:
            after["cancel_reason"] = cancel_reason
        _audit(
            session,
            bet,
            request_id=request_id,
            request_hash=request_hash,
            operation=operation,
            before=before,
            after=after,
            now=now,
        )
    return after
