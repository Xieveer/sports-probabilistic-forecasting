"""
Модуль подготовки промежуточного слоя данных (interim).

Назначение:
    Преобразовать данные из слоя raw в более чистый и валидированный формат,
    пригодный для последующего вычисления фичей.

Слой данных:
    Вход:  data/raw/{tournament}/matches.parquet
    Выход: data/interim/{tournament}/matches_interim.parquet

Конфигурация:
    Управляется через Hydra-конфиг ``conf/data_clean.yaml``:

    - paths.raw_dir / paths.interim_dir
    - clean.required_columns
    - clean.drop_na_columns
    - clean.column_mapping
    - clean.select_columns

Пример запуска:
    $ uv run python -m sports_forecast.data.clean
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import hydra
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


def process_tournament(tournament_dir: Path, cfg: DictConfig) -> None:
    """Обработать один турнир: raw → interim.

    Читает parquet-файл из raw-слоя, применяет маппинг колонок,
    выполняет типизацию, минимальную очистку согласно конфигу
    и сохраняет результат в interim-слой.

    Args:
        tournament_dir: Путь к директории турнира в raw-слое.
        cfg: Hydra-конфиг с параметрами очистки.
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

    # 1. Применяем маппинг колонок (если он задан в конфиге)
    if hasattr(cfg.clean, "column_mapping") and cfg.clean.column_mapping:
        mapping = dict(cfg.clean.column_mapping)
        df = _apply_column_mapping(df, mapping, tournament_name)

    # 2. Проверяем обязательные колонки (после маппинга!)
    required = cfg.clean.required_columns or []
    if required and not _validate_required_columns(df, required, tournament_name):
        return

    # 3. Применяем типизацию (ВАЖНО: до dropna!)
    if hasattr(cfg.clean, "dtype_mapping"):
        df = _apply_dtype_conversion(df, cfg.clean.dtype_mapping, tournament_name)

    # 4. Удаляем строки с NaN
    drop_na_cols = cfg.clean.drop_na_columns or []
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

    # 5. Выбираем нужные колонки
    select_cols = cfg.clean.select_columns or []
    if select_cols:
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

    # 6. Сохраняем результат
    interim_root = PROJECT_ROOT / cfg.paths.interim_dir
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


@hydra.main(config_path="../../conf", config_name="data_clean", version_base="1.3")
def run(cfg: DictConfig) -> None:
    """Запустить обработку всех турниров из raw-слоя в interim-слой."""
    raw_root = PROJECT_ROOT / cfg.paths.raw_dir
    interim_root = PROJECT_ROOT / cfg.paths.interim_dir

    if not raw_root.exists():
        raise RuntimeError(f"Папка с raw-данными не найдена: {raw_root}")

    interim_root.mkdir(parents=True, exist_ok=True)

    tournaments = sorted(p for p in raw_root.iterdir() if p.is_dir())
    if not tournaments:
        logger.warning("В %s нет ни одного турнира, ничего обрабатывать", raw_root)
        return

    logger.info("Найдено турниров в raw: %d", len(tournaments))
    for tournament_dir in tournaments:
        process_tournament(tournament_dir, cfg)


if __name__ == "__main__":
    run()
