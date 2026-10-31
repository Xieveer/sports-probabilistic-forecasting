"""Расчёт открытых фактических ставок в пределах одного Data Cycle."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import cast
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from sports_forecast.betting.auto_settlement import resolve_bet_result
from sports_forecast.betting.real_bets import expected_payout
from sports_forecast.service.db.engine import get_session
from sports_forecast.service.db.models import (
    CanonicalEvent,
    CanonicalEventRevision,
    DataCycleNotificationOutbox,
    DataCycleRun,
    RealBet,
    RealBetAudit,
)
from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)


def settle_open_bets(
    session: Session,
    *,
    run_id: str,
    tournament: str,
    owner_id: str,
    generation: int,
    executor_id: str,
    at: datetime,
) -> dict[str, object]:
    """В одной транзакции рассчитать ставки и подготовить сводку владельцу."""
    now = at.astimezone(UTC).replace(tzinfo=None)
    run = session.scalar(
        select(DataCycleRun).where(DataCycleRun.run_id == run_id).with_for_update()
    )
    if (
        run is None
        or run.tournament != tournament
        or run.status != "running"
        or run.executor_generation != generation
        or run.executor_owner_id != executor_id
        or run.executor_stalled_at is not None
    ):
        raise RuntimeError("Data Cycle executor generation fenced")
    existing = session.scalar(
        select(DataCycleNotificationOutbox).where(
            DataCycleNotificationOutbox.run_id == run_id,
            DataCycleNotificationOutbox.destination_alias == "bets_owner",
            DataCycleNotificationOutbox.kind == "bet_summary",
        )
    )
    if existing is not None:
        return cast(dict[str, object], json.loads(existing.payload_json or "{}"))
    bets = list(
        session.scalars(
            select(RealBet)
            .where(
                RealBet.owner_user_id == owner_id,
                RealBet.tournament == tournament,
                RealBet.status == "open",
                RealBet.placed_at <= now,
            )
            .order_by(RealBet.placed_at, RealBet.bet_id)
            .with_for_update()
        )
    )
    settled: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    total_pnl = Decimal("0.00")
    for bet in bets:
        corrected = session.scalar(
            select(RealBetAudit.audit_id)
            .where(RealBetAudit.bet_id == bet.bet_id, RealBetAudit.operation == "correct")
            .limit(1)
        )
        if corrected is not None:
            skipped.append({"bet_id": bet.bet_id, "reason": "Ставка исправлена вручную"})
            continue
        query = select(CanonicalEvent).where(
            CanonicalEvent.tournament == tournament,
            CanonicalEvent.source_event_id == bet.source_event_id,
        )
        if bet.source_namespace:
            query = query.where(CanonicalEvent.source == bet.source_namespace)
        events = list(session.scalars(query.limit(2)))
        if len(events) != 1:
            skipped.append({"bet_id": bet.bet_id, "reason": "Не найден единственный матч"})
            continue
        event = events[0]
        if event.scheduled_at > now:
            continue
        revision = session.scalar(
            select(CanonicalEventRevision).where(
                CanonicalEventRevision.canonical_event_id == event.id,
                CanonicalEventRevision.revision_sha256 == event.current_revision_sha256,
            )
        )
        if revision is None:
            skipped.append({"bet_id": bet.bet_id, "reason": "Нет текущего результата матча"})
            continue
        try:
            result_json = json.loads(revision.result_json)
        except (TypeError, ValueError):
            result_json = {}
        if not isinstance(result_json, dict):
            result_json = {}
        if tournament != "nhl" or event.source != "nhl_web_api":
            result, reason = None, "Источник результата не поддерживается"
        else:
            result, reason = resolve_bet_result(
                sport=event.sport,
                market_spec=bet.market_spec,
                outcome=bet.outcome,
                status=event.status,
                result=result_json,
            )
        if result is None:
            if event.status in {"finished", "cancelled", "postponed", "needs_review"}:
                skipped.append(
                    {"bet_id": bet.bet_id, "reason": reason or "Неоднозначный результат"}
                )
            continue
        before = {"status": bet.status, "revision": bet.revision}
        payout = expected_payout(bet.stake, bet.decimal_odds, bet.funding, result)
        bet.status = "settled"
        bet.result = result
        bet.payout = payout
        bet.settled_at = now
        bet.updated_at = now
        bet.revision += 1
        after = {
            "status": bet.status,
            "result": bet.result,
            "payout": str(payout),
            "settled_at": now.isoformat() + "+00:00",
            "revision": bet.revision,
            "source_event_id": event.source_event_id,
            "source_revision_sha256": revision.revision_sha256,
            "score": {
                "home_score_ft": result_json.get("home_score_ft"),
                "away_score_ft": result_json.get("away_score_ft"),
            },
        }
        request_id = f"auto:{run_id}:{bet.bet_id}"
        session.add(
            RealBetAudit(
                audit_id=str(uuid4()),
                bet_id=bet.bet_id,
                owner_user_id=owner_id,
                request_id=request_id,
                request_hash=hashlib.sha256(request_id.encode()).hexdigest(),
                operation="settle",
                before_json=json.dumps(before),
                after_json=json.dumps(after),
                created_at=now,
            )
        )
        pnl = payout - bet.stake if bet.funding == "cash" else payout
        total_pnl += pnl
        settled.append({"bet_id": bet.bet_id, "result": result, "pnl": str(pnl)})
    summary: dict[str, object] = {
        "settled_count": len(settled),
        "skipped_count": len(skipped),
        "total_cash_pnl": str(total_pnl),
        "settled": settled[:10],
        "skipped": skipped[:10],
    }
    if settled or skipped:
        session.add(
            DataCycleNotificationOutbox(
                run_id=run_id,
                destination_alias="bets_owner",
                kind="bet_summary",
                payload_json=json.dumps(summary, ensure_ascii=False, sort_keys=True),
                status="pending",
                attempts=0,
                available_at=now + timedelta(days=3650),
                created_at=now,
            )
        )
    session.flush()
    return summary


def main(argv: list[str] | None = None) -> int:
    """Запустить расчёт после canonical import под владельцем текущего run."""
    parser = argparse.ArgumentParser(description="Settle open real bets")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--tournament", required=True)
    args = parser.parse_args(argv)
    owner_id = os.environ.get("SF_BETS_OWNER_ID", "").strip()
    if not owner_id.isdigit():
        logger.error("Владелец журнала ставок не настроен")
        return 1
    try:
        generation = int(os.environ["SF_DATA_CYCLE_GENERATION"])
        executor_id = os.environ["SF_DATA_CYCLE_OWNER_ID"]
        with get_session() as session:
            summary = settle_open_bets(
                session,
                run_id=args.run_id,
                tournament=args.tournament,
                owner_id=owner_id,
                generation=generation,
                executor_id=executor_id,
                at=datetime.now(UTC),
            )
        logger.info(
            "Расчёт ставок: %s рассчитано, %s требуют проверки",
            summary["settled_count"],
            summary["skipped_count"],
        )
        return 0
    except Exception:
        logger.error("Не удалось рассчитать открытые ставки")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
