"""
Текущие decimal Pinnacle (h2h) для NHL через The Odds API.

Один батч-запрос ``/sports/{sport}/odds`` на вызов; лимит ``max_real_http_requests`` у
:class:`~sports_forecast.data.providers.odds.client.OddsApiClient` задаётся из
``conf/bookmaker/the_odds_api.yaml`` → ``live_inference.max_real_http_requests``.

По умолчанию **не** используется дисковый кэш ответа (``allow_disk_cache_for_live_odds:
false``), чтобы витрина и digest получали актуальные линии, а не снимок из ``data/cache``.

Сопоставление ``match_id`` витрины (NHL ``id`` из processed) с событиями API:

В строгом режиме команды и турнир разрешаются словарями источников, затем матч
выбирается по сторонам и времени. Для legacy режима сохранено прежнее сопоставление.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from math import inf
from typing import Any

from omegaconf import DictConfig, OmegaConf

from sports_forecast.config.loaders import load_bookmaker_config
from sports_forecast.data.providers.odds.client import OddsApiClient
from sports_forecast.data.providers.odds.enrichment import (
    _find_bookmaker,
    _h2h_prices,
    unwrap_odds_payload,
)
from sports_forecast.data.providers.odds.team_name_registry import (
    TeamNameRegistry,
    normalize_team_key,
)
from sports_forecast.identity.derived_event_matching import (
    DerivedEventCandidate,
    match_derived_events,
)
from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class NHLLiveMatchRef:
    """Матч витрины для сопоставления с событием The Odds API."""

    match_id: str
    home_team: str
    away_team: str
    commence_utc: datetime | None = None


@dataclass(frozen=True, slots=True)
class PinnacleH2HQuote:
    """Денежная линия Pinnacle (2-way h2h) для одного события API."""

    odds_api_event_id: str
    home_team: str
    away_team: str
    commence_utc: datetime | None
    decimal_home: float | None
    decimal_away: float | None


def _parse_commence_utc(raw: object) -> datetime | None:
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _team_merge_key(name: str, registry: TeamNameRegistry | None) -> str:
    if registry is not None and not registry.is_empty:
        return registry.resolve(name)
    return normalize_team_key(name)


def extract_pinnacle_h2h_quote(
    ev: dict[str, Any],
    *,
    bookmaker_key: str,
    team_registry: TeamNameRegistry | None = None,
) -> PinnacleH2HQuote | None:
    """Вытащить Pinnacle h2h из одного события JSON; ``None`` если линии нет."""
    eid = str(ev.get("id") or "").strip()
    if not eid:
        return None
    home_name = str(ev.get("home_team") or "")
    away_name = str(ev.get("away_team") or "")
    bm = _find_bookmaker(ev, bookmaker_key)
    if bm is None:
        return None
    markets = [
        item
        for item in bm.get("markets") or []
        if isinstance(item, dict) and str(item.get("key")) == "h2h"
    ]
    if len(markets) != 1:
        return None
    outcomes = markets[0].get("outcomes")
    if not isinstance(outcomes, list) or len(outcomes) != 2:
        return None
    expected_names = {
        _team_merge_key(home_name, team_registry),
        _team_merge_key(away_name, team_registry),
    }
    actual_names = {
        _team_merge_key(str(item.get("name") or ""), team_registry)
        for item in outcomes
        if isinstance(item, dict)
    }
    if len(expected_names) != 2 or actual_names != expected_names:
        return None
    hh, aa, _dd = _h2h_prices(bm, home_name, away_name, team_registry=team_registry)
    if hh is None or aa is None or hh <= 1.0 or aa <= 1.0:
        return None
    return PinnacleH2HQuote(
        odds_api_event_id=eid,
        home_team=home_name,
        away_team=away_name,
        commence_utc=_parse_commence_utc(ev.get("commence_time")),
        decimal_home=hh,
        decimal_away=aa,
    )


def parse_pinnacle_h2h_quotes_from_payload(
    payload: Any,
    *,
    bookmaker_key: str,
    team_registry: TeamNameRegistry | None = None,
) -> list[PinnacleH2HQuote]:
    """Разобрать тело ответа ``/odds`` в список котировок Pinnacle h2h."""
    events = unwrap_odds_payload(payload)
    out: list[PinnacleH2HQuote] = []
    for ev in events:
        q = extract_pinnacle_h2h_quote(ev, bookmaker_key=bookmaker_key, team_registry=team_registry)
        if q is not None:
            out.append(q)
    return out


def _extract_registry_resolved_quote(
    event: dict[str, Any],
    *,
    bookmaker_key: str,
    home_team_id: str,
    away_team_id: str,
    resolve_team_id: Callable[[dict[str, Any], str], str | None],
) -> PinnacleH2HQuote | None:
    """Разобрать two-way quote по подтверждённым provider team aliases."""
    event_id = str(event.get("id") or "").strip()
    home_name = str(event.get("home_team") or "").strip()
    away_name = str(event.get("away_team") or "").strip()
    bookmaker = _find_bookmaker(event, bookmaker_key)
    if not event_id or not home_name or not away_name or bookmaker is None:
        return None
    markets = [
        market
        for market in bookmaker.get("markets") or []
        if isinstance(market, dict) and market.get("key") == "h2h"
    ]
    if len(markets) != 1:
        return None
    outcomes = markets[0].get("outcomes")
    if not isinstance(outcomes, list) or len(outcomes) != 2:
        return None
    prices_by_team: dict[str, float] = {}
    for outcome in outcomes:
        if not isinstance(outcome, dict):
            return None
        outcome_name = str(outcome.get("name") or "").strip()
        team_id = resolve_team_id(event, outcome_name)
        try:
            price = float(outcome.get("price"))
        except (TypeError, ValueError):
            return None
        if team_id not in {home_team_id, away_team_id} or not math.isfinite(price) or price <= 1.0:
            return None
        if team_id in prices_by_team:
            return None
        prices_by_team[team_id] = price
    if set(prices_by_team) != {home_team_id, away_team_id}:
        return None
    return PinnacleH2HQuote(
        odds_api_event_id=event_id,
        home_team=home_name,
        away_team=away_name,
        commence_utc=_parse_commence_utc(event.get("commence_time")),
        decimal_home=prices_by_team[home_team_id],
        decimal_away=prices_by_team[away_team_id],
    )


def _commence_delta_minutes(a: datetime | None, b: datetime | None) -> float | None:
    if a is None or b is None:
        return None
    return abs((a - b).total_seconds()) / 60.0


def map_match_refs_to_pinnacle_quotes(
    refs: Sequence[NHLLiveMatchRef],
    quotes: Sequence[PinnacleH2HQuote],
    *,
    team_registry: TeamNameRegistry | None = None,
    commence_tolerance_minutes: int = 360,
    event_id_to_match_id: Mapping[str, str] | None = None,
    calendar_identity_by_match: Mapping[str, DerivedEventCandidate] | None = None,
    calendar_window_candidates: Sequence[DerivedEventCandidate] | None = None,
    provider_window_candidates: Sequence[DerivedEventCandidate] | None = None,
    quote_identity_resolver: Callable[[PinnacleH2HQuote], DerivedEventCandidate] | None = None,
) -> dict[str, PinnacleH2HQuote | None]:
    """Сопоставить ``match_id`` из витрины с котировками (overrides → fuzzy по командам/времени)."""
    out: dict[str, PinnacleH2HQuote | None] = {r.match_id: None for r in refs}
    has_provider_identity = (
        quote_identity_resolver is not None or provider_window_candidates is not None
    )
    if (calendar_identity_by_match is None) != (not has_provider_identity):
        raise ValueError("Derived live matching требует обе коллекции подтверждённых обозначений")
    if calendar_identity_by_match is not None and (
        quote_identity_resolver is not None or provider_window_candidates is not None
    ):
        refs_by_candidate_key = {
            calendar_identity_by_match[ref.match_id].key: ref.match_id
            for ref in refs
            if ref.match_id in calendar_identity_by_match
        }
        calendar_candidates = list(calendar_window_candidates or ())
        known_keys = {candidate.key for candidate in calendar_candidates}
        calendar_candidates.extend(
            candidate
            for candidate in calendar_identity_by_match.values()
            if candidate.key not in known_keys
        )
        provider_candidates = list(provider_window_candidates or ())
        if not provider_candidates and quote_identity_resolver is not None:
            provider_candidates = [quote_identity_resolver(quote) for quote in quotes]
        result = match_derived_events(calendar_candidates, provider_candidates)
        quote_by_id = {quote.odds_api_event_id: quote for quote in quotes}
        for provider_id, calendar_key in result.provider_to_calendar.items():
            match_id = refs_by_candidate_key.get(calendar_key)
            if match_id in out and provider_id in quote_by_id:
                out[match_id] = quote_by_id[provider_id]
        for provider_id, reason in result.provider_reasons.items():
            logger.debug(
                "live odds: event match unresolved provider_event_id=%s reason=%s",
                provider_id,
                reason,
            )
        for ref in refs:
            if ref.match_id not in calendar_identity_by_match:
                logger.debug(
                    "live odds: event match unresolved match_id=%s reason=unconfirmed_calendar_designation",
                    ref.match_id,
                )
        return out
    quotes_by_id = {q.odds_api_event_id: q for q in quotes}
    used_quote_ids: set[str] = set()

    overrides = dict(event_id_to_match_id or {})
    for eid, mid in overrides.items():
        if mid not in out:
            logger.debug("live_inference: неизвестный match_id в override %s → %s", eid, mid)
            continue
        q = quotes_by_id.get(str(eid))
        if q is None:
            logger.debug("live_inference: событие %s не найдено в ответе API", eid)
            continue
        out[mid] = q
        used_quote_ids.add(q.odds_api_event_id)

    refs_sorted = sorted(
        refs,
        key=lambda r: (
            r.commence_utc is None,
            r.commence_utc or datetime(1970, 1, 1, tzinfo=UTC),
        ),
    )

    for ref in refs_sorted:
        if out[ref.match_id] is not None:
            continue
        hk = _team_merge_key(ref.home_team, team_registry)
        ak = _team_merge_key(ref.away_team, team_registry)
        best_q: PinnacleH2HQuote | None = None
        best_score: float = inf

        for q in quotes:
            if q.odds_api_event_id in used_quote_ids:
                continue
            qh = _team_merge_key(q.home_team, team_registry)
            qa = _team_merge_key(q.away_team, team_registry)
            if qh != hk or qa != ak:
                continue
            delta = _commence_delta_minutes(ref.commence_utc, q.commence_utc)
            if delta is None:
                score = 0.0
            else:
                score = float(delta)
                if score > float(commence_tolerance_minutes):
                    continue

            if score < best_score:
                best_score = score
                best_q = q

        if best_q is None and ref.commence_utc is None:
            # Несколько матчей с одними аббревиатурами без времени — не угадываем.
            candidates = [
                q
                for q in quotes
                if q.odds_api_event_id not in used_quote_ids
                and _team_merge_key(q.home_team, team_registry) == hk
                and _team_merge_key(q.away_team, team_registry) == ak
            ]
            if len(candidates) == 1:
                best_q = candidates[0]

        if best_q is not None:
            out[ref.match_id] = best_q
            used_quote_ids.add(best_q.odds_api_event_id)

    return out


def build_odds_client_for_live(book_cfg: DictConfig) -> OddsApiClient:
    """Создать :class:`OddsApiClient` с лимитом сетевых запросов из ``live_inference``."""
    live = OmegaConf.select(book_cfg, "bookmaker.live_inference") or {}
    raw_mx = live.get("max_real_http_requests")
    mx = int(raw_mx) if raw_mx is not None else 2
    return OddsApiClient(book_cfg, max_real_http_requests=mx)


def fetch_nhl_pinnacle_quotes_for_refs(
    refs: Sequence[NHLLiveMatchRef],
    *,
    book_cfg: DictConfig | None = None,
    team_registry: TeamNameRegistry | None = None,
    client: OddsApiClient | None = None,
    sport_key: str | None = None,
    bookmaker_key: str | None = None,
    calendar_identity_by_match: Mapping[str, DerivedEventCandidate] | None = None,
    calendar_window_candidates: Sequence[DerivedEventCandidate] | None = None,
    provider_event_identity_resolver: Callable[[dict[str, Any]], DerivedEventCandidate]
    | None = None,
    quote_identity_resolver: Callable[[PinnacleH2HQuote], DerivedEventCandidate] | None = None,
    provider_outcome_team_resolver: Callable[[dict[str, Any], str], str | None] | None = None,
) -> dict[str, PinnacleH2HQuote | None]:
    """Один запрос odds NHL + сопоставление со списком матчей витрины.

    Args:
        refs: Матчи из prediction store (или планировщика).
        book_cfg: Обёртка ``{bookmaker: ...}`` как у :func:`~sports_forecast.config.loaders.load_bookmaker_config`;
            при ``None`` загружается ``the_odds_api``.
        team_registry: Реестр имён команд NHL; ``None`` — только :func:`normalize_team_key`.
        client: Готовый клиент (тесты); иначе строится через :func:`build_odds_client_for_live`.

    Returns:
        ``match_id`` → котировка или ``None`` при отсутствии линии / неоднозначности.

    Raises:
        ValueError: Нет ``ODDS_API_KEY`` / конфига (пробрасывается из клиента).
        QuotaBudgetError: Исчерпан лимит сетевых запросов (см. :class:`~sports_forecast.data.providers.odds.client.OddsApiClient`).
    """
    cfg = book_cfg if book_cfg is not None else load_bookmaker_config("the_odds_api")
    if cfg is None:
        raise ValueError("Не найден conf/bookmaker/the_odds_api.yaml")

    live = OmegaConf.select(cfg, "bookmaker.live_inference") or {}
    resolved_sport_key = sport_key or str(
        OmegaConf.select(cfg, "bookmaker.sport_keys.nhl") or "icehockey_nhl"
    )
    resolved_bookmaker_key = bookmaker_key or str(
        OmegaConf.select(cfg, "bookmaker.bookmakers.primary") or "pinnacle"
    )
    regions = str(live.get("regions", "eu"))
    tol = int(live.get("commence_tolerance_minutes", 360))
    # Для витрины нужны актуальные линии; дисковый кэш клиента иначе может отдать
    # устаревший снимок → no_quote по всем матчам. Включайте allow_disk_cache_for_live_odds
    # только для локальной отладки без сети.
    use_disk_cache = bool(live.get("allow_disk_cache_for_live_odds", False))
    overrides_any = live.get("event_id_to_match_id")
    overrides: dict[str, str] = {}
    if isinstance(overrides_any, dict):
        overrides = {str(k): str(v) for k, v in overrides_any.items()}

    oc = client or build_odds_client_for_live(cfg)
    payload = oc.fetch_odds_for_sport(
        resolved_sport_key,
        regions=regions,
        markets=["h2h"],
        use_cache=use_disk_cache,
    )
    source_events = unwrap_odds_payload(payload)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for event in source_events:
        provider_id = str(event.get("id") or "").strip()
        if provider_id:
            grouped.setdefault(provider_id, []).append(event)
    unique_events: dict[str, dict[str, Any]] = {}
    for provider_id, rows in grouped.items():
        usable = [
            row
            for row in rows
            if _parse_commence_utc(row.get("commence_time")) is not None
            and str(row.get("home_team") or "").strip()
            and str(row.get("away_team") or "").strip()
        ]
        distinct = {json.dumps(row, sort_keys=True, separators=(",", ":")): row for row in usable}
        if len(distinct) == 1:
            unique_events[provider_id] = next(iter(distinct.values()))
        elif len(distinct) > 1:
            logger.debug(
                "live odds: provider event rejected provider_event_id=%s reason=conflicting_duplicate_source_event_id",
                provider_id,
            )

    provider_candidates_by_id: dict[str, DerivedEventCandidate] = {}
    if provider_event_identity_resolver is not None:
        provider_candidates_by_id = {
            provider_id: provider_event_identity_resolver(event)
            for provider_id, event in unique_events.items()
        }
    if provider_event_identity_resolver is not None and provider_outcome_team_resolver is not None:
        quotes = []
        for provider_id, event in unique_events.items():
            candidate = provider_candidates_by_id[provider_id]
            if candidate.unresolved_reason is not None:
                continue
            quote = _extract_registry_resolved_quote(
                event,
                bookmaker_key=resolved_bookmaker_key,
                home_team_id=candidate.home_team_id or "",
                away_team_id=candidate.away_team_id or "",
                resolve_team_id=provider_outcome_team_resolver,
            )
            if quote is not None:
                quotes.append(quote)
    else:
        quotes = parse_pinnacle_h2h_quotes_from_payload(
            payload,
            bookmaker_key=resolved_bookmaker_key,
            team_registry=team_registry,
        )
    quotes = [quote for quote in quotes if quote.odds_api_event_id in unique_events]
    return map_match_refs_to_pinnacle_quotes(
        refs,
        quotes,
        team_registry=team_registry,
        commence_tolerance_minutes=tol,
        event_id_to_match_id=overrides,
        calendar_identity_by_match=calendar_identity_by_match,
        calendar_window_candidates=calendar_window_candidates,
        provider_window_candidates=(
            list(provider_candidates_by_id.values())
            if provider_event_identity_resolver is not None
            else None
        ),
        quote_identity_resolver=quote_identity_resolver,
    )


__all__ = [
    "NHLLiveMatchRef",
    "PinnacleH2HQuote",
    "build_odds_client_for_live",
    "extract_pinnacle_h2h_quote",
    "fetch_nhl_pinnacle_quotes_for_refs",
    "map_match_refs_to_pinnacle_quotes",
    "parse_pinnacle_h2h_quotes_from_payload",
]
