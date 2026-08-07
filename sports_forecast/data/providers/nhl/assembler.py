"""Сборка таблицы матчей NHL для ``source.csv``: расписание, boxscore, standings, ростеры."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pandas as pd
from omegaconf import DictConfig, OmegaConf

from sports_forecast.data.providers.base import SourceFetchError
from sports_forecast.data.providers.nhl.boxscore import build_team_stats, load_boxscore_and_pbp
from sports_forecast.data.providers.nhl.client import NhlApiClient
from sports_forecast.data.providers.nhl.roster import roster_to_json_cell
from sports_forecast.data.providers.nhl.schedule import ScheduleGameStub, collect_games_for_range
from sports_forecast.data.providers.nhl.standings import (
    StandingRow,
    fetch_standings_for_date,
    standings_snapshot_ymd_before_game_date,
)
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
    schedule_progress_file: str | None
    csv_flush_every: int
    incremental: bool
    incremental_buffer_days: int


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
    today = datetime.now(UTC).date()
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

    sp = c.get("schedule_progress_file")
    raw_flush = c.get("csv_flush_every", 50)
    try:
        csv_flush = max(0, int(raw_flush))
    except (TypeError, ValueError):
        csv_flush = 50

    raw_buf = c.get("incremental_buffer_days", 3)
    try:
        buf_days = max(0, int(raw_buf))
    except (TypeError, ValueError):
        buf_days = 3

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
        schedule_progress_file=str(sp).strip() if sp else None,
        csv_flush_every=csv_flush,
        incremental=bool(c.get("incremental", False)),
        incremental_buffer_days=buf_days,
    )


def last_finished_match_date_from_source_csv(csv_path: Path) -> date | None:
    """Найти календарную дату последнего завершённого матча в ``source.csv``.

    Используется для инкрементального refresh: перекрытие на несколько дней назад
    позволяет подтянуть исправления boxscore в недавнем окне.

    Args:
        csv_path: Путь к существующему ``source.csv``.

    Returns:
        Дата (UTC-календарь) последнего матча с ``match_is_end`` = завершён, либо ``None``.
    """
    if not csv_path.is_file():
        return None
    try:
        df = pd.read_csv(
            csv_path,
            usecols=["datetime", "match_is_end"],
            dtype=str,
            low_memory=False,
        )
    except ValueError:
        df = pd.read_csv(csv_path, dtype=str, low_memory=False)
    if df.empty or "datetime" not in df.columns:
        return None
    if "match_is_end" in df.columns:
        fin = df["match_is_end"].astype(str).str.strip().isin(["1", "True", "true"])
        sub = df.loc[fin, "datetime"]
    else:
        sub = df["datetime"]
    if sub.empty:
        return None
    parsed = pd.to_datetime(sub, errors="coerce", utc=True)
    parsed = parsed.dropna()
    if parsed.empty:
        return None
    last = parsed.max()
    return last.date()


def resolve_incremental_date_from(
    base_cfg: AssemblerConfig,
    source_csv_path: Path,
) -> AssemblerConfig:
    """Сузить ``date_from`` для инкрементального режима по хвосту ``source.csv``.

    Args:
        base_cfg: Конфигурация из YAML (полный прогон при ``incremental=False``).
        source_csv_path: Путь к ``source.csv`` турнира.

    Returns:
        Новая конфигурация с подправленным ``date_from`` или копия ``base_cfg``.
    """
    if not base_cfg.incremental:
        return base_cfg
    last_d = last_finished_match_date_from_source_csv(source_csv_path)
    if last_d is None:
        logger.info(
            "NHL incremental: нет завершённых матчей в %s — полный интервал с %s",
            source_csv_path,
            base_cfg.date_from,
        )
        return base_cfg
    buffered = last_d - timedelta(days=base_cfg.incremental_buffer_days)
    new_from = max(buffered, base_cfg.date_from)
    if new_from != base_cfg.date_from:
        logger.info(
            "NHL incremental: date_from %s → %s (последний finished %s, буфер %d дн.)",
            base_cfg.date_from.isoformat(),
            new_from.isoformat(),
            last_d.isoformat(),
            base_cfg.incremental_buffer_days,
        )
    return AssemblerConfig(
        date_from=new_from,
        date_to=base_cfg.date_to,
        season_id_min=base_cfg.season_id_min,
        season_id_max=base_cfg.season_id_max,
        max_games=base_cfg.max_games,
        include_play_by_play=base_cfg.include_play_by_play,
        finished_only=base_cfg.finished_only,
        roster_enabled=base_cfg.roster_enabled,
        checkpoint_file=base_cfg.checkpoint_file,
        progress_log_every=base_cfg.progress_log_every,
        schedule_progress_file=base_cfg.schedule_progress_file,
        csv_flush_every=base_cfg.csv_flush_every,
        incremental=base_cfg.incremental,
        incremental_buffer_days=base_cfg.incremental_buffer_days,
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


def _row_is_finished_in_csv(row: dict[str, Any]) -> bool:
    """Согласовано с :func:`sports_forecast.data.clean.infer_match_status_from_scores`."""
    v = row.get("match_is_end")
    return str(v).strip() in ("1", "True", "true")


def _snapshot_csv_rows(
    stubs: list[ScheduleGameStub],
    rows_from_current_pass: list[dict[str, Any]],
    prev_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Собрать полный набор строк для ``source.csv`` при частичном прогоне.

    Промежуточная запись должна соединять уже пересчитанный префикс (``rows_from_current_pass``)
    с **хвостом** из прошлого файла (``prev_by_id``). Иначе ``to_csv`` из первых N строк
    **уничтожает** все матчи, ещё не обработанные в текущем запуске.

    Порядок строк — как в ``stubs`` (сортировка расписания).

    Args:
        stubs: Все матчи интервала в порядке обхода.
        rows_from_current_pass: Строки, собранные в текущем запуске (по одной на обработанный stub).
        prev_by_id: Индекс прошлого CSV по ``id``.

    Returns:
        Список записей на всю длину расписания (или короче, если в ``prev`` не было хвоста).
    """
    by_id_cur = {str(r["id"]): r for r in rows_from_current_pass}
    out: list[dict[str, Any]] = []
    for stub in stubs:
        sid = str(stub.game_id)
        if sid in by_id_cur:
            out.append(by_id_cur[sid])
        elif sid in prev_by_id:
            out.append(prev_by_id[sid])
    return out


def _sort_rows_chronologically(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Упорядочить строки по ``datetime``, затем по ``id`` (устойчиво к пропускам даты)."""
    if len(rows) <= 1:
        return rows
    df = pd.DataFrame(rows)
    if "datetime" in df.columns:
        ts = pd.to_datetime(df["datetime"], errors="coerce", utc=True)
        df = df.assign(_ts=ts)
        sort_cols: list[str] = ["_ts"]
        if "id" in df.columns:
            sort_cols.append("id")
        df = df.sort_values(by=sort_cols, na_position="last")
        df = df.drop(columns=["_ts"])
    elif "id" in df.columns:
        df = df.sort_values(by="id")
    return cast(list[dict[str, Any]], df.to_dict(orient="records"))


def _merge_full_source_snapshot(
    stubs: list[ScheduleGameStub],
    rows_from_current_pass: list[dict[str, Any]],
    prev_by_id: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], int, int]:
    """Собрать полный ``source.csv``: история вне окна + пересчитанное окно расписания.

    Строки с ``id``, попавшими в текущее расписание (``stubs``), заменяются на результат
    текущего прогона (см. :func:`_snapshot_csv_rows`). Остальные ``id`` из прошлого файла
    сохраняются без изменений. Итог сортируется по времени матча.

    Returns:
        ``(combined_rows, n_retained_outside_window, n_rows_in_window)``.
    """
    window = _snapshot_csv_rows(stubs, rows_from_current_pass, prev_by_id)
    stub_ids = {str(s.game_id) for s in stubs}
    retained = [row for sid, row in prev_by_id.items() if sid not in stub_ids]
    n_ret, n_win = len(retained), len(window)
    if not retained:
        return window, 0, n_win
    if not window:
        return _sort_rows_chronologically(retained), n_ret, 0
    return _sort_rows_chronologically(retained + window), n_ret, n_win


def _load_previous_source_rows(csv_path: Path) -> dict[str, dict[str, Any]]:
    """Индекс строк прошлого ``source.csv`` по ``id`` (для checkpoint и смены upcoming→OFF)."""
    if not csv_path.exists():
        return {}
    df = pd.read_csv(csv_path, dtype={"id": str}, low_memory=False)
    out: dict[str, dict[str, Any]] = {}
    for rec in df.to_dict(orient="records"):
        rec_t = cast(dict[str, Any], rec)
        sid = rec_t.get("id")
        if sid is not None and str(sid).strip() != "":
            out[str(sid).strip()] = rec_t
    return out


def _empty_pbp_cell(include_pbp: bool, v: int | str = "") -> str:
    if not include_pbp:
        return ""
    return v if isinstance(v, str) else _fmt_int(v) if v else ""


def _build_upcoming_row(
    stub: ScheduleGameStub,
    *,
    st_idx: dict[str, StandingRow],
    include_pbp: bool,
) -> dict[str, Any]:
    """Строка для матча не в ``OFF`` (предстоящий или live): метаданные и standings, статистика пустая."""
    hs, hp, hgp = _standings_triplet(st_idx, stub.home_abbrev)
    aws, ap, agp = _standings_triplet(st_idx, stub.away_abbrev)
    empty = ""
    return {
        "id": str(stub.game_id),
        "nhl_id": str(stub.game_id),
        "season": str(stub.season),
        "game_type": _GAME_TYPE_LABEL.get(stub.game_type, str(stub.game_type)),
        "datetime": stub.start_time_utc,
        "location": stub.venue_default,
        "home_team": stub.home_abbrev,
        "away_team": stub.away_abbrev,
        "match_end": stub.match_end or "",
        "home_score_ft": empty,
        "away_score_ft": empty,
        "home_score_mt": _empty_pbp_cell(include_pbp, empty),
        "away_score_mt": _empty_pbp_cell(include_pbp, empty),
        "home_sog_ft": empty,
        "away_sog_ft": empty,
        "home_sog_mt": _empty_pbp_cell(include_pbp, empty),
        "away_sog_mt": _empty_pbp_cell(include_pbp, empty),
        "home_bs_ft": empty,
        "away_bs_ft": empty,
        "home_bs_mt": _empty_pbp_cell(include_pbp, empty),
        "away_bs_mt": _empty_pbp_cell(include_pbp, empty),
        "home_hits_ft": empty,
        "away_hits_ft": empty,
        "home_hits_mt": _empty_pbp_cell(include_pbp, empty),
        "away_hits_mt": _empty_pbp_cell(include_pbp, empty),
        "home_pim_ft": empty,
        "away_pim_ft": empty,
        "home_pim_mt": _empty_pbp_cell(include_pbp, empty),
        "away_pim_mt": _empty_pbp_cell(include_pbp, empty),
        "home_2pim_ft": _empty_pbp_cell(include_pbp, empty),
        "away_2pim_ft": _empty_pbp_cell(include_pbp, empty),
        "home_2pim_mt": _empty_pbp_cell(include_pbp, empty),
        "away_2pim_mt": _empty_pbp_cell(include_pbp, empty),
        "home_fow_ft": _empty_pbp_cell(include_pbp, empty),
        "away_fow_ft": _empty_pbp_cell(include_pbp, empty),
        "home_fow_mt": _empty_pbp_cell(include_pbp, empty),
        "away_fow_mt": _empty_pbp_cell(include_pbp, empty),
        "home_roster": empty,
        "away_roster": empty,
        "home_conference_standing": hs,
        "home_P": hp,
        "home_GP": hgp,
        "away_conference_standing": aws,
        "away_P": ap,
        "away_GP": agp,
        "match_is_end": "0",
    }


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
        self._schedule_stubs: tuple[ScheduleGameStub, ...] = ()

    @property
    def schedule_snapshot_rows(self) -> pd.DataFrame:
        """Нормализованные строки последнего успешно собранного расписания.

        В отличие от progress-файла, результат содержит только поля, необходимые
        quality gate, и не переносит исходные ответы NHL API.
        """
        return pd.DataFrame(
            [
                {
                    "id": str(stub.game_id),
                    "datetime": stub.start_time_utc,
                    "game_state": stub.game_state,
                }
                for stub in self._schedule_stubs
            ]
        )

    def build_dataframe(
        self,
        checkpoint_base: Path | None = None,
        output_csv_path: Path | None = None,
    ) -> pd.DataFrame:
        """Собрать строки матчей: расписание → standings; для ``OFF`` — boxscore/PBP и ростеры.

        При ``finished_only=False`` в расписание попадают матчи не в ``OFF``; для них пишется
        строка с пустой статистикой и ``match_is_end=0`` (как у настольного тенниса / ``clean``).

        Чекпоинт и HTTP-обогащение выполняются только для завершённых (``OFF``) матчей; уже
        собранные строки подтягиваются из предыдущего ``output_csv_path`` по ``id``, чтобы
        не терять прогресс внутри одного окна расписания.

        При записи в ``output_csv_path`` результат **объединяется** с матчами **вне** текущего
        интервала расписания: старые строки (не из этого прогона ``stubs``) сохраняются,
        строки по датам окна заменяются/дополняются данными текущего запуска (инкремент без
        затирания всей истории).

        Args:
            checkpoint_base: Каталог ``data/source/<name>`` для checkpoint матчей и прогресса расписания.
            output_csv_path: Если задан, периодически перезаписывается полным снимком (история
                вне окна + окно); финал — то же.

        Returns:
            Таблица в колонках, согласованных с ``docs/cursor/source_data/nhl.md`` и downstream clean.

        Note:
            Прогресс пишется в лог: этап расписания (в :func:`collect_games_for_range`),
            затем каждые ``progress_log_every`` матчей (0 — без промежуточных INFO).
        """
        sched_path: Path | None = None
        if checkpoint_base is not None and self._cfg.schedule_progress_file:
            sched_path = checkpoint_base / self._cfg.schedule_progress_file

        games = collect_games_for_range(
            self._client,
            self._cfg.date_from,
            self._cfg.date_to,
            self._cfg.season_id_min,
            self._cfg.season_id_max,
            finished_only=self._cfg.finished_only,
            progress_path=sched_path,
        )
        stubs = list(games.values())
        stubs.sort(key=lambda s: (s.game_date, s.start_time_utc, s.game_id))
        self._schedule_stubs = tuple(stubs)

        ck_path: Path | None = None
        done: set[int] = set()
        if checkpoint_base is not None and self._cfg.checkpoint_file:
            ck_path = checkpoint_base / self._cfg.checkpoint_file
            done = _read_checkpoint(ck_path)

        prev_by_id: dict[str, dict[str, Any]] = {}
        if output_csv_path is not None:
            prev_by_id = _load_previous_source_rows(output_csv_path)

        enrich_remaining = self._cfg.max_games

        logger.info(
            "NHL assemble: в расписании %d матчей, finished_only=%s, в checkpoint (OFF): %d, "
            "max_games=%s (лимит только на новые обогащения OFF; None = без лимита)",
            len(stubs),
            self._cfg.finished_only,
            len(done),
            self._cfg.max_games if self._cfg.max_games is not None else "—",
        )

        rows: list[dict[str, Any]] = []
        standings_cache: dict[str, dict[str, StandingRow]] = {}
        roster_cache: dict[tuple[str, int], str] = {}

        total_work = len(stubs)
        for idx, stub in enumerate(stubs, start=1):
            snap_ymd = standings_snapshot_ymd_before_game_date(stub.game_date)
            if snap_ymd not in standings_cache:
                logger.debug(
                    "NHL assemble: standings снимок %s (gameDate матча %s)",
                    snap_ymd,
                    stub.game_date,
                )
                standings_cache[snap_ymd] = fetch_standings_for_date(self._client, snap_ymd)

            st_idx = standings_cache[snap_ymd]

            if stub.game_state != "OFF":
                rows.append(
                    _build_upcoming_row(
                        stub,
                        st_idx=st_idx,
                        include_pbp=self._cfg.include_play_by_play,
                    )
                )
            else:
                sid = str(stub.game_id)
                prev_row = prev_by_id.get(sid)
                if (
                    stub.game_id in done
                    and prev_row is not None
                    and _row_is_finished_in_csv(prev_row)
                ):
                    rows.append(prev_row)
                elif enrich_remaining is not None and enrich_remaining <= 0:
                    if prev_row is not None:
                        rows.append(prev_row)
                    else:
                        logger.warning(
                            "NHL: лимит max_games исчерпан, нет строки в CSV для OFF game_id=%s",
                            stub.game_id,
                        )
                else:
                    try:
                        box, pbp = load_boxscore_and_pbp(
                            self._client,
                            stub.game_id,
                            with_pbp=self._cfg.include_play_by_play,
                        )
                    except SourceFetchError:
                        logger.warning("NHL: пропуск game_id=%s (boxscore/pbp)", stub.game_id)
                        if prev_row is not None:
                            rows.append(prev_row)
                    else:
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
                        if enrich_remaining is not None:
                            enrich_remaining -= 1

            flush_n = self._cfg.csv_flush_every
            if output_csv_path is not None and flush_n > 0 and len(rows) % flush_n == 0:
                merged, n_ret, n_win = _merge_full_source_snapshot(stubs, rows, prev_by_id)
                pd.DataFrame(merged).to_csv(output_csv_path, index=False)
                logger.info(
                    "NHL assemble: промежуточная запись CSV (%d всего: вне окна %d, окно %d; "
                    "обработано в проходе %d) → %s",
                    len(merged),
                    n_ret,
                    n_win,
                    len(rows),
                    output_csv_path,
                )

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

        merged, n_ret, n_win = _merge_full_source_snapshot(stubs, rows, prev_by_id)
        df_out = pd.DataFrame(merged)
        if not merged:
            logger.warning("NHL assemble: нет строк (проверьте интервал дат и фильтры)")
        else:
            logger.info(
                "NHL assemble: готово, всего строк: %d (вне окна расписания: %d, в окне: %d; "
                "обработано записей в проходе: %d)",
                len(merged),
                n_ret,
                n_win,
                len(rows),
            )

        if output_csv_path is not None and len(merged) > 0:
            df_out.to_csv(output_csv_path, index=False)

        return df_out
