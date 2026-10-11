"""
Live Pinnacle (The Odds API) для ответов публичного prediction API (R37.5).

Один батч-запрос на список предсказаний NHL moneyline (``winner`` / ``winner_withOT``);
тяжёлые фичи не считаются — только лёгкий HTTP + сопоставление из
:mod:`sports_forecast.data.providers.odds.live_nhl_pinnacle`.

При ``live_pinnacle=false`` или отсутствии ``ODDS_API_KEY`` поля остаются пустыми,
``live_odds_status`` фиксирует причину (см. OpenAPI у ``/predict/*``).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Any

import requests
from omegaconf import OmegaConf
from sqlalchemy import select

from sports_forecast.betting.live_moneyline_extras import (
    build_live_moneyline_extras,
    nhl_live_match_ref_from_prediction,
    proba_home_from_prediction,
)
from sports_forecast.config.loaders import load_bookmaker_config
from sports_forecast.data.providers.odds.client import QuotaBudgetError, has_configured_odds_api_key
from sports_forecast.data.providers.odds.live_nhl_pinnacle import (
    PinnacleH2HQuote,
    build_odds_client_for_live,
    fetch_nhl_pinnacle_quotes_for_refs,
)
from sports_forecast.data.providers.odds.team_name_registry import (
    TeamNameRegistry,
    load_nhl_team_name_registry,
)
from sports_forecast.identity.derived_event_matching import DerivedEventCandidate
from sports_forecast.identity.events import registry_event_reader_enabled
from sports_forecast.identity.installation import pin_installed_registry
from sports_forecast.service.db.engine import get_session
from sports_forecast.service.db.models import CanonicalEvent, Prediction
from sports_forecast.service.service_api_settings import load_edge_decision_params
from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)


def _is_nhl_tournament(tournament: str) -> bool:
    t = str(tournament).strip().lower()
    return t == "nhl" or t == "nhl_train" or t.startswith("nhl_")


def _is_moneyline_market(market: str) -> bool:
    return str(market).strip() in ("winner", "winner_withOT")


def _is_nhl_moneyline(pred: Prediction) -> bool:
    return _is_nhl_tournament(pred.tournament) and _is_moneyline_market(pred.market)


def _registry() -> TeamNameRegistry:
    return load_nhl_team_name_registry(strict_mode=registry_event_reader_enabled())


def pinned_live_quote_matching(
    predictions: Sequence[Prediction], *, sport_key: str, source: str = "the_odds_api"
) -> tuple[
    dict[str, DerivedEventCandidate],
    Callable[[dict[str, Any]], DerivedEventCandidate],
    Callable[[dict[str, Any], str], str | None],
    list[DerivedEventCandidate],
]:
    """Разрешить обозначения обеих сторон через один закреплённый snapshot."""
    with get_session() as session:
        reader = pin_installed_registry(session)
        scheduled_events = session.scalars(
            select(CanonicalEvent).where(
                CanonicalEvent.__table__.c.tournament == "nhl",
                CanonicalEvent.__table__.c.status == "scheduled",
            )
        ).all()
        requested_ids = {str(prediction.match_id) for prediction in predictions}
        requested_events: dict[str, list[CanonicalEvent]] = {}
        for event in scheduled_events:
            source_event_id = str(event.source_event_id)
            if source_event_id in requested_ids:
                requested_events.setdefault(source_event_id, []).append(event)

        all_candidates: list[DerivedEventCandidate] = []
        candidate_by_event_id: dict[int, DerivedEventCandidate] = {}
        source_sports = {str(event.sport) for event in scheduled_events}
        for event in scheduled_events:
            key = str(int(event.id))
            source_sports.add(str(event.sport))
            at = event.scheduled_at
            if at is not None and at.tzinfo is None:
                at = at.replace(tzinfo=UTC)
            at_text = at.isoformat() if at is not None else None
            tournament = reader.resolve_designation(
                source=str(event.source),
                kind="tournament",
                scope={"sport": str(event.sport)},
                value_kind="name",
                raw_value=str(event.tournament),
                at=at_text,
            )
            team_scope = {"sport": str(event.sport), "tournament": tournament.entity_id or ""}
            home = reader.resolve_designation(
                source=str(event.source),
                kind="team",
                scope=team_scope,
                value_kind="name",
                raw_value=str(event.home_participant or ""),
                at=at_text,
            )
            away = reader.resolve_designation(
                source=str(event.source),
                kind="team",
                scope=team_scope,
                value_kind="name",
                raw_value=str(event.away_participant or ""),
                at=at_text,
            )
            reason = None
            if tournament.status != "resolved":
                reason = "unconfirmed_calendar_tournament"
            elif home.status != "resolved" or away.status != "resolved":
                reason = "unconfirmed_calendar_team"
            candidate = DerivedEventCandidate(
                key=key,
                tournament_id=tournament.entity_id,
                home_team_id=home.entity_id,
                away_team_id=away.entity_id,
                scheduled_at=at,
                unresolved_reason=reason,
            )
            all_candidates.append(candidate)
            candidate_by_event_id[int(event.id)] = candidate
        calendar_candidates = {
            match_id: candidate_by_event_id[int(events[0].id)]
            for match_id, events in requested_events.items()
            if len(events) == 1 and int(events[0].id) in candidate_by_event_id
        }

    def resolve_provider_identity(item: dict[str, Any]) -> DerivedEventCandidate:
        raw_time = str(item.get("commence_time") or "").strip()
        if raw_time.endswith("Z"):
            raw_time = raw_time[:-1] + "+00:00"
        try:
            event_time = datetime.fromisoformat(raw_time).astimezone(UTC) if raw_time else None
        except ValueError:
            event_time = None
        sport = next(iter(source_sports)) if len(source_sports) == 1 else ""
        at_text = event_time.isoformat() if event_time is not None else None
        tournament = reader.resolve_designation(
            source=source,
            kind="tournament",
            scope={"sport": sport},
            value_kind="external_id",
            raw_value=sport_key,
            at=at_text,
        )
        scope = {"sport": sport, "tournament": tournament.entity_id or ""}
        home = reader.resolve_designation(
            source=source,
            kind="team",
            scope=scope,
            value_kind="name",
            raw_value=str(item.get("home_team") or ""),
            at=at_text,
        )
        away = reader.resolve_designation(
            source=source,
            kind="team",
            scope=scope,
            value_kind="name",
            raw_value=str(item.get("away_team") or ""),
            at=at_text,
        )
        reason = None
        if len(source_sports) != 1 or tournament.status != "resolved":
            reason = "unconfirmed_provider_tournament"
        elif home.status != "resolved" or away.status != "resolved":
            reason = "unconfirmed_provider_team"
        else:
            books = [
                book
                for book in item.get("bookmakers", [])
                if isinstance(book, dict) and book.get("key") == "pinnacle"
            ]
            markets = [
                market
                for market in (books[0].get("markets", []) if len(books) == 1 else [])
                if isinstance(market, dict) and market.get("key") == "h2h"
            ]
            market_resolution = reader.resolve_market(
                source=source,
                sport=sport,
                tournament_id=tournament.entity_id or "",
                bookmaker="pinnacle",
                raw_market_key="h2h",
                at=at_text,
            )
            market_ok = (
                market_resolution.status == "resolved"
                and market_resolution.entity_id is not None
                and len(markets) == 1
            )
            if market_ok:
                try:
                    rule = reader.get_market_rule(market_resolution.entity_id)
                    market_entity = reader.get_entity(market_resolution.entity_id)
                except (KeyError, TypeError):
                    market_ok = False
                else:
                    market_ok = (
                        market_entity.project_name == "winner_withOT"
                        and rule.period == "game"
                        and rule.overtime
                        and rule.shootout
                        and not rule.draw
                        and set(rule.valid_outcome_keys) == {"home_win", "away_win"}
                    )
            if market_ok:
                outcome_ids = set()
                outcomes = markets[0].get("outcomes", [])
                if isinstance(outcomes, list) and len(outcomes) == 2:
                    for outcome in outcomes:
                        if not isinstance(outcome, dict):
                            continue
                        designation = reader.resolve_designation(
                            source=source,
                            kind="team",
                            scope=scope,
                            value_kind="name",
                            raw_value=str(outcome.get("name") or ""),
                            at=at_text,
                        )
                        if designation.status == "resolved" and designation.entity_id:
                            outcome_ids.add(designation.entity_id)
                market_ok = outcome_ids == {home.entity_id, away.entity_id}
            if not market_ok:
                reason = "unconfirmed_market_or_outcome_rule"
        return DerivedEventCandidate(
            key=str(item.get("id") or ""),
            tournament_id=tournament.entity_id,
            home_team_id=home.entity_id,
            away_team_id=away.entity_id,
            scheduled_at=event_time,
            unresolved_reason=reason,
        )

    def resolve_provider_outcome_team(item: dict[str, Any], raw_name: str) -> str | None:
        candidate = resolve_provider_identity(item)
        event_time = candidate.scheduled_at
        if (
            candidate.unresolved_reason is not None
            or candidate.tournament_id is None
            or event_time is None
            or len(source_sports) != 1
        ):
            return None
        resolution = reader.resolve_designation(
            source=source,
            kind="team",
            scope={"sport": next(iter(source_sports)), "tournament": candidate.tournament_id},
            value_kind="name",
            raw_value=raw_name,
            at=event_time.isoformat(),
        )
        return resolution.entity_id if resolution.status == "resolved" else None

    return (
        calendar_candidates,
        resolve_provider_identity,
        resolve_provider_outcome_team,
        all_candidates,
    )


def _fetch_quotes_map(preds: list[Prediction]) -> dict[str, PinnacleH2HQuote | None]:
    by_mid: dict[str, Prediction] = {}
    for p in preds:
        mid = str(p.match_id)
        if mid not in by_mid:
            by_mid[mid] = p
    refs = [nhl_live_match_ref_from_prediction(by_mid[mid]) for mid in sorted(by_mid)]
    book_cfg = load_bookmaker_config("the_odds_api")
    if book_cfg is None:
        raise RuntimeError("the_odds_api bookmaker config missing")
    client = build_odds_client_for_live(book_cfg)
    if not registry_event_reader_enabled():
        return fetch_nhl_pinnacle_quotes_for_refs(
            refs, book_cfg=book_cfg, team_registry=_registry(), client=client
        )

    sport_key = str(OmegaConf.select(book_cfg, "bookmaker.sport_keys.nhl") or "icehockey_nhl")
    (
        calendar_candidates,
        resolve_provider_identity,
        resolve_provider_outcome_team,
        calendar_window_candidates,
    ) = pinned_live_quote_matching(list(by_mid.values()), sport_key=sport_key)

    return fetch_nhl_pinnacle_quotes_for_refs(
        refs,
        book_cfg=book_cfg,
        team_registry=_registry(),
        client=client,
        calendar_identity_by_match=calendar_candidates,
        calendar_window_candidates=calendar_window_candidates,
        provider_event_identity_resolver=resolve_provider_identity,
        provider_outcome_team_resolver=resolve_provider_outcome_team,
    )


def batch_live_response_extras(
    preds: list[Prediction],
    *,
    live_pinnacle: bool = True,
) -> dict[int, dict[str, Any]]:
    """Построить kwargs для опциональных полей :class:`~sports_forecast.service.schemas.PredictionResponse`.

    Args:
        preds: Строки витрины (ожидается загруженный PK ``id``).
        live_pinnacle: ``False`` — не вызывать The Odds API (статус ``disabled``).

    Returns:
        ``pred.id`` → словарь полей ``pinnacle_*``, ``edge_home`` / ``edge_away``,
        ``bet_decision_home`` / ``bet_decision_away``, ``live_odds_status``.
    """
    out: dict[int, dict[str, Any]] = {}
    if not preds:
        return out

    disabled: dict[str, Any] = {
        "pinnacle_home_decimal": None,
        "pinnacle_away_decimal": None,
        "edge_home": None,
        "edge_away": None,
        "bet_decision_home": None,
        "bet_decision_away": None,
        "live_odds_status": "disabled",
    }
    if not live_pinnacle:
        for p in preds:
            out[int(p.id)] = dict(disabled)
        return out

    neutral: dict[str, Any] = {
        "pinnacle_home_decimal": None,
        "pinnacle_away_decimal": None,
        "edge_home": None,
        "edge_away": None,
        "bet_decision_home": None,
        "bet_decision_away": None,
        "live_odds_status": None,
    }

    nhl_ml = [p for p in preds if _is_nhl_moneyline(p)]
    quotes_by_match: dict[str, PinnacleH2HQuote | None] | None = None
    fetch_error: str | None = None

    if nhl_ml:
        if not has_configured_odds_api_key():
            fetch_error = "missing_api_key"
        else:
            try:
                quotes_by_match = _fetch_quotes_map(nhl_ml)
            except (
                QuotaBudgetError,
                requests.RequestException,
                OSError,
                ValueError,
                RuntimeError,
            ) as e:
                logger.warning("Live Pinnacle: fetch failed (%s)", type(e).__name__)
                fetch_error = "fetch_failed"

    params = load_edge_decision_params()

    for p in preds:
        pid = int(p.id)
        if not _is_nhl_tournament(p.tournament):
            row = dict(neutral)
            row["live_odds_status"] = "skipped_not_nhl"
            out[pid] = row
            continue
        if not _is_moneyline_market(p.market):
            row = dict(neutral)
            row["live_odds_status"] = "skipped_unsupported_market"
            out[pid] = row
            continue

        if fetch_error == "missing_api_key":
            out[pid] = build_live_moneyline_extras(
                proba_home=proba_home_from_prediction(p),
                quote=None,
                params=params,
                status="missing_api_key",
            )
            continue
        if fetch_error == "fetch_failed":
            out[pid] = build_live_moneyline_extras(
                proba_home=proba_home_from_prediction(p),
                quote=None,
                params=params,
                status="fetch_failed",
            )
            continue

        assert quotes_by_match is not None  # при наличии NHL ML и успешном fetch
        q = quotes_by_match.get(str(p.match_id))
        st = "ok" if q is not None else "no_quote"
        out[pid] = build_live_moneyline_extras(
            proba_home=proba_home_from_prediction(p),
            quote=q,
            params=params,
            status=st,
        )

    return out


__all__ = ["batch_live_response_extras"]
