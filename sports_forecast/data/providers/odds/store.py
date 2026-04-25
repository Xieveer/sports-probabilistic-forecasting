"""Персистентное хранение линий Pinnacle (The Odds API) в Parquet.

Используется source-слой: путь вида ``data/source/{tournament}/odds/pinnacle_odds.parquet``.
Операции ``upsert`` идемпотентны: дедупликация по дате и нормализованным командам,
приоритет — более свежий ``fetched_at``.
"""

from __future__ import annotations

import os
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Final

import pandas as pd

from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)

ODDS_DEDUP_KEYS: Final[tuple[str, str, str]] = (
    "game_date",
    "home_team_norm",
    "away_team_norm",
)

ODDS_STORE_COLUMNS: Final[tuple[str, ...]] = (
    "game_date",
    "home_team_norm",
    "away_team_norm",
    "pinnacle_home_open",
    "pinnacle_away_open",
    "pinnacle_draw_open",
    "pinnacle_home_close",
    "pinnacle_away_close",
    "pinnacle_draw_close",
    "pinnacle_total_open",
    "pinnacle_total_close",
    "fetched_at",
)


def _now_utc_iso() -> str:
    """Текущий момент в UTC в формате ISO 8601 (для ``fetched_at``)."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _align_to_store_schema(df: pd.DataFrame) -> pd.DataFrame:
    """Оставить только колонки схемы store, в фиксированном порядке; остальные отбрасываются."""
    extra = [c for c in df.columns if c not in ODDS_STORE_COLUMNS]
    if extra:
        logger.debug("Отброшены неизвестные колонки odds store: %s", extra)
    return df.reindex(columns=list(ODDS_STORE_COLUMNS))


def _coerce_fetched_for_sort(s: pd.Series) -> pd.Series:
    """Парсинг ``fetched_at`` в UTC; неразборчивое → NaT (считаем «старым»)."""
    return pd.to_datetime(s, utc=True, errors="coerce")


def load_odds_store(store_path: Path) -> pd.DataFrame:
    """Загрузить Parquet-таблицу odds. Если файла нет — пустой DataFrame со схемой.

    Args:
        store_path: путь к ``*.parquet`` (например ``.../pinnacle_odds.parquet``).

    Returns:
        DataFrame с колонками :data:`ODDS_STORE_COLUMNS` (возможны NaN).
    """
    if not store_path.exists():
        return pd.DataFrame(columns=list(ODDS_STORE_COLUMNS))
    df = pd.read_parquet(store_path)
    if not df.empty and list(df.columns) != list(ODDS_STORE_COLUMNS):
        logger.debug("Выравнивание колонок loaded odds store по схеме R20.1")
    return _align_to_store_schema(df)


def max_game_date_in_store(store_df: pd.DataFrame) -> date | None:
    """Максимальная календарная дата в колонке ``game_date`` (строки ISO или timestamp).

    Пустой фрейм/без колонки/только NaT — ``None``.
    """
    if store_df is None or store_df.empty or "game_date" not in store_df.columns:
        return None
    parsed = pd.to_datetime(store_df["game_date"], errors="coerce", utc=True)
    if parsed.isna().all():
        return None
    m = parsed.max()
    if pd.isna(m):
        return None
    ts = pd.Timestamp(m)
    return ts.date()


def _write_parquet_atomic(df: pd.DataFrame, path: Path) -> None:
    """Записать Parquet в ``path`` атомарно: временный файл в том же каталоге + rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    aligned = _align_to_store_schema(df)
    tmp = path.parent / f".{path.name}.tmp.{os.getpid()}.{uuid.uuid4().hex}.parquet"
    try:
        aligned.to_parquet(tmp, index=False)
        tmp.replace(path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                logger.warning("Не удалось удалить временный файл %s", tmp)


def save_odds_store(df: pd.DataFrame, store_path: Path) -> None:
    """Сохранить таблицу odds в Parquet (атомарная запись, не ломает существующий файл при сбое).

    Args:
        df: данные; лишние колонки отбрасываются, отсутствующие в схеме — NaN.
        store_path: целевой путь.
    """
    _write_parquet_atomic(df, store_path)
    logger.debug("Записан odds store: %s, строк: %d", store_path, len(df))


def upsert_odds_store(existing_df: pd.DataFrame, new_df: pd.DataFrame) -> pd.DataFrame:
    """Слияние с дедупликацией по :data:`ODDS_DEDUP_KEYS`.

    Для одной и той же тройки ключей остаётся запись с наиболее свежим ``fetched_at`` (UTC).
    При равенстве ``fetched_at`` побеждает строка, идущая позже в объединённом ряде (``keep='last'``).

    Args:
        existing_df: текущий снимок (может быть пустым).
        new_df: новые строки; при отсутствии ``fetched_at`` подставляется текущий UTC ISO.

    Returns:
        Итоговый DataFrame по схеме store, без дубликатов по ключам.
    """
    existing = _align_to_store_schema(existing_df)
    new = _align_to_store_schema(new_df.copy())

    if not new.empty:
        fmask = new["fetched_at"].isna()
        if fmask.all():
            new["fetched_at"] = _now_utc_iso()
        elif fmask.any():
            new.loc[fmask, "fetched_at"] = _now_utc_iso()

    if new.empty and existing.empty:
        return pd.DataFrame(columns=list(ODDS_STORE_COLUMNS))
    if new.empty:
        return existing
    if existing.empty:
        return _dedup_combined(new)

    combined = pd.concat([existing, new], ignore_index=True)
    return _dedup_combined(combined)


def _dedup_combined(combined: pd.DataFrame) -> pd.DataFrame:
    """Сортировка по времени и порядку строк, затем ``drop_duplicates(keep='last')``."""
    c = _align_to_store_schema(combined)
    c = c.reset_index(drop=True)
    c["_ord"] = range(len(c))
    c["_ts"] = _coerce_fetched_for_sort(c["fetched_at"])
    c = c.sort_values(by=list(ODDS_DEDUP_KEYS) + ["_ts", "_ord"], kind="mergesort")
    out = c.drop_duplicates(subset=list(ODDS_DEDUP_KEYS), keep="last")
    out = out.drop(columns=["_ord", "_ts"], errors="ignore")
    return _align_to_store_schema(out.reset_index(drop=True))


def upsert_odds_store_file(new_df: pd.DataFrame, store_path: Path) -> pd.DataFrame:
    """Загрузить store с диска, выполнить upsert, атомарно сохранить, вернуть итог.

    Args:
        new_df: новые данные.
        store_path: путь к Parquet-файлу (файл может отсутствовать — обрабатывается как пустой store).

    Returns:
        Результирующий DataFrame после upsert.
    """
    existing = load_odds_store(store_path)
    result = upsert_odds_store(existing, new_df)
    save_odds_store(result, store_path)
    return result
