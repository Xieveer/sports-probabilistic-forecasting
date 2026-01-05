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

from sports_forecast.utils.log_config import get_logger


#: Корень проекта: sports_forecast/data/clean.py -> sports_forecast -> project_root
PROJECT_ROOT = Path(__file__).resolve().parents[2]
logger = get_logger(__name__)


def _apply_column_mapping(
    df: pd.DataFrame,
    mapping: dict[str, str],
    tournament_name: str,
) -> pd.DataFrame:
    """Применить маппинг колонок для унификации названий.

    Args:
        df: Исходный датафрейм.
        mapping: Словарь {старое_название: новое_название}.
        tournament_name: Название турнира (для логирования).

    Returns:
        Датафрейм с переименованными колонками.
    """
    # Находим только те колонки, которые реально есть в датафрейме
    rename_dict = {
        old_name: new_name for old_name, new_name in mapping.items() if old_name in df.columns
    }

    if rename_dict:
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
    dtype_config: DictConfig,
    tournament_name: str,
) -> pd.DataFrame:
    """Применить типизацию колонок согласно конфигу.

    Args:
        df: Датафрейм для типизации.
        dtype_config: Конфиг с типами колонок из clean.dtype_mapping.
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

    logger.info(
        "Турнир %s: загружено %d записей, %d колонок",
        tournament_name,
        len(df),
        df.shape[1],
    )

    # Извлекаем настройки очистки из турнир-специфичного конфига
    clean_cfg = tournament_cfg.data_clean

    # 1. Применяем маппинг колонок (если он задан в конфиге)
    if hasattr(clean_cfg, "column_mapping") and clean_cfg.column_mapping:
        mapping = dict(clean_cfg.column_mapping)
        df = _apply_column_mapping(df, mapping, tournament_name)

    # 2. Проверяем обязательные колонки (после маппинга!)
    required = clean_cfg.required_columns or []
    if required and not _validate_required_columns(df, required, tournament_name):
        return

    # 3. Применяем типизацию (ВАЖНО: до dropna!)
    if hasattr(clean_cfg, "dtype_mapping"):
        df = _apply_dtype_conversion(df, clean_cfg.dtype_mapping, tournament_name)

    # 4. Удаляем строки с NaN
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

    # 5. Добавляем default_status если указан (для турниров без колонки status)
    if hasattr(clean_cfg, "default_status") and clean_cfg.default_status:
        df["status"] = clean_cfg.default_status
        logger.info(
            "Турнир %s: добавлена колонка status = '%s'",
            tournament_name,
            clean_cfg.default_status,
        )

    # 6. Выбираем нужные колонки
    select_cols = clean_cfg.select_columns or []
    if select_cols:
        # Добавляем status в список если есть default_status
        if (
            hasattr(clean_cfg, "default_status")
            and clean_cfg.default_status
            and "status" not in select_cols
        ):
            select_cols = list(select_cols) + ["status"]

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
            "Турнир %s: оставлены колонки: %s",
            tournament_name,
            existing_cols,
        )

    if df.empty:
        logger.warning("Турнир %s: после очистки датафрейм пуст, пропускаю", tournament_name)
        return

    # 7. Сохраняем результат
    interim_root = PROJECT_ROOT / paths_cfg.paths.interim_dir
    out_dir = interim_root / tournament_name
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "matches_interim.parquet"

    logger.info(
        "Турнир %s: записываю interim (%d записей) → %s",
        tournament_name,
        len(df),
        out_path,
    )
    df.to_parquet(out_path, index=False)


def load_tournament_config(tournament_name: str) -> tuple[DictConfig, DictConfig]:
    """Загрузить конфиг для конкретного турнира (только tournament + paths).

    Args:
        tournament_name: Имя турнира (например, 'uel', 'lp_by').

    Returns:
        Tuple (tournament_cfg, paths_cfg) с настройками турнира и путями.

    Raises:
        FileNotFoundError: Если конфиг турнира не найден.
    """
    from hydra import compose, initialize_config_dir
    from omegaconf import OmegaConf

    config_dir = str((PROJECT_ROOT / "conf").resolve())

    # Загружаем paths
    with initialize_config_dir(config_dir=config_dir, version_base="1.3"):
        paths_cfg = compose(config_name="paths", return_hydra_config=False)

    # Загружаем tournament-специфичный конфиг напрямую
    tournament_config_path = PROJECT_ROOT / "conf" / "tournament" / f"{tournament_name}.yaml"
    if not tournament_config_path.exists():
        raise FileNotFoundError(f"Конфиг турнира не найден: {tournament_config_path}")

    tournament_cfg = OmegaConf.load(tournament_config_path)

    return tournament_cfg, paths_cfg


def run() -> None:
    """Запустить обработку всех турниров из raw-слоя в interim-слой.

    Для каждого турнира автоматически загружается соответствующий конфиг
    из conf/tournament/{tournament_name}.yaml и применяются турнир-специфичные
    настройки очистки данных.
    """
    from hydra import compose, initialize_config_dir

    # Загружаем базовый конфиг только для получения путей
    config_dir = str((PROJECT_ROOT / "conf").resolve())
    with initialize_config_dir(config_dir=config_dir, version_base="1.3"):
        # Загружаем только paths
        base_cfg = compose(config_name="paths", return_hydra_config=False)

    raw_root = PROJECT_ROOT / base_cfg.paths.raw_dir
    interim_root = PROJECT_ROOT / base_cfg.paths.interim_dir

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
            # Загружаем конфиг для конкретного турнира
            tournament_cfg, paths_cfg = load_tournament_config(tournament_name)

            # Обрабатываем турнир
            process_tournament(tournament_dir, tournament_cfg, paths_cfg)

        except Exception as e:
            logger.error("Турнир %s: ошибка при обработке - %s", tournament_name, e)
            import traceback

            logger.error("Traceback:\n%s", traceback.format_exc())
            continue

    logger.info("=" * 60)
    logger.info("Обработка завершена")


if __name__ == "__main__":
    run()
