"""Денежные правила ручного журнала фактических ставок."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Literal
from zoneinfo import ZoneInfo


Funding = Literal["cash", "freebet"]
Result = Literal["win", "loss", "void"]
MANUAL_MARKETS_BY_SPORT: dict[str, tuple[str, tuple[str, ...]]] = {
    "icehockey": ("winner_withOT", ("home_win", "away_win")),
    "football": ("winner_1x2", ("home_win", "draw", "away_win")),
    "table_tennis": ("winner", ("home_win", "away_win")),
}
MARKET_OUTCOMES: dict[str, tuple[str, ...]] = dict(MANUAL_MARKETS_BY_SPORT.values())
_CENT = Decimal("0.01")
_MOSCOW = ZoneInfo("Europe/Moscow")


def money(value: Decimal | str | int) -> Decimal:
    """Проверить неотрицательную сумму в рублях с точностью до копейки."""
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Некорректная сумма") from exc
    if not amount.is_finite() or amount < 0 or amount != amount.quantize(_CENT):
        raise ValueError("Сумма должна быть неотрицательной и с точностью до копейки")
    return amount


def expected_payout(stake: Decimal, odds: Decimal, funding: Funding, result: Result) -> Decimal:
    """Вычислить ожидаемую денежную выплату; номинал фрибета не возвращается."""
    if stake <= 0 or odds <= 1 or not stake.is_finite() or not odds.is_finite():
        raise ValueError("Сумма и коэффициент должны быть положительными")
    if result == "loss" or (funding == "freebet" and result == "void"):
        return Decimal("0.00")
    if result == "void":
        return stake.quantize(_CENT)
    factor = odds if funding == "cash" else odds - 1
    return (stake * factor).quantize(_CENT, rounding=ROUND_HALF_UP)


def _summary_bucket() -> dict[str, Any]:
    return {
        "settled_count": 0,
        "win_count": 0,
        "loss_count": 0,
        "void_count": 0,
        "cash_turnover": Decimal("0.00"),
        "cash_payout": Decimal("0.00"),
        "cash_pnl": Decimal("0.00"),
        "freebet_nominal": Decimal("0.00"),
        "freebet_payout": Decimal("0.00"),
        "total_cash_pnl": Decimal("0.00"),
    }


def _add_row(bucket: dict[str, Any], row: Mapping[str, Any]) -> None:
    stake = money(str(row["stake"]))
    payout = money(str(row["payout"]))
    funding = str(row["funding"])
    result = str(row["result"])
    bucket["settled_count"] += 1
    bucket[f"{result}_count"] += 1
    if funding == "cash":
        bucket["cash_turnover"] += stake
        bucket["cash_payout"] += payout
        bucket["cash_pnl"] += payout - stake
        bucket["total_cash_pnl"] += payout - stake
    else:
        bucket["freebet_nominal"] += stake
        bucket["freebet_payout"] += payout
        bucket["total_cash_pnl"] += payout


def _serialize_bucket(bucket: dict[str, Any]) -> dict[str, Any]:
    cash_turnover = bucket["cash_turnover"]
    bucket["cash_roi"] = (
        str((bucket["cash_pnl"] / cash_turnover).quantize(Decimal("0.0001")))
        if cash_turnover
        else None
    )
    outcomes = bucket["win_count"] + bucket["loss_count"]
    bucket["hit_rate"] = (
        str((Decimal(bucket["win_count"]) / Decimal(outcomes)).quantize(Decimal("0.0001")))
        if outcomes
        else None
    )
    return {
        key: str(value) if isinstance(value, Decimal) else value for key, value in bucket.items()
    }


def monthly_summary(rows: Iterable[Mapping[str, Any]], year: int, month: int) -> dict[str, Any]:
    """Свести рассчитанные записи по дате расчёта МСК без смешения ROI и фрибетов."""
    if year < 1 or not 1 <= month <= 12:
        raise ValueError("Некорректный месяц")
    total = _summary_bucket()
    by_bookmaker: dict[str, dict[str, Any]] = {}
    by_market: dict[str, dict[str, Any]] = {}
    by_funding: dict[str, dict[str, Any]] = {}
    by_tournament: dict[str, dict[str, Any]] = {}
    open_count = 0
    for row in rows:
        if row.get("status") == "open":
            placed_at = row.get("placed_at")
            if isinstance(placed_at, datetime):
                placed = placed_at.replace(tzinfo=UTC) if placed_at.tzinfo is None else placed_at
                placed = placed.astimezone(_MOSCOW)
                if (placed.year, placed.month) == (year, month):
                    open_count += 1
            continue
        if row.get("status") != "settled":
            continue
        settled_at = row.get("settled_at")
        if not isinstance(settled_at, datetime):
            continue
        moment = settled_at.replace(tzinfo=UTC) if settled_at.tzinfo is None else settled_at
        moment = moment.astimezone(_MOSCOW)
        if (moment.year, moment.month) != (year, month):
            continue
        _add_row(total, row)
        for grouping, field in (
            (by_bookmaker, "bookmaker"),
            (by_market, "market_spec"),
            (by_funding, "funding"),
            (by_tournament, "tournament"),
        ):
            key = str(row[field])
            _add_row(grouping.setdefault(key, _summary_bucket()), row)
    return {
        "year": year,
        "month": month,
        "open_count": open_count,
        **_serialize_bucket(total),
        "by_bookmaker": {key: _serialize_bucket(bucket) for key, bucket in by_bookmaker.items()},
        "by_market": {key: _serialize_bucket(bucket) for key, bucket in by_market.items()},
        "by_funding": {key: _serialize_bucket(bucket) for key, bucket in by_funding.items()},
        "by_tournament": {key: _serialize_bucket(bucket) for key, bucket in by_tournament.items()},
    }


def season_summary(
    rows: Iterable[Mapping[str, Any]], *, tournament: str, start: str, end: str
) -> dict[str, Any]:
    """Свести фактические ставки турнира и накопленный денежный PnL по дням МСК."""
    start_date = date.fromisoformat(start)
    end_date = date.fromisoformat(end)
    if start_date > end_date or not tournament:
        raise ValueError("Некорректный период сезона")
    total = _summary_bucket()
    by_bookmaker: dict[str, dict[str, Any]] = {}
    by_market: dict[str, dict[str, Any]] = {}
    by_funding: dict[str, dict[str, Any]] = {}
    daily: dict[date, Decimal] = {}
    open_count = 0
    for row in rows:
        if row.get("tournament") != tournament:
            continue
        if row.get("status") == "open":
            placed_at = row.get("placed_at")
            if isinstance(placed_at, datetime):
                placed = placed_at.replace(tzinfo=UTC) if placed_at.tzinfo is None else placed_at
                if start_date <= placed.astimezone(_MOSCOW).date() <= end_date:
                    open_count += 1
            continue
        if row.get("status") != "settled":
            continue
        settled_at = row.get("settled_at")
        if not isinstance(settled_at, datetime):
            continue
        moment = settled_at.replace(tzinfo=UTC) if settled_at.tzinfo is None else settled_at
        day = moment.astimezone(_MOSCOW).date()
        if not start_date <= day <= end_date:
            continue
        previous = total["total_cash_pnl"]
        _add_row(total, row)
        daily[day] = daily.get(day, Decimal("0.00")) + total["total_cash_pnl"] - previous
        for grouping, field in (
            (by_bookmaker, "bookmaker"),
            (by_market, "market_spec"),
            (by_funding, "funding"),
        ):
            key = str(row[field])
            _add_row(grouping.setdefault(key, _summary_bucket()), row)
    cumulative = Decimal("0.00")
    points: list[dict[str, str]] = []
    for day, pnl in sorted(daily.items()):
        cumulative += pnl
        points.append({"date": day.isoformat(), "cumulative_cash_pnl": str(cumulative)})
    return {
        "tournament": tournament,
        "start": start,
        "end": end,
        "open_count": open_count,
        **_serialize_bucket(total),
        "by_bookmaker": {key: _serialize_bucket(bucket) for key, bucket in by_bookmaker.items()},
        "by_market": {key: _serialize_bucket(bucket) for key, bucket in by_market.items()},
        "by_funding": {key: _serialize_bucket(bucket) for key, bucket in by_funding.items()},
        "by_tournament": {tournament: _serialize_bucket(total)},
        "daily_pnl": points,
    }
