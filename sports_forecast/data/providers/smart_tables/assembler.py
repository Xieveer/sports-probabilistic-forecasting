"""Сборка wide-строки Smart Tables bronze → ``source.csv``."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import pandas as pd
from omegaconf import DictConfig, OmegaConf

from sports_forecast.data.providers.base import SourceFetchError
from sports_forecast.data.providers.smart_tables.catalog import (
    filter_national_competitions,
    load_competition_catalog,
)
from sports_forecast.data.providers.smart_tables.client import SmartTablesApiClient
from sports_forecast.data.providers.smart_tables.constants import (
    PERIOD_API_TO_SUFFIX,
    PERIODS_API,
    STAT_CODES,
)
from sports_forecast.data.providers.smart_tables.fetch import (
    append_checkpoint,
    fetch_match_bronze,
    read_checkpoint,
)
from sports_forecast.data.providers.smart_tables.importance import (
    compute_is_friendly,
    compute_match_importance,
)
from sports_forecast.data.providers.smart_tables.matches_list import collect_match_ids
from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)


@dataclass
class AssemblerConfig:
    """Параметры сборщика (поля ``provider`` в source yaml)."""

    catalog_path: str
    national_teams_only: bool
    competition_codes: list[str] | None
    max_matches: int | None
    matches_page_limit: int
    matches_list_checkpoint: str | None
    matches_list_cache_dir: str
    raw_cache_dir: str
    checkpoint_file: str | None
    csv_flush_every: int
    progress_log_every: int
    mode: str
    use_network: bool


def _env_int(name: str) -> int | None:
    raw = os.getenv(name, "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _env_codes(name: str) -> list[str] | None:
    raw = os.getenv(name, "").strip()
    if not raw:
        return None
    return [c.strip() for c in raw.split(",") if c.strip()]


def load_assembler_config(provider_cfg: DictConfig) -> AssemblerConfig:
    """Построить :class:`AssemblerConfig` из ветки ``provider``."""
    c = OmegaConf.to_container(provider_cfg, resolve=True)
    if not isinstance(c, dict):
        raise SourceFetchError("smart_tables_api: provider должен быть объектом")

    codes = c.get("competition_codes")
    code_list: list[str] | None = None
    if codes is not None and codes != "":
        code_list = [str(x) for x in codes] if isinstance(codes, (list, tuple)) else [str(codes)]

    env_codes = _env_codes("SF_SMART_TABLES_COMPETITION_CODES")
    if env_codes is not None:
        code_list = env_codes

    max_m = c.get("max_matches")
    max_matches = int(max_m) if max_m is not None else None
    env_max = _env_int("SF_SMART_TABLES_MAX_MATCHES")
    if env_max is not None:
        max_matches = env_max

    raw_flush = c.get("csv_flush_every", 50)
    try:
        csv_flush = max(0, int(raw_flush))
    except (TypeError, ValueError):
        csv_flush = 50

    raw_every = c.get("progress_log_every", 25)
    try:
        progress_every = max(0, int(raw_every))
    except (TypeError, ValueError):
        progress_every = 25

    ml_ck = c.get("matches_list_checkpoint")
    ck = c.get("checkpoint_file")

    return AssemblerConfig(
        catalog_path=str(c.get("catalog_path", "")),
        national_teams_only=bool(c.get("national_teams_only", True)),
        competition_codes=code_list,
        max_matches=max_matches,
        matches_page_limit=int(c.get("matches_page_limit", 200)),
        matches_list_checkpoint=str(ml_ck).strip() if ml_ck else None,
        matches_list_cache_dir=str(c.get("matches_list_cache_dir", "raw/lists")),
        raw_cache_dir=str(c.get("raw_cache_dir", "raw")),
        checkpoint_file=str(ck).strip() if ck else None,
        csv_flush_every=csv_flush,
        progress_log_every=progress_every,
        mode=str(c.get("mode", "backfill")),
        use_network=bool(c.get("use_network", True)),
    )


def _team_field(team: dict[str, Any] | None, key: str, default: Any = "") -> Any:
    if not team:
        return default
    return team.get(key, default)


def _current_coach(team: dict[str, Any] | None) -> tuple[str, str]:
    if not team:
        return "", ""
    coaches = team.get("coaches") or []
    if not isinstance(coaches, list):
        return "", ""
    for coach in coaches:
        if isinstance(coach, dict) and coach.get("is_current"):
            return str(coach.get("id", "")), str(coach.get("name", ""))
    if coaches and isinstance(coaches[0], dict):
        c0 = coaches[0]
        return str(c0.get("id", "")), str(c0.get("name", ""))
    return "", ""


def _parse_stat_payload(payload: dict[str, Any], period_suffix: str) -> dict[str, Any]:
    row: dict[str, Any] = {}
    data = payload.get("data") if payload else None
    stats = data.get("stat") if isinstance(data, dict) else None
    if not isinstance(stats, list):
        return row
    for item in stats:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code", ""))
        if code not in STAT_CODES:
            continue
        row[f"home_{code}_{period_suffix}"] = item.get("home")
        row[f"away_{code}_{period_suffix}"] = item.get("away")
    return row


def _parse_chart_payload(payload: dict[str, Any], prefix: str) -> dict[str, Any]:
    data = payload.get("data") if payload else None
    chart = data.get("chart") if isinstance(data, dict) else None
    if not isinstance(chart, dict):
        return {f"home_goal_minutes_{prefix}": "[]", f"away_goal_minutes_{prefix}": "[]"}
    home_m: list[Any] = []
    away_m: list[Any] = []
    home = chart.get("home")
    away = chart.get("away")
    if isinstance(home, dict):
        home_m = home.get("minutes") or []
    if isinstance(away, dict):
        away_m = away.get("minutes") or []
    return {
        f"home_goal_minutes_{prefix}": json.dumps(home_m, ensure_ascii=False),
        f"away_goal_minutes_{prefix}": json.dumps(away_m, ensure_ascii=False),
    }


def bronze_to_row(bronze: dict[str, Any]) -> dict[str, Any] | None:
    """Преобразовать bronze JSON одного матча в wide-строку ``football.md``.

    Args:
        bronze: Результат :func:`fetch_match_bronze`.

    Returns:
        Строка для CSV или ``None``, если матч не проходит national-фильтр.
    """
    card_payload = bronze.get("card") or {}
    data = card_payload.get("data")
    item = data.get("item") if isinstance(data, dict) else None
    if not isinstance(item, dict):
        return None

    home_team = item.get("home_team_with_coach") or item.get("home_team") or {}
    away_team = item.get("away_team_with_coach") or item.get("away_team") or {}
    if not isinstance(home_team, dict):
        home_team = {}
    if not isinstance(away_team, dict):
        away_team = {}

    home_nat = int(_team_field(home_team, "is_national", 0) or 0)
    away_nat = int(_team_field(away_team, "is_national", 0) or 0)
    if home_nat != 1 or away_nat != 1:
        return None

    competition = item.get("competition") if isinstance(item.get("competition"), dict) else {}
    status = str(item.get("status", ""))
    is_end = 1 if status.lower() in ("finished", "ended", "ft") else 0

    h_coach_id, h_coach_name = _current_coach(home_team)
    a_coach_id, a_coach_name = _current_coach(away_team)
    referee = item.get("referee") if isinstance(item.get("referee"), dict) else {}

    row: dict[str, Any] = {
        "match_id": item.get("id"),
        "match_center_id": item.get("match_center_id", ""),
        "competition_id": item.get("competition_id", competition.get("id", "")),
        "competition_code": competition.get("code", ""),
        "season_id": item.get("season_id", ""),
        "datetime": item.get("begin_at", ""),
        "match_status": status,
        "match_is_end": is_end,
        "match_importance": compute_match_importance(competition),
        "is_friendly": compute_is_friendly(competition),
        "competition_is_cup": competition.get("is_cup", ""),
        "competition_is_top": competition.get("is_top", ""),
        "stage": item.get("stage", ""),
        "round": item.get("round", ""),
        "group": item.get("group", ""),
        "home_team_id": item.get("home_team_id", home_team.get("id", "")),
        "away_team_id": item.get("away_team_id", away_team.get("id", "")),
        "home_team_name": _team_field(home_team, "common_title") or _team_field(home_team, "title"),
        "away_team_name": _team_field(away_team, "common_title") or _team_field(away_team, "title"),
        "home_is_national": home_nat,
        "away_is_national": away_nat,
        "home_score_ft": item.get("home_goals", item.get("home_points", "")),
        "away_score_ft": item.get("away_goals", item.get("away_points", "")),
        "home_coach_id": h_coach_id,
        "home_coach_name": h_coach_name,
        "away_coach_id": a_coach_id,
        "away_coach_name": a_coach_name,
        "referee_id": item.get("referee_id", referee.get("id", "")),
        "referee_name": referee.get("name", ""),
        "odd_home": item.get("odd_home", ""),
        "odd_draw": item.get("odd_x", item.get("odd_draw", "")),
        "odd_away": item.get("odd_away", ""),
    }

    for api_period in PERIODS_API:
        suffix = PERIOD_API_TO_SUFFIX[api_period]
        stat_payload = bronze.get(f"stat_{api_period}") or {}
        row.update(_parse_stat_payload(stat_payload, suffix))
        chart_payload = bronze.get(f"chart_{api_period}") or {}
        row.update(_parse_chart_payload(chart_payload, suffix))

    # HT score from first-half goals stat
    row["home_score_ht"] = row.get("home_goals_1h", "")
    row["away_score_ht"] = row.get("away_goals_1h", "")

    return row


class SmartTablesDataAssembler:
    """Оркестрация backfill: каталог → списки матчей → bronze → ``source.csv``."""

    def __init__(self, client: SmartTablesApiClient, cfg: AssemblerConfig) -> None:
        self._client = client
        self._cfg = cfg

    def build_dataframe(
        self,
        *,
        storage_dir: Path,
        output_csv_path: Path,
    ) -> pd.DataFrame:
        """Выполнить backfill и записать ``source.csv``.

        Args:
            storage_dir: ``data/source/football_nationals``.
            output_csv_path: Путь к итоговому CSV.

        Returns:
            DataFrame собранных строк.
        """
        catalog = load_competition_catalog(self._cfg.catalog_path)
        competitions = filter_national_competitions(
            catalog,
            national_teams_only=self._cfg.national_teams_only,
            competition_codes=self._cfg.competition_codes,
        )
        if not competitions:
            raise SourceFetchError("Smart Tables: пустой каталог после фильтрации")

        list_ck = (
            storage_dir / self._cfg.matches_list_checkpoint
            if self._cfg.matches_list_checkpoint
            else None
        )
        list_cache = storage_dir / self._cfg.matches_list_cache_dir
        raw_root = storage_dir / self._cfg.raw_cache_dir

        match_ids = collect_match_ids(
            self._client,
            competitions,
            page_limit=self._cfg.matches_page_limit,
            cache_dir=list_cache,
            checkpoint_path=list_ck,
            use_network=self._cfg.use_network,
        )
        if self._cfg.max_matches is not None:
            match_ids = match_ids[: self._cfg.max_matches]

        ck_path = storage_dir / self._cfg.checkpoint_file if self._cfg.checkpoint_file else None
        done = read_checkpoint(ck_path) if ck_path else set()

        prev_rows: list[dict[str, Any]] = []
        if output_csv_path.is_file() and done:
            prev_df = pd.read_csv(output_csv_path, dtype=str, low_memory=False)
            prev_rows = cast(list[dict[str, Any]], prev_df.to_dict(orient="records"))

        rows: list[dict[str, Any]] = list(prev_rows)
        seen_row_ids = {str(r.get("match_id")) for r in prev_rows if r.get("match_id") is not None}
        n_ok = len(prev_rows)
        for mid in match_ids:
            if mid in done:
                continue
            bronze = fetch_match_bronze(
                self._client,
                mid,
                raw_root,
                use_network=self._cfg.use_network,
            )
            row = bronze_to_row(bronze)
            if row is not None:
                rid = str(row.get("match_id"))
                if rid not in seen_row_ids:
                    rows.append(row)
                    seen_row_ids.add(rid)
                    n_ok += 1
                else:
                    rows = [r for r in rows if str(r.get("match_id")) != rid]
                    rows.append(row)
            if ck_path is not None:
                append_checkpoint(ck_path, mid)
            if (
                self._cfg.progress_log_every > 0
                and n_ok > 0
                and n_ok % self._cfg.progress_log_every == 0
            ):
                logger.info("Smart Tables assembler: обогащено %d матчей", n_ok)
            if (
                self._cfg.csv_flush_every > 0
                and rows
                and len(rows) % self._cfg.csv_flush_every == 0
            ):
                self._write_csv(output_csv_path, rows)

        if not rows:
            logger.warning("Smart Tables assembler: нет строк после фильтрации")
            if output_csv_path.is_file():
                return pd.read_csv(output_csv_path, dtype=str, low_memory=False)
            return pd.DataFrame()

        df = self._write_csv(output_csv_path, rows)
        if ck_path is not None and ck_path.is_file():
            ck_path.unlink()
            logger.info("Smart Tables: удалён checkpoint матчей %s", ck_path)
        return df

    @staticmethod
    def _write_csv(path: Path, rows: list[dict[str, Any]]) -> pd.DataFrame:
        path.parent.mkdir(parents=True, exist_ok=True)
        df = pd.DataFrame(rows)
        if "datetime" in df.columns:
            ts = pd.to_datetime(df["datetime"], errors="coerce", utc=True)
            df = df.assign(datetime=ts)
            df = df.sort_values(by=["datetime", "match_id"], na_position="last")
        df.to_csv(path, index=False)
        logger.info("Smart Tables: записано %d строк → %s", len(df), path)
        return cast(pd.DataFrame, df)
