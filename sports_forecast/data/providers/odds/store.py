"""Персистентное хранение линий букмекеров (The Odds API) в Parquet.

Используется source-слой: путь вида ``data/source/{tournament}/odds/pinnacle_odds.parquet``.
Операции ``upsert`` идемпотентны: дедупликация по дате и нормализованным командам,
приоритет — более свежий ``fetched_at``.

**Схема V3 (R21.10+):** целевой **close-only** store с отдельными полями эталонного
снимка ``T−15`` — нет open-снимка и
колонок ``*_open``, нет ничьи Pinnacle h2h (2-way with OT), есть ничья 1xBet. Семантика
в префиксах/суффиксах имён: ``winner``/``total`` = regulation, ``*withOT`` = полный матч.

Старые файлы R20 (V1) и R21.1–R21.8 (V2) при ``load_odds_store`` / ``upsert`` в памяти
поднимаются в V3: V1 → V2 → V3 (см. :func:`migrate_v1_to_v3`).

**Схема V1/V2** остаётся в ``ODDS_STORE_COLUMNS_V1`` / ``ODDS_STORE_COLUMNS_V2`` для
миграции и тестов.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, date, datetime
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

# R20 Parquet schema (12 колонок). Сохраняем для миграции и тестов.
ODDS_STORE_COLUMNS_V1: Final[tuple[str, ...]] = (
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

# R21 V2: тайминги события, Pinnacle (full game), 1xBet (regulation), метка загрузки.
ODDS_STORE_COLUMNS_V2: Final[tuple[str, ...]] = (
    "game_date",
    "home_team_norm",
    "away_team_norm",
    "commence_time_utc",
    "open_snapshot_utc",
    "close_snapshot_utc",
    "open_minutes_before",
    "close_minutes_before",
    "pinnacle_winner_withOT_home_open",
    "pinnacle_winner_withOT_away_open",
    "pinnacle_winner_withOT_draw_open",
    "pinnacle_winner_withOT_home_close",
    "pinnacle_winner_withOT_away_close",
    "pinnacle_winner_withOT_draw_close",
    "pinnacle_total_withOT_line_open",
    "pinnacle_total_withOT_over_open",
    "pinnacle_total_withOT_under_open",
    "pinnacle_total_withOT_line_close",
    "pinnacle_total_withOT_over_close",
    "pinnacle_total_withOT_under_close",
    "onexbet_winner_home_open",
    "onexbet_winner_away_open",
    "onexbet_winner_draw_open",
    "onexbet_winner_home_close",
    "onexbet_winner_away_close",
    "onexbet_winner_draw_close",
    "onexbet_total_line_open",
    "onexbet_total_over_open",
    "onexbet_total_under_open",
    "onexbet_total_line_close",
    "onexbet_total_over_close",
    "onexbet_total_under_close",
    "fetched_at",
)

# R21.10+ V3: только close, без open, без draw Pinnacle (NHL 2-way h2h).
ODDS_STORE_COLUMNS_V3: Final[tuple[str, ...]] = (
    "game_date",
    "home_team_norm",
    "away_team_norm",
    "commence_time_utc",
    "close_snapshot_utc",
    "close_minutes_before",
    "pinnacle_winner_withOT_home_close",
    "pinnacle_winner_withOT_away_close",
    "pinnacle_total_withOT_line_close",
    "pinnacle_total_withOT_over_close",
    "pinnacle_total_withOT_under_close",
    "onexbet_winner_home_close",
    "onexbet_winner_away_close",
    "onexbet_winner_draw_close",
    "onexbet_total_line_close",
    "onexbet_total_over_close",
    "onexbet_total_under_close",
    "fetched_at",
    "pinnacle_winner_withOT_home_t15",
    "pinnacle_winner_withOT_away_t15",
    "pinnacle_total_withOT_line_t15",
    "pinnacle_total_withOT_over_t15",
    "pinnacle_total_withOT_under_t15",
    "onexbet_winner_home_t15",
    "onexbet_winner_away_t15",
    "onexbet_winner_draw_t15",
    "onexbet_total_line_t15",
    "onexbet_total_over_t15",
    "onexbet_total_under_t15",
    "t15_provider_observed_at",
    "t15_retrieved_at",
)

#: Публичный кортеж колонок V3 с additive provenance historical ``t15``.
ODDS_STORE_COLUMNS: Final[tuple[str, ...]] = ODDS_STORE_COLUMNS_V3

T15_REFERENCE_COLUMNS: Final[tuple[str, ...]] = tuple(
    column for column in ODDS_STORE_COLUMNS_V3 if column.endswith("_t15")
) + (
    "t15_provider_observed_at",
    "t15_retrieved_at",
)

# Колонки, которые были в V2, но не входят в V3 (для auto-detect).
_V2_ONLY_COLUMNS: Final[frozenset[str]] = frozenset(ODDS_STORE_COLUMNS_V2) - frozenset(
    ODDS_STORE_COLUMNS_V3
)

_V1_TO_V2_RENAME: Final[dict[str, str]] = {
    "pinnacle_home_open": "pinnacle_winner_withOT_home_open",
    "pinnacle_away_open": "pinnacle_winner_withOT_away_open",
    "pinnacle_draw_open": "pinnacle_winner_withOT_draw_open",
    "pinnacle_home_close": "pinnacle_winner_withOT_home_close",
    "pinnacle_away_close": "pinnacle_winner_withOT_away_close",
    "pinnacle_draw_close": "pinnacle_winner_withOT_draw_close",
    "pinnacle_total_open": "pinnacle_total_withOT_over_open",
    "pinnacle_total_close": "pinnacle_total_withOT_over_close",
}


def migrate_v1_to_v2(df: pd.DataFrame) -> pd.DataFrame:
    """Перевести кадр из схемы R20 (V1) в R21 (V2).

    Переименовывает колонки Pinnacle по контракту ``winner_withOT`` / ``total_withOT``;
    значения V1 ``pinnacle_total_*`` (в R20 хранилась цена over) маппятся в
    ``pinnacle_total_withOT_over_*``. Остальные поля V2 заполняются NA.

    Args:
        df: входной кадр (в т.ч. пустой или только с частью колонок V1).

    Returns:
        DataFrame с колонками :data:`ODDS_STORE_COLUMNS_V2` в фиксированном порядке.
    """
    if df is None:
        return pd.DataFrame(columns=list(ODDS_STORE_COLUMNS_V2))
    renamed = df.rename(columns=_V1_TO_V2_RENAME)
    return renamed.reindex(columns=list(ODDS_STORE_COLUMNS_V2))


def migrate_v2_to_v3(df: pd.DataFrame) -> pd.DataFrame:
    """Усечь кадр V2 до схемы V3: только колонки :data:`ODDS_STORE_COLUMNS_V3` (порядок фиксирован).

    Open-снимки, ``pinnacle_winner_withOT_draw_*`` и прочие поля, отсутствующие в V3,
    отбрасываются; close-значения сохраняются.

    Args:
        df: входной кадр (в т.ч. пустой).

    Returns:
        DataFrame с колонками V3; отсутствующие поля — NA.
    """
    if df is None:
        return pd.DataFrame(columns=list(ODDS_STORE_COLUMNS_V3))
    return df.reindex(columns=list(ODDS_STORE_COLUMNS_V3))


def migrate_v1_to_v3(df: pd.DataFrame) -> pd.DataFrame:
    """Цепочка V1→V2→V3: переименование R20 и отброс open/draw Pinnacle как в V3.

    Args:
        df: кадр V1 или частичный; ``None`` трактуется как пустой V1.

    Returns:
        Кадр по схеме :data:`ODDS_STORE_COLUMNS`.
    """
    return migrate_v2_to_v3(migrate_v1_to_v2(df))


def _is_store_v3_frame(df: pd.DataFrame) -> bool:
    """True, если кадр уже в терминах V3 (нет колонок, характерных только для V2).

    Пустой кадр без колонок — False (нужно выравнивание по целевой схеме).
    """
    if df is None:
        return False
    if df.empty and len(df.columns) == 0:
        return False
    cols = frozenset(df.columns)
    if cols & _V2_ONLY_COLUMNS:
        return False
    return frozenset(ODDS_STORE_COLUMNS_V3).issubset(cols)


def _is_store_v2_frame(df: pd.DataFrame) -> bool:
    """True, если кадр уже в терминах V2 (есть обязательная колонка-сентинел)."""
    return "commence_time_utc" in df.columns


def _frame_has_v1_odds_columns(df: pd.DataFrame) -> bool:
    """Содержит ли кадр колонки схемы R20 (``pinnacle_home_open`` и т.д.)."""
    return "pinnacle_home_open" in df.columns


def _coerce_input_to_v3(df: pd.DataFrame) -> pd.DataFrame:
    """Привести произвольный вход (V1, V2, V3, пустой) к кадру перед выравниванием V3.

    Кадр с колонками V1 и одновременно ``commence_time_utc`` (из enrichment) сначала
    проходит :func:`migrate_v1_to_v2`, затем V2→V3, подставляя ``commence_time_utc`` из
    исходного кадра при необходимости.
    """
    if df.empty and len(df.columns) == 0:
        return pd.DataFrame(columns=list(ODDS_STORE_COLUMNS_V3))
    if _frame_has_v1_odds_columns(df):
        out2 = migrate_v1_to_v2(df)
        if "commence_time_utc" in df.columns:
            out2["commence_time_utc"] = df["commence_time_utc"]
        return migrate_v2_to_v3(out2)
    if _is_store_v3_frame(df):
        return df.reindex(columns=list(ODDS_STORE_COLUMNS_V3))
    if _is_store_v2_frame(df):
        return migrate_v2_to_v3(df)
    return migrate_v1_to_v3(df)


def _now_utc_iso() -> str:
    """Текущий момент в UTC в формате ISO 8601 (для ``fetched_at``)."""
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _align_to_store_schema(df: pd.DataFrame) -> pd.DataFrame:
    """Оставить только колонки схемы V3 store, в фиксированном порядке; лишние отбрасываются.

    Вход V1 / V2 сначала приводится к V3 in-memory.
    """
    v3 = _coerce_input_to_v3(df)
    extra = [c for c in v3.columns if c not in ODDS_STORE_COLUMNS_V3]
    if extra:
        logger.debug("Отброшены неизвестные колонки odds store: %s", extra)
    return v3.reindex(columns=list(ODDS_STORE_COLUMNS_V3))


def _coerce_fetched_for_sort(s: pd.Series) -> pd.Series:
    """Парсинг ``fetched_at`` в UTC; неразборчивое → NaT (считаем «старым»)."""
    return pd.to_datetime(s, utc=True, errors="coerce")


def load_odds_store(store_path: Path) -> pd.DataFrame:
    """Загрузить Parquet-таблицу odds. Если файла нет — пустой DataFrame со схемой V3.

    Файл V1 (без ``commence_time_utc``) или V2 (open+close) прозрачно приводится к V3
    (цепочка V1→V2→V3 либо V2→V3).

    Args:
        store_path: путь к ``*.parquet`` (например ``.../pinnacle_odds.parquet``).

    Returns:
        DataFrame с колонками :data:`ODDS_STORE_COLUMNS` (V3, возможны NaN).
    """
    if not store_path.exists():
        return pd.DataFrame(columns=list(ODDS_STORE_COLUMNS_V3))
    df = pd.read_parquet(store_path)
    if df.empty:
        return pd.DataFrame(columns=list(ODDS_STORE_COLUMNS_V3))
    if _frame_has_v1_odds_columns(df) and not _is_store_v2_frame(df):
        logger.debug("Миграция odds store V1→V3 при загрузке: %s", store_path)
    elif not _is_store_v3_frame(df):
        logger.debug("Миграция/выравнивание loaded odds store → V3: %s", store_path)
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
        df: данные; лишние колонки отбрасываются, отсутствующие в схеме V3 — NaN.
            Кадр V1 / V2 мигрирует в V3 перед записью.
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
            Кадр V1 (R20) или V2 автоматически приводится к V3.

    Returns:
        Итоговый DataFrame по схеме V3 store, без дубликатов по ключам.
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
        return pd.DataFrame(columns=list(ODDS_STORE_COLUMNS_V3))
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


def upsert_t15_reference_store_file(reference_df: pd.DataFrame, store_path: Path) -> pd.DataFrame:
    """Записать только historical ``T−15`` поля, не затрагивая legacy ``*_close``.

    Этот путь намеренно не использует обычный row-level upsert: более поздний
    backfill reference не должен заменить forecast/legacy значения той же игры.
    """
    existing = load_odds_store(store_path)
    updates = reference_df.reindex(columns=list(ODDS_STORE_COLUMNS_V3)).copy()
    if updates.empty:
        return existing
    updates = updates.dropna(subset=list(ODDS_DEDUP_KEYS)).drop_duplicates(
        subset=list(ODDS_DEDUP_KEYS), keep="last"
    )
    if updates.empty:
        return existing

    out = existing.copy()
    for _, update in updates.iterrows():
        key_mask = pd.Series(True, index=out.index)
        for key_column in ODDS_DEDUP_KEYS:
            key_mask &= out[key_column] == update[key_column]
        if key_mask.any():
            for column in T15_REFERENCE_COLUMNS:
                if pd.notna(update[column]):
                    out.loc[key_mask, column] = update[column]
            continue
        new_row = update.copy()
        if pd.isna(new_row["fetched_at"]):
            new_row["fetched_at"] = _now_utc_iso()
        out = pd.concat([out, pd.DataFrame([new_row])], ignore_index=True)

    result = _align_to_store_schema(out)
    save_odds_store(result, store_path)
    return result
