"""
Модуль подготовки промежуточного слоя данных (interim).

Назначение:
    Преобразовать данные из слоя raw в более чистый и валидированный формат,
    пригодный для последующего вычисления фичей.

Слой данных:
    Вход:  data/raw/{tournament}/matches.parquet
    Выход: data/interim/{tournament}/matches_interim.parquet

Конфигурация:
    Управляется через турнир-специфичные Hydra-конфиги ``conf/tournament/*.yaml``.
    Для каждого турнира автоматически загружается соответствующий конфиг:

    - tournament.data_clean.required_columns
    - tournament.data_clean.drop_na_columns
    - tournament.data_clean.column_mapping (турнир-специфичный!)
    - tournament.data_clean.select_columns
    - tournament.data_clean.derived_columns (опционально, для генерации доп. колонок)

Пример запуска:
    $ uv run python -m sports_forecast.data.clean

    Автоматически обработает все турниры из data/raw/, применяя
    турнир-специфичные настройки очистки.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import pandas as pd
from omegaconf import DictConfig

from sports_forecast.config.loaders import load_paths_config, load_tournament_config
from sports_forecast.utils.log_config import get_logger


#: Корень проекта: sports_forecast/data/clean.py -> sports_forecast -> project_root
PROJECT_ROOT = Path(__file__).resolve().parents[2]
logger = get_logger(__name__)


def _derive_status(
    df: pd.DataFrame,
    score_columns: list[str],
    tournament_name: str,
) -> pd.DataFrame:
    """Определить статус матча по флагу match_is_end и наличию счёта.

    Логика:
        - match_is_end == 1 → ``"finished"``
        - match_is_end != 1 AND все score_columns пусты → ``"upcoming"``
        - match_is_end != 1 AND есть хотя бы один score → ``"live"`` (фильтруется)

    Args:
        df: DataFrame с колонкой ``match_is_end`` и score-колонками.
        score_columns: Список колонок со счётом (после column_mapping).
        tournament_name: Название турнира (для логирования).

    Returns:
        DataFrame с добавленной колонкой ``status`` и отфильтрованными live-событиями.
    """
    is_ended = df["match_is_end"].astype(str).str.strip().isin(["1", "True", "true"])

    existing_score_cols = [c for c in score_columns if c in df.columns]
    if existing_score_cols:
        has_score = df[existing_score_cols].notna().any(axis=1)
    else:
        has_score = pd.Series(False, index=df.index)

    df = df.copy()
    df["status"] = "unknown"
    df.loc[is_ended, "status"] = "finished"
    df.loc[~is_ended & ~has_score, "status"] = "upcoming"
    df.loc[~is_ended & has_score, "status"] = "live"

    finished_n = (df["status"] == "finished").sum()
    upcoming_n = (df["status"] == "upcoming").sum()
    live_n = (df["status"] == "live").sum()

    logger.info(
        "Турнир %s: status derived — finished=%d, upcoming=%d, live=%d",
        tournament_name,
        finished_n,
        upcoming_n,
        live_n,
    )

    if live_n > 0:
        logger.info(
            "Турнир %s: отфильтровано %d live-событий (match_is_end=0, но есть счёт)",
            tournament_name,
            live_n,
        )
        df = df[df["status"] != "live"]

    return df


def _apply_column_mapping(
    df: pd.DataFrame,
    mapping_cfg: DictConfig | None,
    tournament_name: str,
) -> pd.DataFrame:
    """Применить маппинг колонок для унификации названий.

    Args:
        df: Исходный датафрейм.
        mapping_cfg: DictConfig с маппингом {старое_название: новое_название}.
        tournament_name: Название турнира (для логирования).

    Returns:
        Датафрейм с переименованными колонками.
    """
    if not mapping_cfg:
        logger.debug(
            "Турнир %s: маппинг не задан в конфиге",
            tournament_name,
        )
        return df

    # Конвертируем DictConfig в dict для работы
    mapping = dict(mapping_cfg)

    # Находим только те колонки, которые реально есть в датафрейме
    rename_dict = {
        old_name: new_name for old_name, new_name in mapping.items() if old_name in df.columns
    }

    if rename_dict:
        # Guard: если несколько source маппятся в одно target,
        # берём первый найденный (предотвращаем дубликаты колонок).
        target_seen: dict[str, str] = {}
        unique_rename: dict[str, str] = {}
        for old_name, new_name in rename_dict.items():
            if new_name in target_seen:
                logger.warning(
                    "Турнир %s: дубль маппинга → '%s' и '%s' оба → '%s', используем '%s'",
                    tournament_name,
                    target_seen[new_name],
                    old_name,
                    new_name,
                    target_seen[new_name],
                )
                continue
            target_seen[new_name] = old_name
            unique_rename[old_name] = new_name
        rename_dict = unique_rename

        logger.info(
            "Турнир %s: применяю маппинг колонок: %s",
            tournament_name,
            rename_dict,
        )
        df = df.rename(columns=rename_dict)
    else:
        logger.debug(
            "Турнир %s: маппинг не требуется, все колонки уже в нужном формате",
            tournament_name,
        )

    return df


def _apply_dtype_conversion(
    df: pd.DataFrame,
    dtype_config: DictConfig | None,
    tournament_name: str,
) -> pd.DataFrame:
    """Применить типизацию колонок согласно конфигу.

    Args:
        df: Датафрейм для типизации.
        dtype_config: DictConfig с типами колонок из clean.dtype_mapping.
        tournament_name: Название турнира (для логирования).

    Returns:
        Датафрейм с приведенными типами.
    """
    if not dtype_config:
        logger.debug("Турнир %s: типизация не задана в конфиге", tournament_name)
        return df

    total_converted = 0

    # 1. Числовые колонки
    if hasattr(dtype_config, "numeric") and dtype_config.numeric:
        numeric_map = dict(dtype_config.numeric)
        for col, dtype in numeric_map.items():
            if col not in df.columns:
                continue

            try:
                # Конвертируем в числа
                df[col] = pd.to_numeric(df[col], errors="coerce")

                # Подсчитываем NaN после конвертации
                nan_count = df[col].isna().sum()
                if nan_count > 0:
                    logger.warning(
                        "Турнир %s: колонка '%s' - %d значений не удалось конвертировать (стали NaN)",
                        tournament_name,
                        col,
                        nan_count,
                    )

                # Приводим к нужному типу (int/float)
                if dtype == "int":
                    # Для int заполняем NaN нулями
                    df[col] = df[col].fillna(0).astype("int64")
                elif dtype == "float":
                    df[col] = df[col].astype("float64")

                total_converted += 1
                logger.debug("Турнир %s: колонка '%s' → %s", tournament_name, col, dtype)
            except Exception as e:
                logger.error(
                    "Турнир %s: не удалось конвертировать '%s' в %s - %s",
                    tournament_name,
                    col,
                    dtype,
                    e,
                )

    # 2. Строковые колонки
    if hasattr(dtype_config, "string") and dtype_config.string:
        string_cols = list(dtype_config.string)
        for col in string_cols:
            if col not in df.columns:
                continue

            try:
                df[col] = df[col].astype(str)
                total_converted += 1
                logger.debug("Турнир %s: колонка '%s' → string", tournament_name, col)
            except Exception as e:
                logger.error(
                    "Турнир %s: не удалось конвертировать '%s' в string - %s",
                    tournament_name,
                    col,
                    e,
                )

    # 3. Datetime колонки
    if hasattr(dtype_config, "datetime") and dtype_config.datetime:
        datetime_map = dict(dtype_config.datetime)
        for col, params in datetime_map.items():
            if col not in df.columns:
                continue

            try:
                # Параметры для pd.to_datetime
                dt_format = params.get("format") if isinstance(params, dict) else None
                dt_errors = params.get("errors", "coerce") if isinstance(params, dict) else "coerce"

                df[col] = pd.to_datetime(df[col], format=dt_format, errors=dt_errors)

                # Подсчитываем NaT после конвертации
                nat_count = df[col].isna().sum()
                if nat_count > 0:
                    logger.warning(
                        "Турнир %s: колонка '%s' - %d значений не удалось конвертировать в datetime (стали NaT)",
                        tournament_name,
                        col,
                        nat_count,
                    )

                total_converted += 1
                logger.debug(
                    "Турнир %s: колонка '%s' → datetime (format=%s)",
                    tournament_name,
                    col,
                    dt_format or "auto",
                )
            except Exception as e:
                logger.error(
                    "Турнир %s: не удалось конвертировать '%s' в datetime - %s",
                    tournament_name,
                    col,
                    e,
                )

    if total_converted > 0:
        logger.info(
            "Турнир %s: применена типизация к %d колонкам",
            tournament_name,
            total_converted,
        )

    return df


def _validate_required_columns(
    df: pd.DataFrame,
    required_columns: Iterable[str],
    tournament_name: str,
) -> bool:
    """Проверить наличие обязательных колонок в датафрейме.

    Args:
        df: Датафрейм с данными турнира.
        required_columns: Список обязательных колонок.
        tournament_name: Имя турнира для логов.

    Returns:
        True, если все колонки на месте, иначе False.
    """
    missing = [col for col in required_columns if col not in df.columns]
    if missing:
        logger.error(
            "Турнир %s: отсутствуют обязательные колонки %s, пропускаю турнир",
            tournament_name,
            missing,
        )
        return False
    return True


def _apply_derived_columns(
    df: pd.DataFrame,
    derived_cfg: DictConfig | None,
    tournament_name: str,
) -> pd.DataFrame:
    """Применить генерацию производных колонок согласно конфигу.

    Args:
        df: Датафрейм с данными.
        derived_cfg: DictConfig с правилами генерации колонок из tournament.data_clean.derived_columns.
        tournament_name: Название турнира (для логирования).

    Returns:
        Датафрейм с добавленными производными колонками.

    Note:
        Поддерживаемые трансформации:
            - extract_last_char: извлечь последний символ из строки
            - dayofweek: день недели из datetime (0=Пн, 6=Вс)
            - hour: час из datetime
            - date: дата из datetime
    """
    if not derived_cfg:
        logger.debug("Турнир %s: derived_columns не заданы в конфиге", tournament_name)
        return df

    added_columns = []

    for col_name, col_config in derived_cfg.items():
        source_col = col_config.get("source")
        transform = col_config.get("transform")

        # Проверяем наличие исходной колонки
        if source_col not in df.columns:
            logger.warning(
                "Турнир %s: исходная колонка '%s' для '%s' не найдена, пропускаю",
                tournament_name,
                source_col,
                col_name,
            )
            continue

        try:
            # Применяем трансформацию
            if transform == "extract_last_char":
                df[col_name] = df[source_col].astype(str).str[-1]
                added_columns.append(col_name)

            elif transform == "dayofweek":
                df[col_name] = pd.to_datetime(df[source_col]).dt.dayofweek
                added_columns.append(col_name)

            elif transform == "hour":
                df[col_name] = pd.to_datetime(df[source_col]).dt.hour
                added_columns.append(col_name)

            elif transform == "date":
                df[col_name] = pd.to_datetime(df[source_col]).dt.date
                added_columns.append(col_name)

            else:
                logger.warning(
                    "Турнир %s: неизвестная трансформация '%s' для колонки '%s'",
                    tournament_name,
                    transform,
                    col_name,
                )

        except Exception as e:
            logger.error(
                "Турнир %s: ошибка при генерации колонки '%s' - %s",
                tournament_name,
                col_name,
                e,
            )

    if added_columns:
        logger.info(
            "Турнир %s: добавлены производные колонки: %s",
            tournament_name,
            added_columns,
        )

    return df


def process_tournament(
    tournament_dir: Path, tournament_cfg: DictConfig, paths_cfg: DictConfig
) -> None:
    """Обработать один турнир: raw → interim.

    Читает parquet-файл из raw-слоя, применяет турнир-специфичный маппинг колонок,
    выполняет типизацию, минимальную очистку согласно конфигу турнира
    и сохраняет результат в interim-слой.

    Args:
        tournament_dir: Путь к директории турнира в raw-слое.
        tournament_cfg: Hydra-конфиг турнира с параметрами очистки (из tournament/*.yaml).
        paths_cfg: Конфиг с путями (из paths.yaml).
    """
    tournament_name = tournament_dir.name
    raw_path = tournament_dir / "matches.parquet"

    if not raw_path.exists():
        logger.warning("Турнир %s: файл %s не найден, пропускаю", tournament_name, raw_path)
        return

    logger.info("Турнир %s: читаю raw %s", tournament_name, raw_path)
    df: pd.DataFrame = pd.read_parquet(raw_path)

    if df is None or df.empty:
        logger.warning("Турнир %s: пустой датафрейм, пропускаю", tournament_name)
        return

    # ── Quality Gate: валидация raw-данных ──
    from sports_forecast.validation.gates import validate_raw

    validate_raw(df, tournament=tournament_name, raise_on_error=False)

    logger.info(
        "Турнир %s: загружено %d записей, %d колонок",
        tournament_name,
        len(df),
        df.shape[1],
    )

    # Извлекаем настройки очистки из турнир-специфичного конфига
    clean_cfg = tournament_cfg.data_clean

    # 1. Применяем маппинг колонок (если он задан в конфиге)
    mapping_cfg = clean_cfg.column_mapping if hasattr(clean_cfg, "column_mapping") else None
    df = _apply_column_mapping(df, mapping_cfg, tournament_name)

    # 2. Проверяем обязательные колонки (после маппинга!)
    required = clean_cfg.required_columns or []
    if required and not _validate_required_columns(df, required, tournament_name):
        return

    # 3. Определяем status из match_is_end + score columns
    #    ВАЖНО: ДО dtype_mapping, т.к. fillna(0) для int-колонок
    #    превратит NaN-счёт upcoming-матчей в 0 и сломает notna()-проверку.
    score_columns = list(clean_cfg.get("score_columns", []))
    if "match_is_end" in df.columns and score_columns:
        df = _derive_status(df, score_columns, tournament_name)
    elif hasattr(clean_cfg, "default_status") and clean_cfg.default_status:
        # Fallback: default_status для источников без match_is_end
        df["status"] = clean_cfg.default_status
        logger.info(
            "Турнир %s: добавлена колонка status = '%s'",
            tournament_name,
            clean_cfg.default_status,
        )

    # 4. Применяем типизацию (ВАЖНО: до dropna!)
    if hasattr(clean_cfg, "dtype_mapping"):
        df = _apply_dtype_conversion(df, clean_cfg.dtype_mapping, tournament_name)

    # 5. Удаляем строки с NaN
    drop_na_cols = clean_cfg.drop_na_columns or []
    if drop_na_cols:
        before = len(df)
        df = df.dropna(subset=drop_na_cols)
        after = len(df)
        logger.info(
            "Турнир %s: после dropna по %s осталось %d/%d записей",
            tournament_name,
            drop_na_cols,
            after,
            before,
        )

    # 5.5. Добавляем производные колонки (derived_columns) из конфига
    derived_cfg = clean_cfg.derived_columns if hasattr(clean_cfg, "derived_columns") else None
    df = _apply_derived_columns(df, derived_cfg, tournament_name)

    # 6. Выбираем нужные колонки
    select_cols = clean_cfg.select_columns or []
    if select_cols:
        # Добавляем status в список если он есть в данных, но не указан явно
        if "status" in df.columns and "status" not in select_cols:
            select_cols = list(select_cols) + ["status"]

        # Автоматически включаем odds_raw если он есть в данных (для BettingSimulator)
        if "odds_raw" in df.columns and "odds_raw" not in select_cols:
            select_cols = list(select_cols) + ["odds_raw"]
            logger.info(
                "Турнир %s: автоматически добавлена колонка odds_raw",
                tournament_name,
            )

        # Фильтруем только существующие колонки (tour_num/weekday/hour уже созданы выше)
        existing_cols = [c for c in select_cols if c in df.columns]
        if not existing_cols:
            logger.warning(
                "Турнир %s: ни одной из колонок %s нет в данных, пропускаю",
                tournament_name,
                select_cols,
            )
            return
        df = df[existing_cols]
        logger.info(
            "Турнир %s: оставлены колонки (%d): %s",
            tournament_name,
            len(existing_cols),
            existing_cols[:10],  # Показываем только первые 10
        )

    if df.empty:
        logger.warning("Турнир %s: после очистки датафрейм пуст, пропускаю", tournament_name)
        return

    # 7. Сохраняем результат
    interim_root = PROJECT_ROOT / paths_cfg.paths.interim_dir
    out_dir = interim_root / tournament_name
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "matches_interim.parquet"

    # ── Quality Gate: валидация interim-данных ──
    from sports_forecast.validation.gates import validate_interim

    validate_interim(df, tournament=tournament_name, raise_on_error=False)

    logger.info(
        "Турнир %s: записываю interim (%d записей) → %s",
        tournament_name,
        len(df),
        out_path,
    )
    df.to_parquet(out_path, index=False)


def run() -> None:
    """Запустить обработку всех турниров из raw-слоя в interim-слой.

    Для каждого турнира автоматически загружается соответствующий конфиг
    из conf/tournament/{tournament_name}.yaml и применяются турнир-специфичные
    настройки очистки данных.
    """
    paths_cfg = load_paths_config()

    raw_root = PROJECT_ROOT / paths_cfg.paths.raw_dir
    interim_root = PROJECT_ROOT / paths_cfg.paths.interim_dir

    if not raw_root.exists():
        raise RuntimeError(f"Папка с raw-данными не найдена: {raw_root}")

    interim_root.mkdir(parents=True, exist_ok=True)

    tournaments = sorted(p for p in raw_root.iterdir() if p.is_dir())
    if not tournaments:
        logger.warning("В %s нет ни одного турнира, ничего обрабатывать", raw_root)
        return

    logger.info("Найдено турниров в raw: %d", len(tournaments))

    for tournament_dir in tournaments:
        tournament_name = tournament_dir.name
        logger.info("=" * 60)
        logger.info("Обрабатываю турнир: %s", tournament_name)

        try:
            tournament_cfg = load_tournament_config(tournament_name)
            process_tournament(tournament_dir, tournament_cfg, paths_cfg)

        except Exception:
            logger.exception("Турнир %s: ошибка при обработке", tournament_name)
            continue

    logger.info("=" * 60)
    logger.info("Обработка завершена")


if __name__ == "__main__":
    run()
