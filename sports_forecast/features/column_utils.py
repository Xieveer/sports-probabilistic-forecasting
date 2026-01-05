"""
Утилиты для работы с колонками датафрейма.

Определяет категории колонок и предоставляет функции для их фильтрации.

Категории колонок:
    - META: Служебные колонки (id, datetime, tournament, status, etc.)
    - SOURCE: Исходные колонки после clean (home_points, away_points, etc.)
    - FEATURE: Генерируемые фичи (префикс f_)
    - TARGET: Целевые переменные для обучения (префикс target_)

Примеры:
    >>> df = pd.DataFrame({
    ...     'id': [1, 2],
    ...     'datetime': ['2024-01-01', '2024-01-02'],
    ...     'home_points': [10, 12],
    ...     'away_points': [8, 9],
    ...     'f_pl_global_ewm_10': [0.5, 0.6],
    ...     'target_home_win': [1, 1]
    ... })
    >>> get_feature_columns(df)
    ['f_pl_global_ewm_10']
    >>> get_meta_columns(df)
    ['id', 'datetime']
"""

import pandas as pd


# Префиксы для категорий колонок
FEATURE_PREFIX = "f_"
TARGET_PREFIX = "target_"

# Мета-колонки (служебные, не участвуют в обучении)
META_COLUMNS = {
    # Общие идентификаторы
    "id",
    "datetime",
    "tournament",
    "status",
    # Long format специфичные
    "pl",  # player (текущий игрок в строке)
    "opp",  # opponent
    "side",  # 'h' или 'a'
    "is_home",  # 1 или 0
    # Wide format специфичные
    "home_name",
    "away_name",
    "home_team",
    "away_team",
    # Турнирные мета-данные
    "tour_name",
    "tour_name_en",
    "tour_name_g",
}


def get_feature_columns(df: pd.DataFrame) -> list[str]:
    """
    Получить все колонки-фичи (с префиксом f_).

    Args:
        df: Датафрейм

    Returns:
        Список имен колонок-фичей

    Examples:
        >>> df = pd.DataFrame({'f_ewm_10': [1], 'id': [1], 'f_count': [2]})
        >>> get_feature_columns(df)
        ['f_ewm_10', 'f_count']
    """
    return [col for col in df.columns if col.startswith(FEATURE_PREFIX)]


def get_meta_columns(df: pd.DataFrame) -> list[str]:
    """
    Получить все мета-колонки (служебные).

    Args:
        df: Датафрейм

    Returns:
        Список имен мета-колонок

    Examples:
        >>> df = pd.DataFrame({'id': [1], 'datetime': ['2024-01-01'], 'f_feat': [0.5]})
        >>> get_meta_columns(df)
        ['id', 'datetime']
    """
    return [col for col in df.columns if col in META_COLUMNS]


def get_target_columns(df: pd.DataFrame) -> list[str]:
    """
    Получить все таргет-колонки (с префиксом target_).

    Args:
        df: Датафрейм

    Returns:
        Список имен таргет-колонок

    Examples:
        >>> df = pd.DataFrame({'target_home_win': [1], 'f_feat': [0.5]})
        >>> get_target_columns(df)
        ['target_home_win']
    """
    return [col for col in df.columns if col.startswith(TARGET_PREFIX)]


def get_source_columns(df: pd.DataFrame) -> list[str]:
    """
    Получить исходные колонки (не мета, не фичи, не таргеты).

    Это колонки, которые пришли из clean.py и используются для генерации фичей.
    Например: home_points, away_points, pl_points, opp_points, tour_num, weekday.

    Args:
        df: Датафрейм

    Returns:
        Список имен исходных колонок

    Examples:
        >>> df = pd.DataFrame({
        ...     'id': [1],
        ...     'home_points': [10],
        ...     'f_ewm': [0.5],
        ...     'target_win': [1]
        ... })
        >>> get_source_columns(df)
        ['home_points']
    """
    features = get_feature_columns(df)
    meta = get_meta_columns(df)
    targets = get_target_columns(df)
    exclude = set(features + meta + targets)
    return [col for col in df.columns if col not in exclude]


def add_feature_prefix(name: str) -> str:
    """
    Добавить префикс f_ к имени фичи (если его еще нет).

    Args:
        name: Имя фичи

    Returns:
        Имя с префиксом f_

    Examples:
        >>> add_feature_prefix('ewm_10')
        'f_ewm_10'
        >>> add_feature_prefix('f_ewm_10')
        'f_ewm_10'
    """
    if name.startswith(FEATURE_PREFIX):
        return name
    return f"{FEATURE_PREFIX}{name}"


def remove_feature_prefix(name: str) -> str:
    """
    Убрать префикс f_ из имени фичи.

    Args:
        name: Имя фичи с префиксом

    Returns:
        Имя без префикса

    Examples:
        >>> remove_feature_prefix('f_ewm_10')
        'ewm_10'
        >>> remove_feature_prefix('ewm_10')
        'ewm_10'
    """
    if name.startswith(FEATURE_PREFIX):
        return name[len(FEATURE_PREFIX) :]
    return name


def add_target_prefix(name: str) -> str:
    """
    Добавить префикс target_ к имени таргета (если его еще нет).

    Args:
        name: Имя таргета

    Returns:
        Имя с префиксом target_

    Examples:
        >>> add_target_prefix('home_win')
        'target_home_win'
        >>> add_target_prefix('target_home_win')
        'target_home_win'
    """
    if name.startswith(TARGET_PREFIX):
        return name
    return f"{TARGET_PREFIX}{name}"


def remove_target_prefix(name: str) -> str:
    """
    Убрать префикс target_ из имени таргета.

    Args:
        name: Имя таргета с префиксом

    Returns:
        Имя без префикса

    Examples:
        >>> remove_target_prefix('target_home_win')
        'home_win'
        >>> remove_target_prefix('home_win')
        'home_win'
    """
    if name.startswith(TARGET_PREFIX):
        return name[len(TARGET_PREFIX) :]
    return name


def filter_feature_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Оставить только колонки-фичи.

    Args:
        df: Датафрейм

    Returns:
        Датафрейм только с фичами

    Examples:
        >>> df = pd.DataFrame({'id': [1], 'f_ewm': [0.5], 'f_count': [2]})
        >>> filter_feature_columns(df).columns.tolist()
        ['f_ewm', 'f_count']
    """
    return df[get_feature_columns(df)]


def exclude_feature_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Исключить колонки-фичи (оставить мета + source + targets).

    Args:
        df: Датафрейм

    Returns:
        Датафрейм без фичей

    Examples:
        >>> df = pd.DataFrame({'id': [1], 'home_points': [10], 'f_ewm': [0.5]})
        >>> exclude_feature_columns(df).columns.tolist()
        ['id', 'home_points']
    """
    feature_cols = get_feature_columns(df)
    return df[[col for col in df.columns if col not in feature_cols]]


def validate_required_columns(df: pd.DataFrame, required: list[str]) -> None:
    """
    Проверить наличие обязательных колонок в датафрейме.

    Args:
        df: Датафрейм
        required: Список обязательных колонок

    Raises:
        ValueError: Если какая-то обязательная колонка отсутствует

    Examples:
        >>> df = pd.DataFrame({'id': [1], 'datetime': ['2024-01-01']})
        >>> validate_required_columns(df, ['id', 'datetime'])  # OK
        >>> validate_required_columns(df, ['id', 'missing'])  # Raises ValueError
        Traceback (most recent call last):
        ...
        ValueError: Отсутствуют обязательные колонки: ['missing']
    """
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise ValueError(f"Отсутствуют обязательные колонки: {missing}")
