"""Денежные правила фактических ставок из REQ-031."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from sports_forecast.betting.real_bets import expected_payout, monthly_summary


@pytest.mark.parametrize(
    ("funding", "result", "expected"),
    [
        ("cash", "win", "250.00"),
        ("cash", "loss", "0.00"),
        ("cash", "void", "100.00"),
        ("freebet", "win", "150.00"),
        ("freebet", "loss", "0.00"),
        ("freebet", "void", "0.00"),
    ],
)
def test_expected_payout_respects_freebet_nominal(funding, result, expected) -> None:
    assert expected_payout(Decimal("100.00"), Decimal("2.50"), funding, result) == Decimal(expected)


def test_monthly_summary_uses_settlement_date_and_separate_roi() -> None:
    rows = [
        {
            "status": "settled",
            "funding": "cash",
            "result": "win",
            "stake": "100.00",
            "payout": "220.00",
            "settled_at": datetime(2026, 10, 1, tzinfo=UTC),
            "bookmaker": "Winline",
            "market_spec": "winner_withOT",
            "tournament": "nhl",
        },
        {
            "status": "settled",
            "funding": "freebet",
            "result": "win",
            "stake": "50.00",
            "payout": "65.00",
            "settled_at": datetime(2026, 10, 2, tzinfo=UTC),
            "bookmaker": "Winline",
            "market_spec": "winner_withOT",
            "tournament": "nhl",
        },
        {
            "status": "open",
            "funding": "cash",
            "result": None,
            "stake": "1000.00",
            "payout": None,
            "placed_at": datetime(2026, 10, 2, tzinfo=UTC),
            "settled_at": None,
            "bookmaker": "Winline",
            "market_spec": "winner_withOT",
            "tournament": "nhl",
        },
    ]
    summary = monthly_summary(rows, 2026, 10)
    assert summary["cash_turnover"] == "100.00"
    assert summary["cash_pnl"] == "120.00"
    assert summary["freebet_nominal"] == "50.00"
    assert summary["freebet_payout"] == "65.00"
    assert summary["total_cash_pnl"] == "185.00"
    assert summary["cash_roi"] == "1.2000"
    assert summary["open_count"] == 1


def test_monthly_summary_uses_moscow_calendar_boundary() -> None:
    """23:30 UTC в последний день сентября относится к октябрю МСК."""
    row = {
        "status": "settled",
        "funding": "cash",
        "result": "loss",
        "stake": "100.00",
        "payout": "0.00",
        "settled_at": datetime(2026, 9, 30, 23, 30, tzinfo=UTC),
        "bookmaker": "Winline",
        "market_spec": "winner_withOT",
        "tournament": "nhl",
    }
    assert monthly_summary([row], 2026, 9)["settled_count"] == 0
    assert monthly_summary([row], 2026, 10)["cash_pnl"] == "-100.00"
