"""Загрузка карточки матча и play-by-play; агрегаты по командам (полный матч и три периода регламента)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sports_forecast.data.providers.nhl.client import NhlApiClient


@dataclass
class TeamGameStats:
    """Числовые метрики одной стороны после агрегации boxscore/PBP.

    Поля ``*_mt`` относятся к периодам 1–3 регулярного времени; ``score_ft`` и
    официальные ``sog_ft`` задаются из boxscore в :func:`build_team_stats`.
    """

    score_ft: int | None
    score_mt: int | None
    sog_ft: int | None
    sog_mt: int | None
    bs_ft: int
    bs_mt: int
    hits_ft: int
    hits_mt: int
    pim_ft: int
    pim_mt: int
    pim2_ft: int
    pim2_mt: int
    fow_ft: int
    fow_mt: int


def _period_is_regulation_first_three(pd: dict[str, Any] | None) -> bool:
    if not pd:
        return False
    try:
        num = int(pd.get("number", 0))
    except (TypeError, ValueError):
        return False
    return pd.get("periodType") == "REG" and 1 <= num <= 3


def _skater_lists(side: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for key in ("forwards", "defense"):
        for row in side.get(key) or []:
            if isinstance(row, dict):
                out.append(row)
    return out


def _sum_skater_int(rows: list[dict[str, Any]], field: str) -> int:
    s = 0
    for r in rows:
        v = r.get(field)
        if isinstance(v, bool):
            continue
        if v is None:
            continue
        try:
            s += int(v)
        except (TypeError, ValueError):
            try:
                s += int(float(v))
            except (TypeError, ValueError):
                continue
    return s


def aggregate_player_box_stats(box: dict[str, Any]) -> tuple[int, int, int, int]:
    """Суммировать блоки и хиты скейтеров из ``playerByGameStats`` (fallback без PBP).

    Args:
        box: Тело ответа ``gamecenter/.../boxscore``.

    Returns:
        Кортеж ``(home_bs, away_bs, home_hits, away_hits)``.
    """
    pstats = box.get("playerByGameStats") or {}
    at = pstats.get("awayTeam") or {}
    ht = pstats.get("homeTeam") or {}
    away_sk = _skater_lists(at)
    home_sk = _skater_lists(ht)
    return (
        _sum_skater_int(home_sk, "blockedShots"),
        _sum_skater_int(away_sk, "blockedShots"),
        _sum_skater_int(home_sk, "hits"),
        _sum_skater_int(away_sk, "hits"),
    )


def _team_skater_pim_totals(box: dict[str, Any]) -> tuple[int, int]:
    """Официальные PIM по сумме игроков карточки (дом / гость)."""
    pstats = box.get("playerByGameStats") or {}
    at = pstats.get("awayTeam") or {}
    ht = pstats.get("homeTeam") or {}
    home_sk = _skater_lists(ht)
    away_sk = _skater_lists(at)
    hg = ht.get("goalies") if isinstance(ht, dict) else []
    ag = at.get("goalies") if isinstance(at, dict) else []
    home_g = _sum_skater_int([x for x in hg if isinstance(x, dict)], "pim")
    away_g = _sum_skater_int([x for x in ag if isinstance(x, dict)], "pim")
    return _sum_skater_int(home_sk, "pim") + home_g, _sum_skater_int(away_sk, "pim") + away_g


def extract_scores_and_sog(
    box: dict[str, Any],
) -> tuple[int | None, int | None, int | None, int | None]:
    """Извлечь финальные голы и броски в створ команд из boxscore.

    Args:
        box: Ответ ``.../boxscore``.

    Returns:
        ``(home_score, away_score, home_sog, away_sog)``.
    """
    ht = box.get("homeTeam") or {}
    at = box.get("awayTeam") or {}

    def _si(d: dict[str, Any], k: str) -> int | None:
        v = d.get(k)
        if v is None:
            return None
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    return (
        _si(ht, "score"),
        _si(at, "score"),
        _si(ht, "sog"),
        _si(at, "sog"),
    )


def aggregate_play_by_play(
    pbp: dict[str, Any],
    home_id: int,
    away_id: int,
) -> tuple[TeamGameStats, TeamGameStats]:
    """Агрегировать события play-by-play в счётчиках по сторонам.

    Args:
        pbp: Ответ ``.../play-by-play`` с массивом ``plays``.
        home_id: Числовой ``homeTeam.id`` из того же матча.
        away_id: Числовой ``awayTeam.id``.

    Returns:
        Пара ``(home_agg, away_agg)``. Поля PIM здесь отражают события штрафов;
        в :func:`build_team_stats` итоговые ``pim_ft`` перезаписываются суммой
        по карточке матча (протокол).
    """
    z_h = TeamGameStats(
        score_ft=None,
        score_mt=0,
        sog_ft=0,
        sog_mt=0,
        bs_ft=0,
        bs_mt=0,
        hits_ft=0,
        hits_mt=0,
        pim_ft=0,
        pim_mt=0,
        pim2_ft=0,
        pim2_mt=0,
        fow_ft=0,
        fow_mt=0,
    )
    z_a = TeamGameStats(
        score_ft=None,
        score_mt=0,
        sog_ft=0,
        sog_mt=0,
        bs_ft=0,
        bs_mt=0,
        hits_ft=0,
        hits_mt=0,
        pim_ft=0,
        pim_mt=0,
        pim2_ft=0,
        pim2_mt=0,
        fow_ft=0,
        fow_mt=0,
    )

    def _add_penalty(target: TeamGameStats, dur: int, is2: bool, reg3: bool) -> None:
        target.pim_ft += dur
        if is2:
            target.pim2_ft += dur
        if reg3:
            target.pim_mt += dur
            if is2:
                target.pim2_mt += dur

    plays = pbp.get("plays") or []
    for ev in plays:
        if not isinstance(ev, dict):
            continue
        desc = ev.get("typeDescKey")
        pd = ev.get("periodDescriptor")
        reg3 = _period_is_regulation_first_three(pd if isinstance(pd, dict) else None)
        in_game = True  # все периоды матча включая OT/SO

        details = ev.get("details")
        det = details if isinstance(details, dict) else {}

        tid_raw = det.get("eventOwnerTeamId")
        try:
            tid = int(tid_raw) if tid_raw is not None else None
        except (TypeError, ValueError):
            tid = None
        if tid is None:
            continue

        if tid == home_id:
            th = z_h
        elif tid == away_id:
            th = z_a
        else:
            continue

        if desc == "shot-on-goal" and in_game:
            th.sog_ft += 1
            if reg3:
                th.sog_mt += 1
        elif desc == "blocked-shot" and in_game:
            th.bs_ft += 1
            if reg3:
                th.bs_mt += 1
        elif desc == "hit" and in_game:
            th.hits_ft += 1
            if reg3:
                th.hits_mt += 1
        elif desc == "faceoff" and in_game:
            th.fow_ft += 1
            if reg3:
                th.fow_mt += 1
        elif desc == "goal" and in_game:
            if reg3:
                th.score_mt += 1
        elif desc == "penalty" and in_game:
            dur_raw = det.get("duration")
            try:
                dur = int(dur_raw) if dur_raw is not None else 0
            except (TypeError, ValueError):
                dur = 0
            typ = det.get("typeCode")
            # 2-мин миноры и 2+2: NHL использует typeCode MIN; длительность 2 или 4
            is2 = typ == "MIN" and dur in (2, 4)
            _add_penalty(th, dur, is2, reg3)

    return z_h, z_a


def load_boxscore_and_pbp(
    client: NhlApiClient,
    game_id: int,
    with_pbp: bool,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Загрузить boxscore и при необходимости play-by-play для ``game_id``.

    Args:
        client: Клиент NHL API.
        game_id: Идентификатор матча NHL.
        with_pbp: Выполнить второй запрос ``play-by-play``.

    Returns:
        ``(boxscore_dict, pbp_dict | None)``.

    Raises:
        sports_forecast.data.providers.base.SourceFetchError: Прокидывается из клиента при ошибке HTTP/сети.
    """
    box = client.get_json(f"gamecenter/{game_id}/boxscore")
    pbp: dict[str, Any] | None = None
    if with_pbp:
        pbp = client.get_json(f"gamecenter/{game_id}/play-by-play")
    return box, pbp


def build_team_stats(
    box: dict[str, Any],
    pbp: dict[str, Any] | None,
) -> tuple[TeamGameStats, TeamGameStats, int, int]:
    """Объединить boxscore и опционально PBP в итоговые метрики обеих команд.

    Args:
        box: Ответ ``gamecenter/{id}/boxscore``.
        pbp: Ответ play-by-play или ``None`` (часть MT-метрик и событийных BS/hits берётся из fallback).

    Returns:
        ``(home_stats, away_stats, home_team_id, away_team_id)``.
    """
    ht = box.get("homeTeam") or {}
    at = box.get("awayTeam") or {}
    home_id = int(ht["id"])
    away_id = int(at["id"])

    hs, as_, h_sog_ft, a_sog_ft = extract_scores_and_sog(box)
    home_sk_bs, away_sk_bs, home_sk_hits, away_sk_hits = aggregate_player_box_stats(box)
    home_sk_pim, away_sk_pim = _team_skater_pim_totals(box)

    zh = TeamGameStats(
        score_ft=hs,
        score_mt=0,
        sog_ft=0,
        sog_mt=0,
        bs_ft=0,
        bs_mt=0,
        hits_ft=0,
        hits_mt=0,
        pim_ft=0,
        pim_mt=0,
        pim2_ft=0,
        pim2_mt=0,
        fow_ft=0,
        fow_mt=0,
    )
    za = TeamGameStats(
        score_ft=as_,
        score_mt=0,
        sog_ft=0,
        sog_mt=0,
        bs_ft=0,
        bs_mt=0,
        hits_ft=0,
        hits_mt=0,
        pim_ft=0,
        pim_mt=0,
        pim2_ft=0,
        pim2_mt=0,
        fow_ft=0,
        fow_mt=0,
    )

    if pbp:
        ph, pa = aggregate_play_by_play(pbp, home_id, away_id)
        for dest, src in ((zh, ph), (za, pa)):
            dest.score_mt = src.score_mt
            dest.sog_mt = src.sog_mt
            dest.bs_ft = src.bs_ft
            dest.bs_mt = src.bs_mt
            dest.hits_ft = src.hits_ft
            dest.hits_mt = src.hits_mt
            dest.pim_ft = src.pim_ft
            dest.pim_mt = src.pim_mt
            dest.pim2_ft = src.pim2_ft
            dest.pim2_mt = src.pim2_mt
            dest.fow_ft = src.fow_ft
            dest.fow_mt = src.fow_mt

    # Официальные SOG за матч из boxscore; sog_mt — только из PBP (регулярные периоды)
    if h_sog_ft is not None:
        zh.sog_ft = h_sog_ft
    if a_sog_ft is not None:
        za.sog_ft = a_sog_ft

    # Fallback без PBP: блоки/хиты из суммы скейтеров boxscore
    if pbp is None:
        zh.bs_ft, za.bs_ft = home_sk_bs, away_sk_bs
        zh.bs_mt, za.bs_mt = 0, 0
        zh.hits_ft, za.hits_ft = home_sk_hits, away_sk_hits
        zh.hits_mt, za.hits_mt = 0, 0

    # Официальные полные PIM матча — сумма по карточке матча (как в протоколе)
    zh.pim_ft, za.pim_ft = home_sk_pim, away_sk_pim

    return zh, za, home_id, away_id
