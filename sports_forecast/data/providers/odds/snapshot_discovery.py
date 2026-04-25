"""Планирование снимков для The Odds API: динамика по `commence_time` и legacy-fallback.

**R21.11:** целевой путь — один **close**-снимок за *N* минут до
``min(commence_time)`` (см. :class:`CloseSnapshotPlan`, :func:`discover_close_snapshot_for_day`).

Устаревший (но сохранён для тестов) — :func:`discover_snapshots_for_day` (open/close, probe-цикл).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Protocol, runtime_checkable

from sports_forecast.data.providers.odds.enrichment import unwrap_odds_payload
from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class SnapshotPlan:
    """Набор ISO-моментов снимков и смещений от опорного ``commence_time`` (R21 V2, legacy)."""

    open_iso: str
    close_iso: str
    open_minutes_before: int
    close_minutes_before: int
    reference_commence_time_utc: str | None
    used_legacy_timestamps: bool


@dataclass(frozen=True, slots=True)
class CloseSnapshotPlan:
    """Один close-снимок (R21.11 V3): момент запроса, минуты до ``commence``, опорный ``commence``."""

    close_iso: str
    close_minutes_before: int
    reference_commence_time_utc: str | None
    used_legacy_timestamps: bool


@runtime_checkable
class HistoricalOddsClient(Protocol):
    """Минимальный контракт клиента (для тестов / моков)."""

    def fetch_odds_for_sport(
        self,
        sport_key: str,
        *,
        regions: str = "us",
        markets: list[str] | None = None,
        odds_format: str = "decimal",
        date_iso: str | None = None,
        use_cache: bool = True,
    ) -> Any:
        """См. :meth:`sports_forecast.data.providers.odds.client.OddsApiClient.fetch_odds_for_sport`."""
        ...


def _as_utc_datetime(raw: str) -> datetime | None:
    if not raw or not isinstance(raw, str):
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_commence_utc_from_event(ev: dict[str, Any]) -> datetime | None:
    """Распарсить момент старта матча из полей ``commence_time`` / ``commenceTime`` (UTC)."""
    raw = ev.get("commence_time") or ev.get("commenceTime")
    return _as_utc_datetime(str(raw)) if raw else None


def commence_datetimes_utc_on_day(
    events: Sequence[dict[str, Any]],
    day: date,
) -> list[datetime]:
    """Собрать ``commence_time`` всех событий, у которых календарная дата (UTC) равна ``day``."""
    out: list[datetime] = []
    for ev in events:
        if not isinstance(ev, dict):
            continue
        dt = parse_commence_utc_from_event(ev)
        if dt is None:
            continue
        if dt.date() == day:
            out.append(dt)
    return out


def commence_datetimes_from_events_payload(payload: Any, day: date) -> list[datetime]:
    """Из тела ответа API (dict/list) извлечь ``commence_time`` для матчей на календарный день ``day``."""
    return commence_datetimes_utc_on_day(unwrap_odds_payload(payload), day)


def earliest_commence_on_day_from_payload(payload: Any, day: date) -> datetime | None:
    """``min(commence_time)`` по событиям, попадающим на ``day`` (UTC), либо ``None``."""
    times = commence_datetimes_from_events_payload(payload, day)
    if not times:
        return None
    return min(times)


def to_api_iso_z(dt: datetime) -> str:
    """Нормализованный ISO для параметра ``date`` The Odds API (суффикс ``Z``)."""
    d = dt.astimezone(timezone.utc).replace(microsecond=0)
    return d.isoformat().replace("+00:00", "Z")


def build_close_snapshot_iso(earliest_commence_utc: datetime, close_margin_hours: float) -> str:
    """Время снимка close: ``earliest_commence_utc - close_margin_hours`` (legacy R21.4)."""
    delta = timedelta(hours=float(close_margin_hours))
    return to_api_iso_z(earliest_commence_utc - delta)


def build_close_snapshot_iso_tminus(
    earliest_commence_utc: datetime, close_t_minus_minutes: int
) -> str:
    """Момент close-снимка: ``earliest_commence_utc - close_t_minus_minutes`` (R21.11 V3)."""
    delta = timedelta(minutes=int(close_t_minus_minutes))
    return to_api_iso_z(earliest_commence_utc - delta)


def minutes_before_commence(
    reference_commence_utc: datetime,
    snapshot_utc: datetime,
) -> int:
    """Минуты от ``snapshot`` до ``commence``; неотрицательно (снимок не позже старта матча)."""
    delta = reference_commence_utc - snapshot_utc.astimezone(timezone.utc)
    secs = int(delta.total_seconds())
    return max(0, secs // 60)


def has_events_for_calendar_day(payload: Any, day: date) -> bool:
    """Есть ли в ответе хотя бы одно событие с ``commence_time`` на дату ``day`` (UTC)."""
    return bool(commence_datetimes_from_events_payload(payload, day))


def _legacy_isos(
    day: date,
    legacy_open_time_utc: str,
    legacy_close_time_utc: str,
) -> tuple[str, str]:
    """Собрать ISO для legacy open/close (``HH:MM:SS`` + день, как в backfill)."""
    to = str(legacy_open_time_utc).strip()
    tc = str(legacy_close_time_utc).strip()
    if "T" in to and ("Z" in to or "+" in to):
        open_iso = to
    else:
        open_iso = f"{day.isoformat()}T{to}Z" if not to.upper().endswith("Z") else to
    if "T" in tc and ("Z" in tc or "+" in tc):
        close_iso = tc
    else:
        close_iso = f"{day.isoformat()}T{tc}Z" if not tc.upper().endswith("Z") else tc
    return (open_iso, close_iso)


def _parse_any_iso_to_utc(s: str) -> datetime:
    s2 = s.replace("Z", "+00:00")
    return datetime.fromisoformat(s2).astimezone(timezone.utc)


def discover_close_snapshot_for_day(
    client: HistoricalOddsClient,
    sport_key: str,
    day: date,
    *,
    regions: str = "us",
    close_t_minus_minutes: int = 15,
    legacy_open_time_utc: str = "12:00:00",
    legacy_close_time_utc: str = "23:30:00",
    use_cache: bool = True,
) -> tuple[CloseSnapshotPlan, Any]:
    """Выбрать момент **одного** close-снимка и вернуть payload (R21.11, V3 close-only store).

    Алгоритм:
        1. **Seed-запрос** в ``{day}T{legacy_open}``; из ответа — ``min(commence_time)`` на ``day`` (UTC).
        2. Если ``commence`` известен: ``close_iso = min(commence) - close_t_minus_minutes``; второй
           запрос по ``close_iso`` (фактическая линия close).
        3. Иначе: снимок по фиксированному ``legacy_close`` (как R20) — без опорного ``commence``.

    **HTTP:** до 2 GET на день (seed + close) — без цикла open-probe.

    Args:
        client: Клиент The Odds API.
        sport_key: Ключ спорта (например ``icehockey_nhl``).
        day: Календарный день матчей (сравнение с ``commence_time`` в UTC).
        close_t_minus_minutes: За сколько минут до старта ближайшего матча снимать close (NHL V3: 15).
        legacy_open_time_utc: Время/ISO **seed**-запроса, чтобы извлечь ``commence`` (как в R21.4).
        legacy_close_time_utc: Запасной момент снимка, если ``commence`` в seed не определён.
        use_cache: Кэш клиента.

    Returns:
        ``(план, payload_close)`` — сырой ответ API с линиями **на момент** ``close_iso``.
    """
    legacy_o, legacy_c = _legacy_isos(day, legacy_open_time_utc, legacy_close_time_utc)
    try:
        p_seed = client.fetch_odds_for_sport(
            sport_key,
            regions=regions,
            date_iso=legacy_o,
            use_cache=use_cache,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("close snapshot: seed fetch failed (%s), legacy close only", exc)
        p_seed = {}
    ref_dt = earliest_commence_on_day_from_payload(p_seed, day)
    if ref_dt is None:
        p_close = client.fetch_odds_for_sport(
            sport_key, regions=regions, date_iso=legacy_c, use_cache=use_cache
        )
        plan = CloseSnapshotPlan(
            close_iso=legacy_c,
            close_minutes_before=0,
            reference_commence_time_utc=None,
            used_legacy_timestamps=True,
        )
        return (plan, p_close)
    close_iso = build_close_snapshot_iso_tminus(ref_dt, close_t_minus_minutes)
    p_close = client.fetch_odds_for_sport(
        sport_key, regions=regions, date_iso=close_iso, use_cache=use_cache
    )
    ref_iso = to_api_iso_z(ref_dt)
    close_m = minutes_before_commence(ref_dt, _parse_any_iso_to_utc(close_iso))
    plan = CloseSnapshotPlan(
        close_iso=close_iso,
        close_minutes_before=close_m,
        reference_commence_time_utc=ref_iso,
        used_legacy_timestamps=False,
    )
    return (plan, p_close)


def discover_snapshots_for_day(
    client: HistoricalOddsClient,
    sport_key: str,
    day: date,
    *,
    regions: str = "us",
    open_probe_offsets_hours: Sequence[float] = (168.0, 72.0, 24.0),
    close_margin_hours: float = 1.0,
    legacy_open_time_utc: str = "12:00:00",
    legacy_close_time_utc: str = "23:30:00",
    use_cache: bool = True,
) -> tuple[SnapshotPlan, Any, Any]:
    """Подобрать open/close ISO и вернуть два сырpayload (open/close), как в backfill R21.

    Алгоритм:
        1. Запрос-seed в ``{day}T{legacy_open}``; из ответа — ``min(commence_time)`` по матчам
           календарного дня (UTC).
        2. Если ``commence`` известен: close = ``min(commence) - close_margin_hours``;
           open — перебор ``open_probe_offsets_hours`` от большего к меньшему, первый ответ, где
           есть события на ``day`` (данные на нужный день).
        3. Иначе (нет ``commence`` / пусто): open и close из legacy fixed times (как R20 backfill).
        4. Если close известен, а все пробы open пусты — open берётся из legacy.

    Args:
        client: Клиент The Odds API.
        sport_key: Ключ спорта, например ``icehockey_nhl``.
        day: Календарный день матчей (часовой пояс для сравнения — UTC по ``commence_time``).
        regions: Параметр ``regions`` запроса.
        open_probe_offsets_hours: Смещения (часов назад от ``earliest_commence``), по убыванию.
        close_margin_hours: Снимок close за столько часов до ``min(commence)``.
        legacy_open_time_utc: Время/ISO fallback для open (как ``backfill.open_snapshot_utc``).
        legacy_close_time_utc: Время/ISO fallback для close.
        use_cache: Пробрасывается в клиент.

    Returns:
        ``(план, payload_open, payload_close)`` — payload те же, что отдаёт API (dict/list).
    """
    legacy_o, legacy_c = _legacy_isos(day, legacy_open_time_utc, legacy_close_time_utc)
    seed_iso = legacy_o

    p_open: Any = {}
    p_seed: Any
    try:
        p_seed = client.fetch_odds_for_sport(
            sport_key,
            regions=regions,
            date_iso=seed_iso,
            use_cache=use_cache,
        )
    except Exception as exc:  # noqa: BLE001 — устойчивость к сети/кэшу; fallback
        logger.warning("Snapshot discovery: seed fetch failed (%s), using legacy", exc)
        p_seed = {}

    ref_dt = earliest_commence_on_day_from_payload(p_seed, day)

    if ref_dt is None:
        p_open = client.fetch_odds_for_sport(
            sport_key, regions=regions, date_iso=legacy_o, use_cache=use_cache
        )
        p_close = client.fetch_odds_for_sport(
            sport_key, regions=regions, date_iso=legacy_c, use_cache=use_cache
        )
        plan = SnapshotPlan(
            open_iso=legacy_o,
            close_iso=legacy_c,
            open_minutes_before=0,
            close_minutes_before=0,
            reference_commence_time_utc=None,
            used_legacy_timestamps=True,
        )
        return (plan, p_open, p_close)

    close_iso = build_close_snapshot_iso(ref_dt, close_margin_hours)
    p_close = client.fetch_odds_for_sport(
        sport_key, regions=regions, date_iso=close_iso, use_cache=use_cache
    )
    ref_iso = to_api_iso_z(ref_dt)
    close_minutes = minutes_before_commence(ref_dt, _parse_any_iso_to_utc(close_iso))

    sorted_offsets = sorted(
        (float(x) for x in open_probe_offsets_hours),
        reverse=True,
    )
    chosen_open: str | None = None
    for off in sorted_offsets:
        t_snap = ref_dt - timedelta(hours=off)
        o_iso = to_api_iso_z(t_snap)
        try:
            p_try = client.fetch_odds_for_sport(
                sport_key, regions=regions, date_iso=o_iso, use_cache=use_cache
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("open probe at %s failed: %s", o_iso, exc)
            continue
        if has_events_for_calendar_day(p_try, day):
            chosen_open = o_iso
            p_open = p_try
            break

    if chosen_open is None:
        p_open = client.fetch_odds_for_sport(
            sport_key, regions=regions, date_iso=legacy_o, use_cache=use_cache
        )
        open_minutes = minutes_before_commence(ref_dt, _parse_any_iso_to_utc(legacy_o))
        used_legacy = True
        o_iso = legacy_o
    else:
        open_minutes = minutes_before_commence(ref_dt, _parse_any_iso_to_utc(chosen_open))
        used_legacy = False
        o_iso = chosen_open

    plan = SnapshotPlan(
        open_iso=o_iso,
        close_iso=close_iso,
        open_minutes_before=open_minutes,
        close_minutes_before=close_minutes,
        reference_commence_time_utc=ref_iso,
        used_legacy_timestamps=used_legacy,
    )
    return (plan, p_open, p_close)
