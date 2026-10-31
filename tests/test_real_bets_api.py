"""Закрытый HTTP-контракт журнала фактических ставок."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from sports_forecast.service import app as app_module
from sports_forecast.service.db.models import Base, CanonicalEvent, PredictionRevision
from sports_forecast.service.routers import real_bets


@pytest.fixture
def client(monkeypatch, tmp_path: Path):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    key_file = tmp_path / "control_api_key"
    key_file.write_text("test-control-secret", encoding="utf-8")
    monkeypatch.setenv("SF_CONTROL_API_KEY_FILE", str(key_file))
    monkeypatch.setenv("SF_CONTROL_ADMIN_IDS", "101,202")
    monkeypatch.setenv("SF_BETS_OWNER_ID", "101")

    @contextmanager
    def control_session():
        with Session(engine, expire_on_commit=False) as session:
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise

    monkeypatch.setattr(real_bets, "get_control_session", control_session)
    monkeypatch.setattr(real_bets, "get_session", control_session)
    with TestClient(app_module.app) as test_client:
        yield test_client, engine
    engine.dispose()


def _headers(owner: str = "101", request_id: str | None = None) -> dict[str, str]:
    headers = {"X-Control-Service-Key": "test-control-secret", "X-Telegram-Admin-Id": owner}
    if request_id:
        headers["Idempotency-Key"] = request_id
    return headers


def _context(client: TestClient) -> str:
    response = client.post(
        "/admin/bet-contexts",
        headers=_headers(),
        json={
            "prediction": {
                "match_id": "2026020084",
                "tournament": "nhl",
                "source_namespace": "nhl",
                "market": "winner_withOT",
                "market_spec": "winner_withOT",
                "home_player": "Washington Capitals",
                "away_player": "Seattle Kraken",
                "match_datetime": "2026-10-11T18:00:00+00:00",
                "predictions": {"home_win": 0.615, "away_win": 0.385},
                "current_revision_id": None,
                "pinnacle_home_decimal": 1.49,
                "pinnacle_away_decimal": 2.78,
            }
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["prediction"]["pinnacle_home_decimal"] == 1.49
    context_id = response.json()["context_id"]
    assert isinstance(context_id, str)
    return context_id


def test_season_start_comes_from_tournament_configuration(client) -> None:
    """NHL использует 1 сентября из конфигурации и закрытый owner API."""
    http, _engine = client
    assert real_bets._season_start("nhl", date(2026, 10, 31)) == date(2026, 9, 1)
    assert real_bets._season_start("nhl", date(2026, 3, 1)) == date(2025, 9, 1)
    response = http.get("/admin/bets/season-summary", headers=_headers())
    assert response.status_code == 200, response.text
    assert response.json()["tournament"] == "nhl"
    assert response.json()["total_cash_pnl"] == "0.00"
    assert response.json()["daily_pnl"] == []
    denied = http.get("/admin/bets/season-summary", headers=_headers("202"))
    assert denied.status_code == 403


def test_bet_topups_settlement_and_monthly_money_rules(client) -> None:
    http, _engine = client
    context_id = _context(http)
    placed = "2026-09-30T21:00:00+00:00"
    body = {
        "context_id": context_id,
        "outcome": "home_win",
        "funding": "cash",
        "stake": "100.00",
        "decimal_odds": "2.20",
        "placed_at": placed,
    }
    first = http.post("/admin/bets", headers=_headers(request_id="create-1"), json=body)
    assert first.status_code == 201, first.text
    same = http.post("/admin/bets", headers=_headers(request_id="create-1"), json=body)
    assert same.status_code == 200
    assert same.json()["bet_id"] == first.json()["bet_id"]
    conflict = http.post(
        "/admin/bets", headers=_headers(request_id="create-1"), json={**body, "stake": "110.00"}
    )
    assert conflict.status_code == 409
    topup = http.post(
        "/admin/bets",
        headers=_headers(request_id="create-2"),
        json={**body, "funding": "freebet", "stake": "50.00", "decimal_odds": "2.30"},
    )
    assert topup.status_code == 201
    assert topup.json()["bet_id"] != first.json()["bet_id"]

    settle_at = "2026-10-01T00:30:00+00:00"
    settled_cash = http.patch(
        f"/admin/bets/{first.json()['bet_id']}",
        headers=_headers(request_id="settle-1"),
        json={"expected_revision": 1, "result": "win", "payout": "220.00", "settled_at": settle_at},
    )
    assert settled_cash.status_code == 200, settled_cash.text
    settled_freebet = http.patch(
        f"/admin/bets/{topup.json()['bet_id']}",
        headers=_headers(request_id="settle-2"),
        json={"expected_revision": 1, "result": "win", "payout": "65.00", "settled_at": settle_at},
    )
    assert settled_freebet.status_code == 200
    summary = http.get("/admin/bets/summary?year=2026&month=10", headers=_headers())
    assert summary.status_code == 200
    assert summary.json()["cash_turnover"] == "100.00"
    assert summary.json()["freebet_nominal"] == "50.00"
    assert summary.json()["total_cash_pnl"] == "185.00"
    assert summary.json()["cash_roi"] == "1.2000"
    assert summary.json()["by_funding"]["freebet"]["freebet_payout"] == "65.00"
    assert summary.json()["by_bookmaker"]["Winline"]["total_cash_pnl"] == "185.00"
    assert (
        http.get("/admin/bets/summary?year=2026&month=9", headers=_headers()).json()[
            "settled_count"
        ]
        == 0
    )
    rows = http.get("/admin/bets", headers=_headers()).json()["bets"]
    assert len(rows) == 2


def test_owner_isolation_audit_and_optimistic_correction(client) -> None:
    http, _engine = client
    context_id = _context(http)
    body = {
        "context_id": context_id,
        "outcome": "away_win",
        "funding": "freebet",
        "stake": "100.00",
        "decimal_odds": "2.50",
        "placed_at": datetime.now(UTC).isoformat(),
    }
    created = http.post("/admin/bets", headers=_headers(request_id=str(uuid4())), json=body)
    assert created.status_code == 201
    bet_id = created.json()["bet_id"]
    assert http.get("/admin/bets", headers=_headers(owner="202")).status_code == 403
    assert http.get(f"/admin/bets/{bet_id}", headers=_headers(owner="202")).status_code == 403
    assert (
        http.post(
            "/admin/bets", headers=_headers(owner="202", request_id="foreign"), json=body
        ).status_code
        == 403
    )
    assert http.get("/admin/bets", headers={"X-Telegram-Admin-Id": "101"}).status_code == 403

    settled = http.patch(
        f"/admin/bets/{bet_id}",
        headers=_headers(request_id="settle-freebet"),
        json={
            "expected_revision": 1,
            "result": "void",
            "payout": "0.00",
            "settled_at": datetime.now(UTC).isoformat(),
        },
    )
    assert settled.status_code == 200
    assert settled.json()["expected_payout"] == "0.00"
    replay = http.patch(
        f"/admin/bets/{bet_id}",
        headers=_headers(request_id="settle-freebet"),
        json={
            "expected_revision": 1,
            "result": "void",
            "payout": "0.00",
            "settled_at": settled.json()["settled_at"],
        },
    )
    assert replay.status_code == 200
    stale = http.patch(
        f"/admin/bets/{bet_id}",
        headers=_headers(request_id="stale"),
        json={
            "expected_revision": 1,
            "result": "win",
            "payout": "150.00",
            "settled_at": datetime.now(UTC).isoformat(),
        },
    )
    assert stale.status_code == 409
    audit = http.get(f"/admin/bets/{bet_id}/audit", headers=_headers()).json()["events"]
    assert [event["operation"] for event in audit] == ["create", "settle"]
    corrected = http.patch(
        f"/admin/bets/{bet_id}",
        headers=_headers(request_id="correct-freebet-payout"),
        json={"expected_revision": 2, "result": "win", "payout": "120.00"},
    )
    assert corrected.status_code == 200
    assert corrected.json()["expected_payout"] == "150.00"
    assert corrected.json()["payout_difference"] == "-30.00"
    audit = http.get(f"/admin/bets/{bet_id}/audit", headers=_headers()).json()["events"]
    assert [event["operation"] for event in audit] == ["create", "settle", "correct"]
    assert audit[-1]["before"]["result"] == "void"
    assert audit[-1]["after"]["result"] == "win"
    cancelled = http.patch(
        f"/admin/bets/{bet_id}",
        headers=_headers(request_id="cancel-error"),
        json={"expected_revision": 3, "status": "cancelled", "cancel_reason": "ошибочная запись"},
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert (
        http.get("/admin/bets/summary?year=2026&month=10", headers=_headers()).json()[
            "settled_count"
        ]
        == 0
    )


def test_context_keeps_revision_and_rejects_changed_probabilities(client) -> None:
    http, engine = client
    revision_id = str(uuid4())
    with Session(engine) as session:
        session.add(
            PredictionRevision(
                revision_id=revision_id,
                run_id="run-1",
                tournament="nhl",
                source_namespace="nhl",
                source_event_id="match-1",
                canonical_event_id=None,
                market="winner_withOT",
                market_spec="winner_withOT",
                outcomes_json='["away_win","home_win"]',
                probabilities_json='{"home_win":0.6,"away_win":0.4}',
                model_pool="nhl",
                bundle_id="bundle-1",
                model_identity="model-1",
                feature_contract_id="features-1",
                calculated_at=datetime.now(UTC),
                input_snapshot_ref=None,
                payload_sha256="a" * 64,
            )
        )
        session.commit()
    payload = {
        "prediction": {
            "match_id": "match-1",
            "tournament": "nhl",
            "source_namespace": "nhl",
            "market": "winner_withOT",
            "market_spec": "winner_withOT",
            "predictions": {"home_win": 0.6, "away_win": 0.4},
            "current_revision_id": revision_id,
            "pinnacle_home_decimal": 1.70,
        }
    }
    saved = http.post("/admin/bet-contexts", headers=_headers(), json=payload)
    assert saved.status_code == 201
    assert saved.json()["prediction_revision_id"] == revision_id
    context_id = saved.json()["context_id"]
    later = http.get(f"/admin/bet-contexts/{context_id}", headers=_headers()).json()
    assert later["prediction"]["pinnacle_home_decimal"] == 1.70
    assert (
        http.get(f"/admin/bet-contexts/{context_id}", headers=_headers(owner="202")).status_code
        == 403
    )
    invalid = http.post(
        "/admin/bet-contexts",
        headers=_headers(),
        json={
            "prediction": {
                **payload["prediction"],
                "predictions": {"home_win": 0.7, "away_win": 0.3},
            }
        },
    )
    assert invalid.status_code == 422


def test_manual_context_uses_calendar_match_without_fabricated_prediction(client) -> None:
    http, engine = client
    with Session(engine) as session:
        session.add(
            CanonicalEvent(
                sport="icehockey",
                tournament="nhl",
                source="nhl_api",
                source_event_id="2026020084",
                scheduled_at=datetime(2026, 10, 11, 18),
                status="scheduled",
                current_revision_sha256="a" * 64,
                home_participant="Washington Capitals",
                away_participant="Seattle Kraken",
            )
        )
        session.commit()
    response = http.post(
        "/admin/bet-contexts/manual",
        headers=_headers(),
        json={"tournament": "nhl", "match_id": "2026020084"},
    )
    assert response.status_code == 201
    assert response.json()["prediction_revision_id"] is None
    assert response.json()["prediction"]["predictions"] == {}
    context_id = response.json()["context_id"]
    bet = http.post(
        "/admin/bets",
        headers=_headers(request_id="manual-bet"),
        json={
            "context_id": context_id,
            "outcome": "away_win",
            "funding": "cash",
            "stake": "100.00",
            "decimal_odds": "2.50",
            "placed_at": "2026-10-11T17:00:00+00:00",
        },
    )
    assert bet.status_code == 201
    assert bet.json()["source_namespace"] == "nhl_api"
    invalid_draw = http.post(
        "/admin/bets",
        headers=_headers(request_id="manual-hockey-draw"),
        json={
            "context_id": context_id,
            "outcome": "draw",
            "funding": "cash",
            "stake": "100.00",
            "decimal_odds": "3.00",
            "placed_at": "2026-10-11T17:00:00+00:00",
        },
    )
    assert invalid_draw.status_code == 422


def test_manual_context_rejects_sport_without_market_rule(client) -> None:
    http, engine = client
    with Session(engine) as session:
        session.add(
            CanonicalEvent(
                sport="unknown_sport",
                tournament="new_league",
                source="source",
                source_event_id="match-1",
                scheduled_at=datetime(2026, 10, 11, 18),
                status="scheduled",
                current_revision_sha256="a" * 64,
                home_participant="Home",
                away_participant="Away",
            )
        )
        session.commit()
    response = http.post(
        "/admin/bet-contexts/manual",
        headers=_headers(),
        json={"tournament": "new_league", "match_id": "match-1"},
    )
    assert response.status_code == 422


def test_manual_context_accepts_football_tournament_and_keeps_draw_outcome(client) -> None:
    http, engine = client
    with Session(engine) as session:
        session.add(
            CanonicalEvent(
                sport="football",
                tournament="epl",
                source="football_api",
                source_event_id="fixture-17",
                scheduled_at=datetime(2026, 10, 12, 18),
                status="scheduled",
                current_revision_sha256="a" * 64,
                home_participant="Arsenal",
                away_participant="Chelsea",
            )
        )
        session.commit()
    context = http.post(
        "/admin/bet-contexts/manual",
        headers=_headers(),
        json={"tournament": "epl", "match_id": "fixture-17"},
    )
    assert context.status_code == 201, context.text
    prediction = context.json()["prediction"]
    assert prediction["market_spec"] == "winner_1x2"
    assert prediction["predictions"] == {}
    assert set(prediction["available_outcomes"]) == {"home_win", "draw", "away_win"}
    bet = http.post(
        "/admin/bets",
        headers=_headers(request_id="football-draw"),
        json={
            "context_id": context.json()["context_id"],
            "outcome": "draw",
            "funding": "cash",
            "stake": "100.00",
            "decimal_odds": "3.20",
            "placed_at": "2026-10-12T17:00:00+00:00",
        },
    )
    assert bet.status_code == 201, bet.text
    assert bet.json()["tournament"] == "epl"
    assert bet.json()["outcome"] == "draw"
    invalid = http.patch(
        f"/admin/bets/{bet.json()['bet_id']}",
        headers=_headers(request_id="football-invalid-outcome"),
        json={"expected_revision": 1, "outcome": "invalid"},
    )
    assert invalid.status_code == 422


def test_monthly_summary_groups_by_tournament(client) -> None:
    http, engine = client
    with Session(engine) as session:
        for sport, tournament, event_id in (
            ("icehockey", "nhl", "hockey-1"),
            ("football", "epl", "football-1"),
        ):
            session.add(
                CanonicalEvent(
                    sport=sport,
                    tournament=tournament,
                    source="test",
                    source_event_id=event_id,
                    scheduled_at=datetime(2026, 10, 12, 18),
                    status="scheduled",
                    current_revision_sha256="a" * 64,
                    home_participant="Home",
                    away_participant="Away",
                )
            )
        session.commit()
    for index, (tournament, event_id) in enumerate((("nhl", "hockey-1"), ("epl", "football-1"))):
        context = http.post(
            "/admin/bet-contexts/manual",
            headers=_headers(),
            json={"tournament": tournament, "match_id": event_id},
        )
        created = http.post(
            "/admin/bets",
            headers=_headers(request_id=f"tournament-create-{index}"),
            json={
                "context_id": context.json()["context_id"],
                "outcome": "home_win",
                "funding": "cash",
                "stake": "100.00",
                "decimal_odds": "2.00",
                "placed_at": "2026-10-12T17:00:00+00:00",
            },
        )
        settled = http.patch(
            f"/admin/bets/{created.json()['bet_id']}",
            headers=_headers(request_id=f"tournament-settle-{index}"),
            json={
                "expected_revision": 1,
                "result": "win" if index == 0 else "loss",
                "payout": "200.00" if index == 0 else "0.00",
                "settled_at": "2026-10-12T20:00:00+00:00",
            },
        )
        assert settled.status_code == 200, settled.text
    summary = http.get("/admin/bets/summary?year=2026&month=10", headers=_headers())
    assert summary.status_code == 200
    by_tournament = summary.json()["by_tournament"]
    assert by_tournament["nhl"]["total_cash_pnl"] == "100.00"
    assert by_tournament["epl"]["total_cash_pnl"] == "-100.00"
    assert summary.json()["total_cash_pnl"] == "0.00"


def test_context_rejects_nonfinite_or_oversized_payload(client) -> None:
    http, _engine = client
    base = {
        "match_id": "m1",
        "tournament": "nhl",
        "market": "winner_withOT",
        "market_spec": "winner_withOT",
        "predictions": {"home_win": 0.6},
    }
    invalid_probability = http.post(
        "/admin/bet-contexts",
        headers=_headers(),
        json={"prediction": {**base, "predictions": {"home_win": 1.5}}},
    )
    assert invalid_probability.status_code == 422
    huge_name = http.post(
        "/admin/bet-contexts",
        headers=_headers(),
        json={"prediction": {**base, "home_player": "A" * 20000}},
    )
    assert huge_name.status_code == 422
