"""Модуль загрузки и первичной обработки данных матчей.

Этот модуль отвечает за преобразование исходных данных из CSV формата
в оптимизированный Parquet формат для дальнейшей обработки.

Основные функции:
    - Чтение CSV файлов с данными матчей
    - Конвертация в Parquet формат
    - Валидация структуры данных
    - Логирование процесса обработки

Структура данных:
    - Входные данные: data/source/{tournament_name}/source.csv
    - Выходные данные: data/raw/{tournament_name}/matches.parquet

Attributes:
    PROJECT_ROOT (Path): Корневая директория проекта
    DATA_SOURCE_DIR (Path): Директория с исходными данными
    DATA_RAW_DIR (Path): Директория для сырых данных в Parquet формате
    logger (Logger): Логгер модуля

Example:
    Запуск обработки всех турниров::

        $ python -m sports_forecast.data.ingest

    Или через DVC::

        $ dvc repro ingest

.. versionadded:: 0.1.0
"""

from __future__ import annotations

import ast
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from sports_forecast.utils.log_config import get_logger


#: Корневая директория проекта
PROJECT_ROOT = Path(__file__).resolve().parents[2]

#: Директория с исходными CSV файлами
DATA_SOURCE_DIR = PROJECT_ROOT / "data" / "source"

#: Директория для сырых данных в Parquet формате
DATA_RAW_DIR = PROJECT_ROOT / "data" / "raw"

#: Логгер модуля для отслеживания процесса загрузки
logger = get_logger(__name__)

#: Директория с конфигурациями турниров
CONF_TOURNAMENT_DIR = PROJECT_ROOT / "conf" / "tournament"


def load_tournament_config(tournament_name: str) -> dict:
    """Загрузить конфигурацию турнира из YAML файла.

    Args:
        tournament_name: Название турнира (например: 'uel_kz_1', 'lp_ru')

    Returns:
        Dict с конфигурацией турнира или пустой dict если файл не найден

    Examples:
        >>> config = load_tournament_config('uel_kz_1')
        >>> config['odds']['enabled']
        True
    """
    config_path = CONF_TOURNAMENT_DIR / f"{tournament_name}.yaml"

    if not config_path.exists():
        logger.warning("Конфиг для турнира %s не найден: %s", tournament_name, config_path)
        return {}

    try:
        with config_path.open(encoding="utf-8") as f:
            config = yaml.safe_load(f)
        return config if config else {}  # type: ignore[no-any-return]
    except Exception as e:
        logger.error("Ошибка чтения конфига %s: %s", config_path, e)
        return {}


def get_uel_subtournament(tour_name_en: pd.Series) -> pd.Series:
    """Определить подтурнир UEL по названию стрима.

    UEL фактически состоит из трех отдельных турниров:
    - kz_1: Kazakhstan Stream 1
    - kz_2: Kazakhstan Stream 2
    - cz: Czech Republic (все остальные)

    Args:
        tour_name_en: Series с названиями турниров на английском.

    Returns:
        Series с названиями подтурниров ('kz_1', 'kz_2', 'cz').

    Examples:
        >>> tour_names = pd.Series(['Stream 1', 'Stream 2', 'Other'])
        >>> get_uel_subtournament(tour_names)
        0    kz_1
        1    kz_2
        2      cz
        dtype: object
    """
    return pd.Series(
        np.select(
            [
                tour_name_en.str.contains("stream 1", case=False, na=False),
                tour_name_en.str.contains("stream 2", case=False, na=False),
            ],
            ["kz_1", "kz_2"],
            default="cz",
        ),
        index=tour_name_en.index,
    )


def split_lp_eu_tournament(df: pd.DataFrame, raw_root: Path, tournament_name: str) -> None:
    """Разделить турнир LP_EU на два подтурнира и сохранить отдельно.

    Разделение по полю tour_name_g:
    - a18 → lp_eu_a18
    - остальные (a12, a14, a16, a17, ...) → lp_eu

    Args:
        df: DataFrame с данными турнира LP_EU.
        raw_root: Корневая директория для сохранения Parquet файлов.
        tournament_name: Имя исходного турнира (обычно 'lp_eu').

    Returns:
        None

    Note:
        Создает два отдельных директории и файла:
        - data/raw/lp_eu_a18/matches.parquet
        - data/raw/lp_eu/matches.parquet
    """
    if "tour_name_g" not in df.columns:
        logger.warning(
            "Турнир %s: колонка 'tour_name_g' не найдена, не могу разделить на подтурниры",
            tournament_name,
        )
        return

    # Определяем подтурнир для каждого матча
    df["subtournament"] = df["tour_name_g"].apply(lambda x: "a18" if x == "a18" else "main")

    # Группируем и сохраняем по подтурнирам
    for subtournament_key, subtournament_suffix in [("a18", "_a18"), ("main", "")]:
        sub_df = df[df["subtournament"] == subtournament_key].copy()

        if sub_df.empty:
            logger.warning(
                "Турнир %s: подтурнир %s пустой, пропускаю", tournament_name, subtournament_key
            )
            continue

        # Удаляем служебную колонку
        sub_df = sub_df.drop(columns=["subtournament"])

        # Формируем путь: lp_eu_a18 или lp_eu
        full_tournament_name = f"{tournament_name}{subtournament_suffix}"
        output_parquet = raw_root / full_tournament_name / "matches.parquet"

        # Создаем директорию
        output_parquet.parent.mkdir(parents=True, exist_ok=True)

        # Сохраняем
        sub_df.to_parquet(
            output_parquet,
            index=False,
            engine="pyarrow",
            compression="snappy",
        )

        file_size = output_parquet.stat().st_size
        logger.info(
            "Турнир %s → подтурнир %s: сохранено %d записей → %s (%.2f MB)",
            tournament_name,
            subtournament_key,
            len(sub_df),
            output_parquet,
            file_size / (1024 * 1024),
        )

        # Сохраняем odds.parquet (если есть конфигурация)
        config = load_tournament_config(full_tournament_name)
        odds_config = config.get("odds", {})

        if odds_config.get("enabled"):
            save_odds_if_available(
                sub_df,
                full_tournament_name,
                output_parquet.parent,
                odds_column=odds_config.get("source_column"),
                bookmaker=odds_config.get("bookmaker"),
            )


def split_uel_tournament(df: pd.DataFrame, raw_root: Path, tournament_name: str) -> None:
    """Разделить турнир UEL на три подтурнира и сохранить отдельно.

    Args:
        df: DataFrame с данными турнира UEL.
        raw_root: Корневая директория для сохранения Parquet файлов.
        tournament_name: Имя исходного турнира (обычно 'uel').

    Returns:
        None

    Note:
        Создает три отдельных директории и файла:
        - data/raw/uel_kz_1/matches.parquet
        - data/raw/uel_kz_2/matches.parquet
        - data/raw/uel_cz/matches.parquet
    """
    if "tour_name_en" not in df.columns:
        logger.warning(
            "Турнир %s: колонка 'tour_name_en' не найдена, не могу разделить на подтурниры",
            tournament_name,
        )
        return

    # Определяем подтурнир для каждого матча
    df["subtournament"] = get_uel_subtournament(df["tour_name_en"])

    # Группируем и сохраняем по подтурнирам
    for subtournament_name in ["kz_1", "kz_2", "cz"]:
        sub_df = df[df["subtournament"] == subtournament_name].copy()

        if sub_df.empty:
            logger.warning(
                "Турнир %s: подтурнир %s пустой, пропускаю", tournament_name, subtournament_name
            )
            continue

        # Удаляем служебную колонку
        sub_df = sub_df.drop(columns=["subtournament"])

        # Формируем путь: uel_kz_1, uel_kz_2, uel_cz
        full_tournament_name = f"{tournament_name}_{subtournament_name}"
        output_parquet = raw_root / full_tournament_name / "matches.parquet"

        # Создаем директорию
        output_parquet.parent.mkdir(parents=True, exist_ok=True)

        # Сохраняем
        sub_df.to_parquet(
            output_parquet,
            index=False,
            engine="pyarrow",
            compression="snappy",
        )

        file_size = output_parquet.stat().st_size
        logger.info(
            "Турнир %s → подтурнир %s: сохранено %d записей → %s (%.2f MB)",
            tournament_name,
            subtournament_name,
            len(sub_df),
            output_parquet,
            file_size / (1024 * 1024),
        )

        # Сохраняем odds.parquet (если есть конфигурация)
        config = load_tournament_config(full_tournament_name)
        odds_config = config.get("odds", {})

        if odds_config.get("enabled"):
            save_odds_if_available(
                sub_df,
                full_tournament_name,
                output_parquet.parent,
                odds_column=odds_config.get("source_column"),
                bookmaker=odds_config.get("bookmaker"),
            )


def parse_odds_from_dict(odds_str: str, bookmaker: str) -> dict:
    """Распарсить строку с коэффициентами в нормализованный dict.

    Принимает Python dict в строковом виде и преобразует в dict
    с нормализованными ключами (odds_*).

    Args:
        odds_str: Python dict в строковом виде (например: "{'1': 1.5, '2': 2.5}")
        bookmaker: Название букмекера ('fonbet' или 'sdf')

    Returns:
        Dict с нормализованными ключами:
            - odds_home_win: коэффициент на победу хозяев
            - odds_draw: коэффициент на ничью (если есть)
            - odds_away_win: коэффициент на победу гостей
            - odds_total_over_X.X: коэффициенты на тотал больше
            - odds_total_under_X.X: коэффициенты на тотал меньше
            - odds_handicap_home_X.X: коэффициенты на фору хозяев
            - odds_handicap_away_X.X: коэффициенты на фору гостей

    Examples:
        >>> parse_odds_from_dict("{'1': 1.48, '2': 2.45}", "sdf")
        {'odds_home_win': 1.48, 'odds_away_win': 2.45}

        >>> parse_odds_from_dict("{'1': 4.7, 'x': 5.0, '2': 1.52, 'to_5.5': 2.17}", "fonbet")
        {'odds_home_win': 4.7, 'odds_draw': 5.0, 'odds_away_win': 1.52, 'odds_total_over_5.5': 2.17}
    """
    if pd.isna(odds_str) or not odds_str:
        return {}

    try:
        # Безопасный парсинг Python dict
        odds_raw = ast.literal_eval(odds_str)

        # Базовые коэффициенты (есть у всех)
        odds = {
            "odds_home_win": odds_raw.get("1"),
            "odds_draw": odds_raw.get("x"),
            "odds_away_win": odds_raw.get("2"),
        }

        # Парсинг дополнительных типов ставок (только для fonbet)
        if bookmaker == "fonbet":
            for key, val in odds_raw.items():
                if key.startswith("to_"):  # Total Over
                    base = key.replace("to_", "")
                    odds[f"odds_total_over_{base}"] = val
                elif key.startswith("tu_"):  # Total Under
                    base = key.replace("tu_", "")
                    odds[f"odds_total_under_{base}"] = val
                elif key.startswith("f1"):  # Home Handicap
                    hcap = key.replace("f1", "")
                    odds[f"odds_handicap_home{hcap}"] = val
                elif key.startswith("f2"):  # Away Handicap
                    hcap = key.replace("f2", "")
                    odds[f"odds_handicap_away{hcap}"] = val

        # Убираем None значения
        return {k: v for k, v in odds.items() if v is not None}

    except (ValueError, SyntaxError) as e:
        logger.warning("Ошибка парсинга odds: %s (строка: %s)", e, odds_str[:100])
        return {}


def extract_odds_from_tournament(
    df: pd.DataFrame,
    tournament_name: str,
    odds_column: str,
    bookmaker: str,
) -> pd.DataFrame | None:
    """Извлечь коэффициенты букмекера из DataFrame турнира.

    Args:
        df: DataFrame с данными турнира
        tournament_name: Название турнира (для логирования)
        odds_column: Название колонки с коэффициентами
        bookmaker: Название букмекера

    Returns:
        DataFrame с коэффициентами или None если коэффициентов нет

    Note:
        Возвращаемый DataFrame содержит:
            - id: ID матча (для джойна)
            - bookmaker: источник коэффициентов
            - odds_*: нормализованные коэффициенты
    """
    if odds_column not in df.columns:
        logger.warning(
            "Турнир %s: колонка с коэффициентами '%s' отсутствует", tournament_name, odds_column
        )
        return None

    # Проверяем заполненность
    odds_count = df[odds_column].notna().sum()
    odds_pct = odds_count / len(df) * 100 if len(df) > 0 else 0

    if odds_count == 0:
        logger.info("Турнир %s: нет коэффициентов в колонке '%s'", tournament_name, odds_column)
        return None

    logger.info(
        "Турнир %s: найдено %d коэффициентов (%.1f%%)", tournament_name, odds_count, odds_pct
    )

    # Парсим коэффициенты для каждого матча
    odds_list = []
    for _idx, row in df[df[odds_column].notna()].iterrows():
        parsed = parse_odds_from_dict(row[odds_column], bookmaker)
        if parsed:
            parsed["id"] = row["id"]
            parsed["bookmaker"] = bookmaker
            odds_list.append(parsed)

    if not odds_list:
        logger.warning("Турнир %s: не удалось распарсить ни одного коэффициента", tournament_name)
        return None

    odds_df = pd.DataFrame(odds_list)
    logger.info(
        "Турнир %s: успешно распарсено %d коэффициентов, колонок: %d",
        tournament_name,
        len(odds_df),
        len(odds_df.columns),
    )

    return odds_df


def save_odds_if_available(
    df: pd.DataFrame,
    tournament_name: str,
    output_dir: Path,
    odds_column: str | None = None,
    bookmaker: str | None = None,
) -> None:
    """Сохранить коэффициенты букмекера (если доступны).

    Извлекает коэффициенты из DataFrame и сохраняет их в odds.parquet
    в той же директории что и matches.parquet.

    Args:
        df: DataFrame с данными турнира
        tournament_name: Название турнира
        output_dir: Директория для сохранения (где лежит matches.parquet)
        odds_column: Колонка с коэффициентами (опционально)
        bookmaker: Название букмекера (опционально)

    Note:
        Если коэффициенты отсутствуют, функция просто ничего не делает
        (не создает пустой файл).
    """
    if not odds_column or not bookmaker:
        return

    odds_df = extract_odds_from_tournament(df, tournament_name, odds_column, bookmaker)

    if odds_df is None or odds_df.empty:
        return

    odds_path = output_dir / "odds.parquet"

    try:
        odds_df.to_parquet(
            odds_path,
            index=False,
            engine="pyarrow",
            compression="snappy",
        )

        file_size = odds_path.stat().st_size
        logger.info(
            "Турнир %s: ✓ odds.parquet создан → %s (размер: %.2f MB, строк: %d)",
            tournament_name,
            odds_path,
            file_size / (1024 * 1024),
            len(odds_df),
        )
    except Exception as e:
        logger.error("Турнир %s: ошибка сохранения odds.parquet - %s", tournament_name, e)


def process_tournament(source_dir: Path, raw_root: Path) -> None:
    """Обработать один турнир: CSV → Parquet (ингест данных).

    Читает CSV файл с данными матчей турнира и конвертирует его
    в оптимизированный Parquet формат для дальнейшей обработки.

    Args:
        source_dir: Путь к директории турнира в data/source.
            Ожидается структура: source_dir/source.csv
        raw_root: Корневая директория для сохранения Parquet файлов.
            Обычно это data/raw

    Returns:
        None

    Raises:
        FileNotFoundError: Если файл source.csv не найден (логируется warning).
        pd.errors.ParserError: Если CSV файл имеет неверный формат.

    Examples:
        >>> from pathlib import Path
        >>> source_path = Path("data/source/premier_league_2023")
        >>> raw_path = Path("data/raw")
        >>> process_tournament(source_path, raw_path)

    Note:
        Функция автоматически создает необходимые директории для выходных данных.
        Если файл source.csv отсутствует, турнир пропускается с предупреждением.
        Все колонки сохраняются как строки для избежания проблем с типами.

    Todo:
        * Добавить валидацию схемы CSV
        * Реализовать обработку ошибок парсинга
        * Добавить поддержку сжатия Parquet файлов
        * Добавить автоопределение разделителя CSV
    """
    tournament_name = source_dir.name
    source_csv = source_dir / "source.csv"
    output_parquet = raw_root / tournament_name / "matches.parquet"

    logger.info("=" * 60)
    logger.info("НАЧАЛО ОБРАБОТКИ ТУРНИРА: %s", tournament_name)
    logger.info("Ищу файл: %s", source_csv)
    logger.info("Файл существует: %s", source_csv.exists())
    logger.info("=" * 60)

    if not source_csv.exists():
        logger.warning("Пропускаю турнир %s: файл %s отсутствует", tournament_name, source_csv)
        return

    logger.info("Турнир %s: читаю %s", tournament_name, source_csv)

    try:
        # Читаем CSV, сохраняя все колонки как строки для избежания проблем с типами
        # low_memory=False для корректного определения типов во всем файле
        df: pd.DataFrame = pd.read_csv(
            source_csv,
            dtype=str,  # Все колонки как строки
            low_memory=False,
        )

        logger.info("Турнир %s: прочитано строк: %d", tournament_name, len(df))
        logger.info("Турнир %s: колонок: %d", tournament_name, len(df.columns))

        if df.empty:
            logger.warning("Турнир %s: CSV файл пустой, пропускаю", tournament_name)
            return

        logger.info(
            "Турнир %s: загружено %d записей, %d колонок",
            tournament_name,
            len(df),
            len(df.columns),
        )

        # БИЗНЕС-ЛОГИКА: Разделение турниров на подтурниры
        if tournament_name == "uel":
            logger.info(
                "Турнир %s: обнаружен UEL, разделяю на подтурниры (kz_1, kz_2, cz)", tournament_name
            )
            split_uel_tournament(df, raw_root, tournament_name)
            logger.info("Турнир %s: разделение завершено", tournament_name)
            return  # UEL обработан через split, не нужно сохранять единым файлом

        if tournament_name == "lp_eu":
            logger.info(
                "Турнир %s: обнаружен LP_EU, разделяю на подтурниры (a18, main)", tournament_name
            )
            split_lp_eu_tournament(df, raw_root, tournament_name)
            logger.info("Турнир %s: разделение завершено", tournament_name)
            return  # LP_EU обработан через split, не нужно сохранять единым файлом

        # Стандартная обработка для остальных турниров
        # Создаем директорию для выходного файла
        logger.info("Турнир %s: создаю директорию %s", tournament_name, output_parquet.parent)
        output_parquet.parent.mkdir(parents=True, exist_ok=True)

        # Сохраняем в Parquet с дополнительными параметрами
        logger.info("Турнир %s: сохраняю в %s", tournament_name, output_parquet)
        df.to_parquet(
            output_parquet,
            index=False,
            engine="pyarrow",
            compression="snappy",  # Сжатие для экономии места
        )

        # Проверяем, что файл создан
        if output_parquet.exists():
            file_size = output_parquet.stat().st_size
            logger.info(
                "Турнир %s: ✓ parquet создан → %s (размер: %.2f MB)",
                tournament_name,
                output_parquet,
                file_size / (1024 * 1024),
            )
        else:
            logger.error("Турнир %s: ✗ parquet НЕ СОЗДАН → %s", tournament_name, output_parquet)

        # Сохраняем odds.parquet (если есть конфигурация)
        config = load_tournament_config(tournament_name)
        odds_config = config.get("odds", {})

        if odds_config.get("enabled"):
            save_odds_if_available(
                df,
                tournament_name,
                output_parquet.parent,
                odds_column=odds_config.get("source_column"),
                bookmaker=odds_config.get("bookmaker"),
            )

    except pd.errors.ParserError as e:
        logger.error("Турнир %s: ошибка парсинга CSV - %s", tournament_name, e)
    except pd.errors.EmptyDataError as e:
        logger.error("Турнир %s: CSV файл пустой или поврежден - %s", tournament_name, e)
    except PermissionError as e:
        logger.error("Турнир %s: нет прав на запись - %s", tournament_name, e)
    except Exception as e:
        logger.error("Турнир %s: неожиданная ошибка - %s", tournament_name, e)
        import traceback

        logger.error("Traceback:\n%s", traceback.format_exc())


def run() -> None:
    """Запустить полный процесс ингеста данных: data/source → data/raw.

    Сканирует директорию data/source на наличие поддиректорий с турнирами
    и последовательно обрабатывает каждый турнир через process_tournament().

    Для каждого турнира:
        1. Читает source.csv
        2. Конвертирует в DataFrame
        3. Сохраняет как matches.parquet

    Returns:
        None

    Raises:
        FileNotFoundError: Если директория data/source не существует.

    Examples:
        Запуск из командной строки::

            >>> run()
            INFO: Найдено турниров: 5
            INFO: Турнир premier_league_2023: читаю data/source/premier_league_2023/source.csv
            INFO: Турнир premier_league_2023: загружено 380 записей, 25 колонок

        Или через Python API::

            >>> from sports_forecast.data.ingest import run
            >>> run()

    See Also:
        process_tournament: Обработка отдельного турнира

    Note:
        Функция использует pathlib.Path для кросс-платформенной совместимости.
        Все пути разрешаются относительно корня проекта.
    """
    if not DATA_SOURCE_DIR.exists():
        raise FileNotFoundError(f"Каталог с источниками не найден: {DATA_SOURCE_DIR}")

    tournaments = sorted(p for p in DATA_SOURCE_DIR.iterdir() if p.is_dir())
    if not tournaments:
        logger.warning("В %s не найдено ни одного турнира", DATA_SOURCE_DIR)
        return

    logger.info("Найдено турниров: %d", len(tournaments))

    for tournament_dir in tournaments:
        process_tournament(tournament_dir, DATA_RAW_DIR)


if __name__ == "__main__":
    run()
