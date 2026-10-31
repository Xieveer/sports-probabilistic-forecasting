"""Контракт автоматического расчёта по canonical результату."""

import json
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from sports_forecast.betting.auto_settlement import resolve_bet_result
from sports_forecast.orchestration.bet_settlement_cli import settle_open_bets
from sports_forecast.service.db.models import (
    Base,
    CanonicalEvent,
    CanonicalEventRevision,
    DataCycleNotificationOutbox,
    DataCycleRun,
    RealBet,
    RealBetAudit,
)


def test_nhl_full_match_winner_including_overtime() -> None:
    """Полный счёт NHL определяет исход двухстороннего рынка."""
    assert resolve_bet_result(
        sport="ice_hockey",
        market_spec="winner_withOT",
        outcome="home_win",
        status="finished",
        result={"home_score_ft": "4", "away_score_ft": "3"},
    ) == ("win", None)
    assert resolve_bet_result(
        sport="ice_hockey",
        market_spec="winner_withOT",
        outcome="away_win",
        status="finished",
        result={"home_score_ft": "4", "away_score_ft": "3"},
    ) == ("loss", None)


def test_ambiguous_or_incomplete_match_stays_open() -> None:
    """Ничья, отсутствие счёта, отмена и чужой рынок не дают выплату."""
    cases = [
        ("finished", {"home_score_ft": "2", "away_score_ft": "2"}, "winner_withOT"),
        ("finished", {"home_score_ft": None, "away_score_ft": "2"}, "winner_withOT"),
        ("cancelled", {"home_score_ft": "2", "away_score_ft": "1"}, "winner_withOT"),
        ("finished", {"home_score_ft": "2", "away_score_ft": "1"}, "total_5.5"),
    ]
    for status, result, market in cases:
        outcome, reason = resolve_bet_result(
            sport="ice_hockey",
            market_spec=market,
            outcome="home_win",
            status=status,
            result=result,
        )
        assert outcome is None
        assert reason


def test_settlement_is_atomic_audited_and_idempotent() -> None:
    """Повторный вызов не платит второй раз и сохраняет отдельную сводку."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    now = datetime(2026, 10, 31, 11, tzinfo=UTC)
    with Session(engine) as session:
        session.add(
            DataCycleRun(
                run_id="run-1",
                tournament="nhl",
                reason="scheduled",
                status="running",
                executor_generation=1,
                executor_owner_id="owner-1",
            )
        )
        event = CanonicalEvent(
            sport="ice_hockey",
            tournament="nhl",
            source="nhl_web_api",
            source_event_id="game-1",
            scheduled_at=datetime(2026, 10, 30, 18),
            status="finished",
            current_revision_sha256="revision-1",
        )
        session.add(event)
        session.flush()
        session.add(
            CanonicalEventRevision(
                canonical_event_id=event.id,
                revision_sha256="revision-1",
                payload_json="{}",
                result_json=json.dumps({"home_score_ft": "4", "away_score_ft": "3"}),
                source_observed_at=now.replace(tzinfo=None),
            )
        )
        session.add(
            RealBet(
                bet_id="bet-1",
                owner_user_id="101",
                create_request_id="create-1",
                create_request_hash="x",
                tournament="nhl",
                source_namespace="nhl_web_api",
                source_event_id="game-1",
                market_spec="winner_withOT",
                outcome="home_win",
                bookmaker="winline",
                funding="cash",
                currency="RUB",
                stake=Decimal("100.00"),
                decimal_odds=Decimal("2.20"),
                placed_at=datetime(2026, 10, 30, 16),
                status="open",
                revision=1,
                created_at=now.replace(tzinfo=None),
                updated_at=now.replace(tzinfo=None),
            )
        )
        session.commit()
        first = settle_open_bets(
            session,
            run_id="run-1",
            tournament="nhl",
            owner_id="101",
            generation=1,
            executor_id="owner-1",
            at=now,
        )
        session.commit()
        again = settle_open_bets(
            session,
            run_id="run-1",
            tournament="nhl",
            owner_id="101",
            generation=1,
            executor_id="owner-1",
            at=now,
        )
        session.commit()
        bet = session.get(RealBet, "bet-1")
        assert bet is not None
        assert bet.status == "settled" and bet.payout == Decimal("220.00")
        assert first == again
        assert first["total_cash_pnl"] == "120.00"
        audits = session.scalars(select(RealBetAudit)).all()
        assert len(audits) == 1
        provenance = json.loads(audits[0].after_json)
        assert provenance["source_revision_sha256"] == "revision-1"
        assert provenance["score"] == {"home_score_ft": "4", "away_score_ft": "3"}
        notes = session.scalars(select(DataCycleNotificationOutbox)).all()
        assert len(notes) == 1 and notes[0].kind == "bet_summary"
        assert notes[0].available_at > now.replace(tzinfo=None)
    engine.dispose()
