"""
Текущие decimal Pinnacle (h2h) для NHL через The Odds API.

Один батч-запрос ``/sports/{sport}/odds`` на вызов; лимит ``max_real_http_requests`` у
:class:`~sports_forecast.data.providers.odds.client.OddsApiClient` задаётся из
``conf/bookmaker/the_odds_api.yaml`` → ``live_inference.max_real_http_requests``.

Сопоставление ``match_id`` витрины (NHL ``id`` из processed) с событиями API:

1. Явные пары ``live_inference.event_id_to_match_id`` (ключ — ``id`` события в JSON).
2. Иначе — по каноническим ключам команд (:class:`~sports_forecast.data.providers.odds.team_name_registry.TeamNameRegistry`)
   и опционально по близости ``commence_time`` (порог ``commence_tolerance_minutes``).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
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
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


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
    hh, aa, _dd = _h2h_prices(bm, home_name, away_name, team_registry=team_registry)
    if hh is None and aa is None:
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
) -> dict[str, PinnacleH2HQuote | None]:
    """Сопоставить ``match_id`` из витрины с котировками (overrides → fuzzy по командам/времени)."""
    out: dict[str, PinnacleH2HQuote | None] = {r.match_id: None for r in refs}
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
            r.commence_utc or datetime(1970, 1, 1, tzinfo=timezone.utc),
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
    sport_key = str(OmegaConf.select(cfg, "bookmaker.sport_keys.nhl") or "icehockey_nhl")
    bookmaker_key = str(OmegaConf.select(cfg, "bookmaker.bookmakers.primary") or "pinnacle")
    regions = str(live.get("regions", "us"))
    tol = int(live.get("commence_tolerance_minutes", 360))
    overrides_any = live.get("event_id_to_match_id")
    overrides: dict[str, str] = {}
    if isinstance(overrides_any, dict):
        overrides = {str(k): str(v) for k, v in overrides_any.items()}

    oc = client or build_odds_client_for_live(cfg)
    payload = oc.fetch_odds_for_sport(
        sport_key,
        regions=regions,
        markets=["h2h"],
        use_cache=True,
    )
    quotes = parse_pinnacle_h2h_quotes_from_payload(
        payload,
        bookmaker_key=bookmaker_key,
        team_registry=team_registry,
    )
    return map_match_refs_to_pinnacle_quotes(
        refs,
        quotes,
        team_registry=team_registry,
        commence_tolerance_minutes=tol,
        event_id_to_match_id=overrides,
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
