"""Итерация по календарю и загрузка расписания NHL (эндпоинт ``schedule/{YYYY-MM-DD}``)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from sports_forecast.data.providers.nhl.client import NhlApiClient
from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)

_SCHEDULE_PROGRESS_VERSION = 1


@dataclass(frozen=True)
class ScheduleGameStub:
    """Сводка матча, извлечённая из JSON расписания (до запросов boxscore)."""

    game_id: int
    season: int
    game_type: int
    game_date: str
    start_time_utc: str
    venue_default: str
    home_abbrev: str
    away_abbrev: str
    game_state: str
    match_end: str | None
    home_score: int | None
    away_score: int | None


def stub_to_dict(stub: ScheduleGameStub) -> dict[str, Any]:
    """Сериализация стаба матча для JSON-файла прогресса расписания."""
    return {
        "game_id": stub.game_id,
        "season": stub.season,
        "game_type": stub.game_type,
        "game_date": stub.game_date,
        "start_time_utc": stub.start_time_utc,
        "venue_default": stub.venue_default,
        "home_abbrev": stub.home_abbrev,
        "away_abbrev": stub.away_abbrev,
        "game_state": stub.game_state,
        "match_end": stub.match_end,
        "home_score": stub.home_score,
        "away_score": stub.away_score,
    }


def stub_from_dict(d: dict[str, Any]) -> ScheduleGameStub:
    """Восстановить стаб из словаря :func:`stub_to_dict`."""
    return ScheduleGameStub(
        game_id=int(d["game_id"]),
        season=int(d["season"]),
        game_type=int(d["game_type"]),
        game_date=str(d["game_date"]),
        start_time_utc=str(d["start_time_utc"]),
        venue_default=str(d.get("venue_default") or ""),
        home_abbrev=str(d["home_abbrev"]),
        away_abbrev=str(d["away_abbrev"]),
        game_state=str(d.get("game_state") or ""),
        match_end=str(d["match_end"]) if d.get("match_end") is not None else None,
        home_score=int(d["home_score"]) if d.get("home_score") is not None else None,
        away_score=int(d["away_score"]) if d.get("away_score") is not None else None,
    )


def _align_resume_to_week_grid(date_from: date, resume: date, date_to: date) -> date:
    """Первый якорь в сетке ``date_from + 7k``, для которого дата >= ``resume`` (не выше ``date_to``)."""
    cur = date_from
    while cur < resume:
        nxt = cur + timedelta(days=7)
        if nxt > date_to:
            return cur
        cur = nxt
    return min(cur, date_to)


def save_schedule_progress(
    path: Path,
    *,
    by_id: dict[int, ScheduleGameStub],
    next_anchor: date,
    date_from: date,
    date_to: date,
    season_min: int | None,
    season_max: int | None,
    finished_only: bool,
    schedule_complete: bool = False,
) -> None:
    """Атомарно сохранить состояние сбора расписания (для возобновления после обрыва).

    Если ``schedule_complete=True``, при следующем запуске HTTP-запросы расписания
    не выполняются — используется сохранённый индекс матчей (пока файл не удалён).
    """
    games_out: dict[str, dict[str, Any]] = {str(gid): stub_to_dict(st) for gid, st in by_id.items()}
    payload = {
        "version": _SCHEDULE_PROGRESS_VERSION,
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "season_min": season_min,
        "season_max": season_max,
        "finished_only": finished_only,
        "next_anchor": next_anchor.isoformat(),
        "schedule_complete": schedule_complete,
        "games": games_out,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(payload, ensure_ascii=False, indent=2)
    tmp_path = path.with_name(path.name + ".tmp")
    tmp_path.write_text(data, encoding="utf-8")
    tmp_path.replace(path)


def _saved_date_to_from_progress(raw: dict[str, Any]) -> date | None:
    try:
        return date.fromisoformat(str(raw.get("date_to", "")))
    except (TypeError, ValueError):
        return None


def load_schedule_progress(
    path: Path,
    *,
    date_from: date,
    date_to: date,
    season_min: int | None,
    season_max: int | None,
    finished_only: bool,
) -> tuple[dict[int, ScheduleGameStub], date | None, bool] | None:
    """Загрузить прогресс.

    Returns:
        ``(by_id, resume_anchor, schedule_complete)`` или ``None`` если файла нет / конфликт.
        При ``schedule_complete=True`` второй элемент безразличен (сеть расписания не нужна).

    Note:
        ``date_to`` в файле — снимок на момент сохранения. Если в конфиге указан более поздний
        конец интервала (типично ``date_to: null`` → «сегодня»), прогресс **принимается**:
        дальнейший сбор продолжится по сетке якорей до нового ``date_to``. Если конец интервала
        **раньше**, чем в файле (сужение диапазона), файл отбрасывается.
    """
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("NHL schedule: повреждён прогресс %s (%s), начинаю заново", path, e)
        return None
    if raw.get("version") != _SCHEDULE_PROGRESS_VERSION:
        logger.warning("NHL schedule: неверная версия прогресса %s, начинаю заново", path)
        return None
    if (
        raw.get("date_from") != date_from.isoformat()
        or raw.get("finished_only") != finished_only
        or raw.get("season_min") != season_min
        or raw.get("season_max") != season_max
    ):
        logger.warning(
            "NHL schedule: параметры конфига изменились, файл прогресса %s игнорирую",
            path,
        )
        return None

    saved_end = _saved_date_to_from_progress(raw)
    if saved_end is None:
        logger.warning("NHL schedule: в прогрессе %s нет корректного date_to, начинаю заново", path)
        return None
    if date_to < saved_end:
        logger.warning(
            "NHL schedule: date_to в конфиге %s раньше сохранённого %s — прогресс %s игнорирую",
            date_to.isoformat(),
            saved_end.isoformat(),
            path,
        )
        return None
    by_id: dict[int, ScheduleGameStub] = {}
    games = raw.get("games") or {}
    if isinstance(games, dict):
        for gid_str, st in games.items():
            try:
                gid = int(gid_str)
            except (TypeError, ValueError):
                continue
            if isinstance(st, dict):
                try:
                    by_id[gid] = stub_from_dict(st)
                except (KeyError, TypeError, ValueError):
                    continue

    if date_to > saved_end:
        logger.info(
            "NHL schedule: конец интервала расширен %s → %s (%d матчей в прогрессе); продолжаю сбор",
            saved_end.isoformat(),
            date_to.isoformat(),
            len(by_id),
        )

    schedule_complete = bool(raw.get("schedule_complete"))
    extending_after_complete = schedule_complete and date_to > saved_end

    if schedule_complete and not extending_after_complete:
        logger.info(
            "NHL schedule: использую сохранённый полный снимок расписания (%d матчей), без HTTP",
            len(by_id),
        )
        return by_id, None, True

    try:
        next_anchor = date.fromisoformat(str(raw["next_anchor"]))
    except (KeyError, ValueError):
        if extending_after_complete:
            logger.warning(
                "NHL schedule: в прогрессе %s нет next_anchor для дозагрузки после расширения date_to",
                path,
            )
        return None
    resume = _align_resume_to_week_grid(date_from, next_anchor, date_to)
    if extending_after_complete:
        logger.info(
            "NHL schedule: дозагрузка новых якорей расписания после расширения date_to, resume с %s",
            resume.isoformat(),
        )
    return by_id, resume, False


def clear_schedule_progress(path: Path) -> None:
    """Удалить файл прогресса после успешного завершения сбора расписания."""
    try:
        path.unlink(missing_ok=True)
    except OSError as e:
        logger.debug("NHL schedule: не удалось удалить прогресс %s: %s", path, e)


def _local_default(node: Any) -> str | None:
    if node is None:
        return None
    if isinstance(node, str):
        return node
    if isinstance(node, dict) and "default" in node:
        v = node["default"]
        return str(v) if v is not None else None
    return str(node)


def _parse_game(
    g: dict[str, Any],
    fallback_game_date: str | None = None,
) -> ScheduleGameStub | None:
    gid = g.get("id")
    if gid is None:
        return None
    season = g.get("season")
    if season is None:
        return None
    gt = g.get("gameType")
    if gt is None:
        return None
    gdate = g.get("gameDate") or fallback_game_date
    st = g.get("startTimeUTC")
    if not gdate and isinstance(st, str) and len(st) >= 10:
        gdate = st[:10]
    if not gdate:
        return None
    if not st:
        return None
    venue = g.get("venue") or {}
    ht = g.get("homeTeam") or {}
    at = g.get("awayTeam") or {}
    ha = _local_default(ht.get("abbrev"))
    aa = _local_default(at.get("abbrev"))
    if not ha or not aa:
        return None
    outcome = g.get("gameOutcome") or {}
    last_pt = outcome.get("lastPeriodType")
    match_end = str(last_pt) if last_pt else None
    hscore = ht.get("score")
    ascore = at.get("score")
    return ScheduleGameStub(
        game_id=int(gid),
        season=int(season),
        game_type=int(gt),
        game_date=str(gdate),
        start_time_utc=str(st),
        venue_default=_local_default(venue) or "",
        home_abbrev=str(ha),
        away_abbrev=str(aa),
        game_state=str(g.get("gameState") or ""),
        match_end=match_end,
        home_score=int(hscore) if hscore is not None else None,
        away_score=int(ascore) if ascore is not None else None,
    )


def iter_week_starts(d0: date, d1: date) -> Iterator[date]:
    """Даты-якоря с шагом 7 дней от ``d0`` до ``d1`` включительно.

    Args:
        d0: Первая дата недельного окна API.
        d1: Последняя дата (включительно).

    Yields:
        Календарные даты для вызова :func:`fetch_schedule_day`.
    """
    cur = d0
    while cur <= d1:
        yield cur
        cur += timedelta(days=7)


def fetch_schedule_day(client: NhlApiClient, day: date) -> list[ScheduleGameStub]:
    """Запросить ``schedule/{day}`` и распарсить все матчи из ``gameWeek``.

    Args:
        client: Клиент NHL API.
        day: Дата якоря в формате календаря Python.

    Returns:
        Список :class:`ScheduleGameStub` (без дедупликации между якорями).
    """
    path = f"schedule/{day.isoformat()}"
    payload = client.get_json(path)
    out: list[ScheduleGameStub] = []
    for week in payload.get("gameWeek") or []:
        wk_date = week.get("date") if isinstance(week, dict) else None
        wk_date_s = str(wk_date) if wk_date else None
        for g in week.get("games") or []:
            if not isinstance(g, dict):
                continue
            stub = _parse_game(g, fallback_game_date=wk_date_s)
            if stub is not None:
                out.append(stub)
    return out


def collect_games_for_range(
    client: NhlApiClient,
    date_from: date,
    date_to: date,
    season_min: int | None,
    season_max: int | None,
    finished_only: bool = True,
    progress_path: Path | None = None,
) -> dict[int, ScheduleGameStub]:
    """Собрать уникальные матчи за интервал дат (недельные запросы).

    Args:
        client: NHL API клиент.
        date_from: Начало интервала (включительно).
        date_to: Конец интервала (включительно).
        season_min: Нижняя граница поля season (8-значный SEASON_ID); None — без фильтра.
        season_max: Верхняя граница season; None — без фильтра.
        finished_only: Если True — только ``gameState == OFF``.
        progress_path: Если задан, после каждого успешного якоря пишется JSON с индексом
            матчей и ``next_anchor``; при следующем запуске с теми же параметрами сбор
            продолжается с этого якоря (обрыв на этапе расписания не теряет уже собранное).

    Returns:
        Словарь ``game_id -> stub``.

    Note:
        На уровне INFO логируется старт, каждый недельный якорь и итоговое число
        уникальных матчей после фильтров. После полного прохода в ``progress_path``
        сохраняется снимок с ``schedule_complete=True`` (его удаляет оркестратор
        после успешной записи ``source.csv``).
    """
    by_id: dict[int, ScheduleGameStub] = {}
    resume_from: date | None = None
    if progress_path is not None:
        loaded = load_schedule_progress(
            progress_path,
            date_from=date_from,
            date_to=date_to,
            season_min=season_min,
            season_max=season_max,
            finished_only=finished_only,
        )
        if loaded is not None:
            by_id, resume_from, completed = loaded
            if completed:
                return by_id
            if resume_from is not None:
                logger.info(
                    "NHL schedule: возобновление с якоря >= %s, уже в индексе матчей: %d (файл %s)",
                    resume_from.isoformat(),
                    len(by_id),
                    progress_path,
                )

    anchors = list(iter_week_starts(date_from, date_to))
    logger.info(
        "NHL schedule: сбор с %s по %s, недельных якорей: %d, finished_only=%s, "
        "season_id in [%s, %s]",
        date_from.isoformat(),
        date_to.isoformat(),
        len(anchors),
        finished_only,
        season_min if season_min is not None else "—",
        season_max if season_max is not None else "—",
    )
    for anchor in anchors:
        if resume_from is not None and anchor < resume_from:
            continue
        batch = fetch_schedule_day(client, anchor)
        before = len(by_id)
        for stub in batch:
            if season_min is not None and stub.season < season_min:
                continue
            if season_max is not None and stub.season > season_max:
                continue
            if finished_only and stub.game_state != "OFF":
                continue
            by_id[stub.game_id] = stub
        added = len(by_id) - before
        logger.info(
            "NHL schedule: якорь %s, матчей в ответе: %d, новых после фильтров: %d, "
            "всего уникальных: %d",
            anchor.isoformat(),
            len(batch),
            added,
            len(by_id),
        )
        if progress_path is not None:
            next_anchor = anchor + timedelta(days=7)
            save_schedule_progress(
                progress_path,
                by_id=by_id,
                next_anchor=next_anchor,
                date_from=date_from,
                date_to=date_to,
                season_min=season_min,
                season_max=season_max,
                finished_only=finished_only,
                schedule_complete=False,
            )
            logger.debug("NHL schedule: сохранён прогресс, next_anchor=%s", next_anchor.isoformat())

    if progress_path is not None:
        save_schedule_progress(
            progress_path,
            by_id=by_id,
            next_anchor=date_to + timedelta(days=7),
            date_from=date_from,
            date_to=date_to,
            season_min=season_min,
            season_max=season_max,
            finished_only=finished_only,
            schedule_complete=True,
        )
        logger.info(
            "NHL schedule: этап расписания завершён, снимок сохранён (%s), уникальных матчей: %d",
            progress_path,
            len(by_id),
        )

    logger.info("NHL schedule: готово, уникальных матчей: %d", len(by_id))
    return by_id
