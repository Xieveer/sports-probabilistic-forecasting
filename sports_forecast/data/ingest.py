"""Модуль загрузки и первичной обработки данных матчей (ingest layer).

Этот модуль отвечает за преобразование исходных данных из CSV формата
в оптимизированный Parquet формат для дальнейшей обработки.

Основные функции:
    - Чтение CSV файлов с данными матчей
    - Конвертация в Parquet формат
    - Извлечение и парсинг букмекерских коэффициентов (odds)
    - Разделение турниров на подтурниры (если задано в конфиге)
    - Валидация структуры данных
    - Логирование процесса обработки

Структура данных:
    - Входные данные: data/source/{tournament_name}/source.csv
    - Выходные данные:
        - data/raw/{tournament_name}/matches.parquet (основные данные)
        - data/raw/{tournament_name}/odds.parquet (букмекерские коэффициенты, опционально)

Конфигурация:
    Управляется через Hydra-конфиги:
        - conf/paths.yaml: пути к директориям
        - conf/tournament/*.yaml: настройки турниров (odds, split_strategy)

Attributes:
    PROJECT_ROOT (Path): Корневая директория проекта
    logger (Logger): Логгер модуля

Example:
    Запуск обработки всех турниров::

        $ python -m sports_forecast.data.ingest

    Или через DVC::

        $ dvc repro ingest

.. versionadded:: 0.1.0
.. versionchanged:: 0.2.0
    Добавлена поддержка извлечения букмекерских коэффициентов
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pandas as pd
from omegaconf import DictConfig

from sports_forecast.config.loaders import (
    load_bookmaker_config,
    load_paths_config,
    load_source_config,
)
from sports_forecast.utils.log_config import get_logger


#: Корневая директория проекта
PROJECT_ROOT = Path(__file__).resolve().parents[2]

#: Логгер модуля для отслеживания процесса загрузки
logger = get_logger(__name__)


def _apply_split_condition(series: pd.Series, condition: str) -> pd.Series:
    """Применить условие разделения к Series.

    Args:
        series: Series с данными для проверки
        condition: Условие в виде строки (например: "contains('stream 1', case=False)")

    Returns:
        Series с булевыми значениями (True/False)

    Examples:
        >>> s = pd.Series(['Stream 1', 'Stream 2', 'Other'])
        >>> _apply_split_condition(s, "contains('stream 1', case=False)")
        0     True
        1    False
        2    False
        dtype: bool
    """
    # Парсим условие и применяем к Series
    if condition == "default":
        # default всегда True (для остальных случаев)
        return pd.Series([True] * len(series), index=series.index)

    if "contains(" in condition:
        # Извлекаем аргументы для contains
        match = re.search(r"contains\('([^']+)'(?:,\s*case=(\w+))?\)", condition)
        if match:
            pattern = match.group(1)
            case_sensitive = match.group(2) != "False" if match.group(2) else True
            return series.str.contains(pattern, case=case_sensitive, na=False)

    if "equals(" in condition:
        # Извлекаем значение для equals
        match = re.search(r"equals\('([^']+)'\)", condition)
        if match:
            value = match.group(1)
            return series == value

    # Если условие не распознано, возвращаем False
    logger.warning("Неизвестное условие split: %s", condition)
    return pd.Series([False] * len(series), index=series.index)


def split_tournament_by_config(
    df: pd.DataFrame,
    raw_root: Path,
    tournament_name: str,
    split_cfg: DictConfig,
    odds_cfg: DictConfig | None = None,
) -> None:
    """Универсальная функция разделения турнира на подтурниры согласно конфигу.

    Args:
        df: DataFrame с данными турнира
        raw_root: Корневая директория для сохранения Parquet файлов
        tournament_name: Имя исходного турнира
        split_cfg: Конфигурация разделения из tournament.split_strategy
        odds_cfg: Конфигурация odds (опционально)

    Note:
        Конфигурация split_strategy должна содержать:
            - method: column_based
            - split_column: название колонки для разделения
            - rules: список правил с condition и output_tournament
    """
    split_column = split_cfg.split_column
    rules = split_cfg.rules

    if split_column not in df.columns:
        logger.warning(
            "Турнир %s: колонка '%s' для split не найдена, пропускаю разделение",
            tournament_name,
            split_column,
        )
        return

    logger.info(
        "Турнир %s: разделяю по колонке '%s' на %d подтурниров",
        tournament_name,
        split_column,
        len(rules),
    )

    # Применяем правила разделения
    for rule in rules:
        condition = rule.condition
        output_tournament = rule.output_tournament
        description = rule.get("description", "")

        # Применяем условие
        if condition == "default":
            # default = все что не попало в предыдущие условия
            # Для этого нужно исключить все уже обработанные строки
            mask = pd.Series([True] * len(df), index=df.index)
            for prev_rule in rules:
                if prev_rule.condition != "default":
                    prev_mask = _apply_split_condition(df[split_column], prev_rule.condition)
                    mask = mask & ~prev_mask
        else:
            mask = _apply_split_condition(df[split_column], condition)

        sub_df = df[mask].copy()

        if sub_df.empty:
            logger.warning(
                "Турнир %s: подтурнир %s пустой, пропускаю",
                tournament_name,
                output_tournament,
            )
            continue

        # Формируем путь
        output_parquet = raw_root / output_tournament / "matches.parquet"
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
            "Турнир %s → подтурнир %s (%s): сохранено %d записей → %s (%.2f MB)",
            tournament_name,
            output_tournament,
            description,
            len(sub_df),
            output_parquet,
            file_size / (1024 * 1024),
        )

        # Сохраняем odds.parquet (если есть конфигурация)
        if odds_cfg and odds_cfg.get("enabled"):
            save_odds_if_available(
                sub_df,
                output_tournament,
                output_parquet.parent,
                odds_column=odds_cfg.get("source_column"),
                bookmaker=odds_cfg.get("bookmaker"),
            )


def parse_odds_from_dict(
    odds_str: str, bookmaker: str, bookmaker_cfg: DictConfig | None = None
) -> dict:
    """Распарсить строку с коэффициентами в нормализованный dict.

    Принимает Python dict в строковом виде и преобразует в dict
    с нормализованными ключами (odds_*) согласно конфигурации букмекера.

    Args:
        odds_str: Python dict в строковом виде (например: "{'1': 1.5, '2': 2.5}")
        bookmaker: Название букмекера ('fonbet' или 'sdf')
        bookmaker_cfg: Конфигурация букмекера (опционально, загружается автоматически)

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

    Note:
        Маппинги коэффициентов загружаются из conf/bookmaker/{bookmaker}.yaml
    """
    if pd.isna(odds_str) or not odds_str:
        return {}

    # Загружаем конфиг букмекера если не передан
    if bookmaker_cfg is None:
        bookmaker_cfg = load_bookmaker_config(bookmaker)

    try:
        # Безопасный парсинг Python dict
        odds_raw = ast.literal_eval(odds_str)
        odds = {}

        # Применяем базовые маппинги из конфига
        if bookmaker_cfg and hasattr(bookmaker_cfg, "base_mapping"):
            base_mapping = dict(bookmaker_cfg.base_mapping)
            for raw_key, normalized_key in base_mapping.items():
                if raw_key in odds_raw:
                    odds[normalized_key] = odds_raw[raw_key]

        # Применяем паттерны для дополнительных рынков
        if bookmaker_cfg and hasattr(bookmaker_cfg, "patterns") and bookmaker_cfg.patterns:
            for pattern in bookmaker_cfg.patterns:
                prefix = pattern.prefix
                template = pattern.template

                for key, val in odds_raw.items():
                    if key.startswith(prefix):
                        # Извлекаем значение (например, "5.5" из "to_5.5")
                        value = key.replace(prefix, "")
                        # Формируем нормализованный ключ
                        normalized_key = template.format(value=value)
                        odds[normalized_key] = val

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

        Маппинги коэффициентов загружаются из conf/bookmaker/{bookmaker}.yaml
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

    # Загружаем конфиг букмекера один раз
    bookmaker_cfg = load_bookmaker_config(bookmaker)

    # Парсим коэффициенты
    mask = df[odds_column].notna()
    odds_list = []
    for odds_str, match_id in zip(df.loc[mask, odds_column], df.loc[mask, "id"], strict=False):
        parsed = parse_odds_from_dict(odds_str, bookmaker, bookmaker_cfg)
        if parsed:
            odds_list.append({**parsed, "id": match_id, "bookmaker": bookmaker})

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

        # БИЗНЕС-ЛОГИКА: Загружаем конфиг источника (если есть)
        source_config = None
        try:
            source_config = load_source_config(tournament_name)
            logger.debug("Источник %s: конфиг загружен", tournament_name)
        except FileNotFoundError:
            # Конфиг источника не найден - это нормально для простых турниров
            logger.debug(
                "Конфиг источника %s не найден, обрабатываю без специальной логики",
                tournament_name,
            )

        # Разделение на подтурниры (если задано в конфиге)
        if (
            source_config
            and hasattr(source_config, "split_strategy")
            and source_config.split_strategy.get("enabled")
        ):
            logger.info(
                "Источник %s: обнаружена split_strategy, разделяю на подтурниры",
                tournament_name,
            )

            # Получаем odds конфиг (если есть)
            odds_cfg = source_config.odds if hasattr(source_config, "odds") else None

            # Универсальное разделение через конфиг
            split_tournament_by_config(
                df,
                raw_root,
                tournament_name,
                source_config.split_strategy,
                odds_cfg,
            )

            logger.info("Источник %s: разделение завершено", tournament_name)
            return  # Источник обработан через split, не нужно сохранять единым файлом

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

        # Сохраняем odds.parquet (если есть конфигурация в source)
        if source_config and hasattr(source_config, "odds") and source_config.odds.get("enabled"):
            save_odds_if_available(
                df,
                tournament_name,
                output_parquet.parent,
                odds_column=source_config.odds.get("source_column"),
                bookmaker=source_config.odds.get("bookmaker"),
            )

    except pd.errors.ParserError as e:
        logger.error("Турнир %s: ошибка парсинга CSV - %s", tournament_name, e)
    except pd.errors.EmptyDataError as e:
        logger.error("Турнир %s: CSV файл пустой или поврежден - %s", tournament_name, e)
    except PermissionError as e:
        logger.error("Турнир %s: нет прав на запись - %s", tournament_name, e)
    except Exception:
        logger.exception("Турнир %s: неожиданная ошибка", tournament_name)


def run() -> None:
    """Запустить полный процесс ингеста данных: data/source → data/raw.

    Сканирует директорию data/source на наличие поддиректорий с турнирами
    и последовательно обрабатывает каждый турнир через process_tournament().

    Для каждого турнира:
        1. Читает source.csv
        2. Конвертирует в DataFrame
        3. Сохраняет как matches.parquet
        4. Извлекает букмекерские коэффициенты (если настроено)
        5. Разделяет на подтурниры (если настроено в split_strategy)

    Returns:
        None

    Raises:
        FileNotFoundError: Если директория data/source не существует.

    Examples:
        Запуск из командной строки::

            >>> run()
            INFO: Найдено турниров: 5
            INFO: Турнир uel: читаю data/source/uel/source.csv
            INFO: Турнир uel: загружено 1000 записей, 30 колонок
            INFO: Турнир uel: разделяю по колонке 'tour_name_en' на 3 подтурниров

        Или через Python API::

            >>> from sports_forecast.data.ingest import run
            >>> run()

    See Also:
        process_tournament: Обработка отдельного турнира
        split_tournament_by_config: Универсальное разделение на подтурниры

    Note:
        Функция использует Hydra для загрузки путей из conf/paths.yaml.
        Все пути разрешаются относительно корня проекта.
    """
    # Загружаем пути через Hydra
    paths_cfg = load_paths_config()

    data_source_dir = PROJECT_ROOT / paths_cfg.paths.source_dir
    data_raw_dir = PROJECT_ROOT / paths_cfg.paths.raw_dir

    if not data_source_dir.exists():
        raise FileNotFoundError(f"Каталог с источниками не найден: {data_source_dir}")

    tournaments = sorted(p for p in data_source_dir.iterdir() if p.is_dir())
    if not tournaments:
        logger.warning("В %s не найдено ни одного турнира", data_source_dir)
        return

    logger.info("Найдено турниров: %d", len(tournaments))

    for tournament_dir in tournaments:
        process_tournament(tournament_dir, data_raw_dir)


if __name__ == "__main__":
    run()
