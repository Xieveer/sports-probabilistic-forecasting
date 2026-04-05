"""Сборка таблицы матчей NHL для ``source.csv``: расписание, boxscore, standings, ростеры."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from omegaconf import DictConfig, OmegaConf

from sports_forecast.data.providers.base import SourceFetchError
from sports_forecast.data.providers.nhl.boxscore import build_team_stats, load_boxscore_and_pbp
from sports_forecast.data.providers.nhl.client import NhlApiClient
from sports_forecast.data.providers.nhl.roster import roster_to_json_cell
from sports_forecast.data.providers.nhl.schedule import collect_games_for_range
from sports_forecast.data.providers.nhl.standings import StandingRow, fetch_standings_for_date
from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)


_GAME_TYPE_LABEL = {1: "preseason", 2: "regular", 3: "playoffs"}


@dataclass
class AssemblerConfig:
    """Параметры длительной загрузки, совпадающие с полями ``provider`` в ``conf/source/nhl.yaml``."""

    date_from: date
    date_to: date
    season_id_min: int | None
    season_id_max: int | None
    max_games: int | None
    include_play_by_play: bool
    finished_only: bool
    roster_enabled: bool
    checkpoint_file: str | None
    progress_log_every: int


def _parse_ymd(s: str) -> date:
    return date.fromisoformat(s.strip())


def _cfg_date(cfg: dict[str, Any], key: str, default: date) -> date:
    raw = cfg.get(key)
    if raw is None or raw == "":
        return default
    if isinstance(raw, datetime):
        return raw.date()
    return _parse_ymd(str(raw))


def load_assembler_config(provider_cfg: DictConfig) -> AssemblerConfig:
    """Построить :class:`AssemblerConfig` из ветки ``provider`` source-конфига.

    Args:
        provider_cfg: Объект OmegaConf с полями провайдера (даты, лимиты, флаги).

    Returns:
        Нормализованная конфигурация сборщика.

    Raises:
        SourceFetchError: Некорректная структура или ``date_to < date_from``.
    """
    c = OmegaConf.to_container(provider_cfg, resolve=True)
    if not isinstance(c, dict):
        raise SourceFetchError("nhl_web_api: provider должен быть объектом")
    today = datetime.now(timezone.utc).date()
    d0 = _cfg_date(c, "date_from", date(1999, 9, 1))
    d1 = _cfg_date(c, "date_to", today)
    if d1 < d0:
        raise SourceFetchError("nhl_web_api: date_to < date_from")

    smin = c.get("season_id_min")
    smax = c.get("season_id_max")
    max_g = c.get("max_games")

    ck = c.get("checkpoint_file")
    raw_every = c.get("progress_log_every", 25)
    try:
        progress_every = max(0, int(raw_every))
    except (TypeError, ValueError):
        progress_every = 25

    return AssemblerConfig(
        date_from=d0,
        date_to=d1,
        season_id_min=int(smin) if smin is not None else None,
        season_id_max=int(smax) if smax is not None else None,
        max_games=int(max_g) if max_g is not None else None,
        include_play_by_play=bool(c.get("include_play_by_play", True)),
        finished_only=bool(c.get("finished_only", True)),
        roster_enabled=bool(c.get("roster_enabled", True)),
        checkpoint_file=str(ck).strip() if ck else None,
        progress_log_every=progress_every,
    )


def _read_checkpoint(path: Path) -> set[int]:
    if not path.exists():
        return set()
    ids: set[int] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ids.add(int(line))
        except ValueError:
            continue
    return ids


def _append_checkpoint(path: Path, game_id: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(f"{game_id}\n")


def _fmt_int(v: int | None) -> str:
    if v is None:
        return ""
    return str(v)


def _standings_triplet(idx: dict[str, StandingRow], abbr: str) -> tuple[str, str, str]:
    row = idx.get(abbr)
    if row is None:
        return "", "", ""
    return str(row.conference_rank), str(row.points), str(row.games_played)


class NhlDataAssembler:
    """Оркестрация HTTP-запросов и сборка одного DataFrame для записи в CSV."""

    def __init__(self, client: NhlApiClient, cfg: AssemblerConfig) -> None:
        """
        Args:
            client: Уже настроенный :class:`~sports_forecast.data.providers.nhl.client.NhlApiClient`.
            cfg: Параметры интервала и поведения сборки.
        """
        self._client = client
        self._cfg = cfg

    def build_dataframe(self, checkpoint_base: Path | None = None) -> pd.DataFrame:
        """Собрать строки матчей: расписание → boxscore/PBP → standings → при необходимости roster.

        Args:
            checkpoint_base: Каталог ``data/source/<name>`` для файла checkpoint (если задан в конфиге).

        Returns:
            Таблица в колонках, согласованных с ``docs/cursor/source_data/nhl.md`` и downstream clean.

        Note:
            Прогресс пишется в лог: этап расписания (в :func:`collect_games_for_range`),
            затем каждые ``progress_log_every`` обогащённых матчей (0 — без промежуточных INFO).
        """
        games = collect_games_for_range(
            self._client,
            self._cfg.date_from,
            self._cfg.date_to,
            self._cfg.season_id_min,
            self._cfg.season_id_max,
            finished_only=self._cfg.finished_only,
        )
        stubs = list(games.values())
        stubs.sort(key=lambda s: (s.game_date, s.start_time_utc, s.game_id))

        ck_path: Path | None = None
        done: set[int] = set()
        if checkpoint_base is not None and self._cfg.checkpoint_file:
            ck_path = checkpoint_base / self._cfg.checkpoint_file
            done = _read_checkpoint(ck_path)

        pending = [s for s in stubs if s.game_id not in done]
        skipped_checkpoint = sum(1 for s in stubs if s.game_id in done)
        if self._cfg.max_games is not None:
            pending = pending[: self._cfg.max_games]

        logger.info(
            "NHL assemble: к обогащению %d матчей (в расписании: %d, пропущено по checkpoint: %d, "
            "include_play_by_play=%s, roster_enabled=%s, max_games=%s)",
            len(pending),
            len(stubs),
            skipped_checkpoint,
            self._cfg.include_play_by_play,
            self._cfg.roster_enabled,
            self._cfg.max_games if self._cfg.max_games is not None else "—",
        )

        rows: list[dict[str, Any]] = []
        standings_cache: dict[str, dict[str, StandingRow]] = {}
        roster_cache: dict[tuple[str, int], str] = {}

        total_work = len(pending)
        for idx, stub in enumerate(pending, start=1):
            if stub.game_date not in standings_cache:
                logger.debug("NHL assemble: загрузка standings на дату %s", stub.game_date)
                standings_cache[stub.game_date] = fetch_standings_for_date(
                    self._client, stub.game_date
                )

            st_idx = standings_cache[stub.game_date]
            try:
                box, pbp = load_boxscore_and_pbp(
                    self._client,
                    stub.game_id,
                    with_pbp=self._cfg.include_play_by_play,
                )
            except SourceFetchError:
                logger.warning("NHL: пропуск game_id=%s (boxscore/pbp)", stub.game_id)
                continue

            pbp_used = pbp is not None
            zh, za, _hid, _aid = build_team_stats(box, pbp)

            outcome = box.get("gameOutcome") or {}
            last_pt = outcome.get("lastPeriodType")
            match_end = str(last_pt) if last_pt else (stub.match_end or "")

            venue = box.get("venue") or {}
            venue_d = venue.get("default") if isinstance(venue, dict) else venue
            location = str(venue_d) if venue_d else stub.venue_default

            hs, hp, hgp = _standings_triplet(st_idx, stub.home_abbrev)
            aws, ap, agp = _standings_triplet(st_idx, stub.away_abbrev)

            home_roster = ""
            away_roster = ""
            if self._cfg.roster_enabled:
                key_h = (stub.home_abbrev, stub.season)
                key_a = (stub.away_abbrev, stub.season)
                if key_h not in roster_cache:
                    try:
                        roster_cache[key_h] = roster_to_json_cell(
                            self._client, stub.home_abbrev, stub.season
                        )
                    except SourceFetchError:
                        roster_cache[key_h] = "{}"
                if key_a not in roster_cache:
                    try:
                        roster_cache[key_a] = roster_to_json_cell(
                            self._client, stub.away_abbrev, stub.season
                        )
                    except SourceFetchError:
                        roster_cache[key_a] = "{}"
                home_roster = roster_cache[key_h]
                away_roster = roster_cache[key_a]

            row = {
                "id": str(stub.game_id),
                "nhl_id": str(stub.game_id),
                "season": str(stub.season),
                "game_type": _GAME_TYPE_LABEL.get(stub.game_type, str(stub.game_type)),
                "datetime": stub.start_time_utc,
                "location": location,
                "home_team": stub.home_abbrev,
                "away_team": stub.away_abbrev,
                "match_end": match_end,
                "home_score_ft": _fmt_int(zh.score_ft),
                "away_score_ft": _fmt_int(za.score_ft),
                "home_score_mt": _fmt_int(zh.score_mt) if pbp_used else "",
                "away_score_mt": _fmt_int(za.score_mt) if pbp_used else "",
                "home_sog_ft": _fmt_int(zh.sog_ft),
                "away_sog_ft": _fmt_int(za.sog_ft),
                "home_sog_mt": _fmt_int(zh.sog_mt) if pbp_used else "",
                "away_sog_mt": _fmt_int(za.sog_mt) if pbp_used else "",
                "home_bs_ft": _fmt_int(zh.bs_ft),
                "away_bs_ft": _fmt_int(za.bs_ft),
                "home_bs_mt": _fmt_int(zh.bs_mt) if pbp_used else "",
                "away_bs_mt": _fmt_int(za.bs_mt) if pbp_used else "",
                "home_hits_ft": _fmt_int(zh.hits_ft),
                "away_hits_ft": _fmt_int(za.hits_ft),
                "home_hits_mt": _fmt_int(zh.hits_mt) if pbp_used else "",
                "away_hits_mt": _fmt_int(za.hits_mt) if pbp_used else "",
                "home_pim_ft": _fmt_int(zh.pim_ft),
                "away_pim_ft": _fmt_int(za.pim_ft),
                "home_pim_mt": _fmt_int(zh.pim_mt) if pbp_used else "",
                "away_pim_mt": _fmt_int(za.pim_mt) if pbp_used else "",
                "home_2pim_ft": _fmt_int(zh.pim2_ft) if pbp_used else "",
                "away_2pim_ft": _fmt_int(za.pim2_ft) if pbp_used else "",
                "home_2pim_mt": _fmt_int(zh.pim2_mt) if pbp_used else "",
                "away_2pim_mt": _fmt_int(za.pim2_mt) if pbp_used else "",
                "home_fow_ft": _fmt_int(zh.fow_ft) if pbp_used else "",
                "away_fow_ft": _fmt_int(za.fow_ft) if pbp_used else "",
                "home_fow_mt": _fmt_int(zh.fow_mt) if pbp_used else "",
                "away_fow_mt": _fmt_int(za.fow_mt) if pbp_used else "",
                "home_roster": home_roster,
                "away_roster": away_roster,
                "home_conference_standing": hs,
                "home_P": hp,
                "home_GP": hgp,
                "away_conference_standing": aws,
                "away_P": ap,
                "away_GP": agp,
                "match_is_end": "1",
            }
            rows.append(row)
            if ck_path is not None:
                _append_checkpoint(ck_path, stub.game_id)

            every = self._cfg.progress_log_every
            if every > 0 and (idx % every == 0 or idx == total_work):
                logger.info(
                    "NHL assemble: обработано %d/%d, game_id=%s %s @ %s (%s)",
                    idx,
                    total_work,
                    stub.game_id,
                    stub.away_abbrev,
                    stub.home_abbrev,
                    stub.game_date,
                )

        if not rows:
            logger.warning("NHL assemble: нет строк (проверьте интервал дат и фильтры)")
        else:
            logger.info("NHL assemble: готово, строк в таблице: %d", len(rows))
        return pd.DataFrame(rows)
