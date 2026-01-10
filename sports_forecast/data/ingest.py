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
from pathlib import Path

import numpy as np
import pandas as pd
from hydra import compose, initialize_config_dir
from omegaconf import DictConfig

from sports_forecast.utils.log_config import get_logger


#: Корневая директория проекта
PROJECT_ROOT = Path(__file__).resolve().parents[2]

#: Логгер модуля для отслеживания процесса загрузки
logger = get_logger(__name__)


def load_source_config(source_name: str) -> DictConfig:
    """Загрузить конфигурацию источника данных через Hydra compose.

    Args:
        source_name: Название источника (например: 'uel', 'lp_eu')

    Returns:
        DictConfig с конфигурацией источника

    Raises:
        FileNotFoundError: Если конфиг источника не найден

    Examples:
        >>> config = load_source_config('uel')
        >>> config.split_strategy.enabled
        True

    Note:
        Использует Hydra compose для загрузки конфигов из conf/source/*.yaml.
        Конфиги источников используются на этапе ingest для определения
        правил разделения и извлечения коэффициентов.
    """
    config_dir = str((PROJECT_ROOT / "conf").resolve())
    source_config_path = PROJECT_ROOT / "conf" / "source" / f"{source_name}.yaml"

    if not source_config_path.exists():
        raise FileNotFoundError(f"Конфиг источника не найден: {source_config_path}")

    try:
        with initialize_config_dir(config_dir=config_dir, version_base="1.3"):
            return compose(  # type: ignore[no-any-return]
                config_name=f"source/{source_name}",
                return_hydra_config=False,
            )
    except Exception as e:
        logger.error("Ошибка загрузки конфига источника %s: %s", source_name, e)
        raise


def load_tournament_config(tournament_name: str) -> DictConfig:
    """Загрузить конфигурацию турнира через Hydra compose.

    Args:
        tournament_name: Название турнира (например: 'uel_kz_1', 'lp_ru')

    Returns:
        DictConfig с конфигурацией турнира

    Raises:
        FileNotFoundError: Если конфиг турнира не найден

    Examples:
        >>> config = load_tournament_config('uel_kz_1')
        >>> config.data.odds_feed.enabled
        True

    Note:
        Использует Hydra compose для загрузки конфигов из conf/tournament/*.yaml.
        Конфиги турниров используются на этапах clean/features/train.
    """
    config_dir = str((PROJECT_ROOT / "conf").resolve())
    tournament_config_path = PROJECT_ROOT / "conf" / "tournament" / f"{tournament_name}.yaml"

    if not tournament_config_path.exists():
        raise FileNotFoundError(f"Конфиг турнира не найден: {tournament_config_path}")

    try:
        with initialize_config_dir(config_dir=config_dir, version_base="1.3"):
            return compose(  # type: ignore[no-any-return]
                config_name=f"tournament/{tournament_name}",
                return_hydra_config=False,
            )
    except Exception as e:
        logger.error("Ошибка загрузки конфига турнира %s: %s", tournament_name, e)
        raise


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
        import re

        match = re.search(r"contains\('([^']+)'(?:,\s*case=(\w+))?\)", condition)
        if match:
            pattern = match.group(1)
            case_sensitive = match.group(2) != "False" if match.group(2) else True
            return series.str.contains(pattern, case=case_sensitive, na=False)

    if "equals(" in condition:
        # Извлекаем значение для equals
        import re

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

    # Определяем подтурнир для каждого матча (deprecated, но оставлено для совместимости)
    df["subtournament"] = pd.Series(
        np.select(
            [
                df["tour_name_en"].str.contains("stream 1", case=False, na=False),
                df["tour_name_en"].str.contains("stream 2", case=False, na=False),
            ],
            ["kz_1", "kz_2"],
            default="cz",
        ),
        index=df.index,
    )

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


def load_bookmaker_config(bookmaker: str) -> DictConfig | None:
    """Загрузить конфигурацию букмекера.

    Args:
        bookmaker: Название букмекера (например: 'fonbet', 'sdf')

    Returns:
        DictConfig с конфигурацией букмекера или None если не найден

    Note:
        Конфигурация загружается из conf/bookmaker/{bookmaker}.yaml
    """
    config_dir = str((PROJECT_ROOT / "conf").resolve())
    bookmaker_config_path = PROJECT_ROOT / "conf" / "bookmaker" / f"{bookmaker}.yaml"

    if not bookmaker_config_path.exists():
        logger.warning("Конфиг букмекера %s не найден: %s", bookmaker, bookmaker_config_path)
        return None

    try:
        with initialize_config_dir(config_dir=config_dir, version_base="1.3"):
            return compose(  # type: ignore[no-any-return]
                config_name=f"bookmaker/{bookmaker}",
                return_hydra_config=False,
            )
    except Exception as e:
        logger.error("Ошибка загрузки конфига букмекера %s: %s", bookmaker, e)
        return None


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

    # Парсим коэффициенты векторизованно
    mask = df[odds_column].notna()
    odds_list = [
        {
            **parse_odds_from_dict(odds_str, bookmaker, bookmaker_cfg),
            "id": match_id,
            "bookmaker": bookmaker,
        }
        for odds_str, match_id in zip(df.loc[mask, odds_column], df.loc[mask, "id"], strict=False)
        if parse_odds_from_dict(odds_str, bookmaker, bookmaker_cfg)  # Пропускаем пустые результаты
    ]

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

        # БИЗНЕС-ЛОГИКА: Разделение источников на подтурниры (если задано в конфиге)
        try:
            source_config = load_source_config(tournament_name)

            if hasattr(source_config, "split_strategy") and source_config.split_strategy.get(
                "enabled"
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

        except FileNotFoundError:
            # Конфиг источника не найден - значит это простой турнир без split логики
            logger.debug(
                "Конфиг источника %s не найден, обрабатываю как обычный турнир", tournament_name
            )

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

        # Сохраняем odds.parquet (если есть конфигурация в турнире)
        try:
            tournament_config = load_tournament_config(tournament_name)
            if (
                hasattr(tournament_config, "data")
                and hasattr(tournament_config.data, "odds_feed")
                and tournament_config.data.odds_feed.get("enabled")
            ):
                save_odds_if_available(
                    df,
                    tournament_name,
                    output_parquet.parent,
                    odds_column=tournament_config.data.odds_feed.get("column"),
                    bookmaker=tournament_config.data.odds_feed.get("bookmaker"),
                )
        except FileNotFoundError:
            logger.debug("Конфиг турнира %s не найден, пропускаю odds", tournament_name)

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
    config_dir = str((PROJECT_ROOT / "conf").resolve())
    with initialize_config_dir(config_dir=config_dir, version_base="1.3"):
        paths_cfg = compose(config_name="paths", return_hydra_config=False)

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
