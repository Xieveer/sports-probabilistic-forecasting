"""
Трансформация датафрейма между wide и long форматами.

Wide format: один матч = одна строка (home vs away)
Long format: один матч = две строки (player vs opponent)

Wide format используется для:
    - Моделей тотала (total_over_X, total_under_X)
    - Хранения исходных данных

Long format используется для:
    - Моделей победителя (is_home_win, is_away_win)
    - Генерации фичей на основе истории игрока

Примеры:
    Wide → Long:
    
    id | datetime   | home_name | away_name | home_points | away_points | tour_num
    1  | 2024-01-01 | Team A    | Team B    | 10          | 8           | 5
    
    →
    
    id | datetime   | pl     | opp    | pl_points | opp_points | side | is_home | tour_num
    1  | 2024-01-01 | Team A | Team B | 10        | 8          | h    | 1       | 5
    1  | 2024-01-01 | Team B | Team A | 8         | 10         | a    | 0       | 5
"""

from typing import Dict, List, Optional

import pandas as pd

from sports_forecast.utils.log_config import get_logger

logger = get_logger(__name__)


def wide_to_long(
    df: pd.DataFrame,
    home_prefix: str = "home_",
    away_prefix: str = "away_",
    player_name: str = "pl",
    opponent_name: str = "opp",
    context_columns: Optional[List[str]] = None,
) -> pd.DataFrame:
    """
    Трансформация wide → long format.

    Разворачивает один матч (home vs away) в две строки (player vs opponent).

    Args:
        df: Wide format датафрейм
        home_prefix: Префикс для колонок хозяев (default: "home_")
        away_prefix: Префикс для колонок гостей (default: "away_")
        player_name: Имя для колонки текущего игрока (default: "pl")
        opponent_name: Имя для колонки оппонента (default: "opp")
        context_columns: Колонки контекста (tour_num, weekday, etc.), которые
                        копируются в обе строки без изменений

    Returns:
        Long format датафрейм (в 2 раза больше строк)

    Examples:
        >>> df = pd.DataFrame({
        ...     'id': [1],
        ...     'datetime': ['2024-01-01'],
        ...     'home_name': ['Team A'],
        ...     'away_name': ['Team B'],
        ...     'home_points': [10],
        ...     'away_points': [8],
        ...     'tour_num': [5]
        ... })
        >>> long = wide_to_long(df, context_columns=['tour_num'])
        >>> len(long)
        2
        >>> long.loc[long['side'] == 'h', 'pl'].iloc[0]
        'Team A'
    """
    if context_columns is None:
        context_columns = []

    # Найти колонки с префиксами home_ и away_
    home_cols = [col for col in df.columns if col.startswith(home_prefix)]
    away_cols = [col for col in df.columns if col.startswith(away_prefix)]

    # Убрать префиксы для создания общих имен (home_points → points)
    base_home_cols = {col: col[len(home_prefix) :] for col in home_cols}
    base_away_cols = {col: col[len(away_prefix) :] for col in away_cols}

    # Найти общие колонки (которые есть и у home, и у away)
    common_base = set(base_home_cols.values()) & set(base_away_cols.values())

    if not common_base:
        raise ValueError(
            f"Не найдено общих колонок для home и away. "
            f"Home колонки: {list(base_home_cols.values())}, "
            f"Away колонки: {list(base_away_cols.values())}"
        )

    logger.debug(
        f"Трансформация wide → long: найдено {len(common_base)} общих атрибутов: "
        f"{sorted(common_base)}"
    )

    # Колонки, которые остаются без изменений (id, datetime, status, etc.)
    meta_cols = [
        col
        for col in df.columns
        if col not in home_cols
        and col not in away_cols
        and col not in context_columns
    ]

    # Создаем строки для home (side='h', is_home=1)
    home_rows = df[meta_cols + context_columns].copy()
    home_rows["side"] = "h"
    home_rows["is_home"] = 1

    for base_name in common_base:
        home_col = f"{home_prefix}{base_name}"
        away_col = f"{away_prefix}{base_name}"
        home_rows[f"{player_name}_{base_name}"] = df[home_col]
        home_rows[f"{opponent_name}_{base_name}"] = df[away_col]

    # Создаем строки для away (side='a', is_home=0)
    away_rows = df[meta_cols + context_columns].copy()
    away_rows["side"] = "a"
    away_rows["is_home"] = 0

    for base_name in common_base:
        home_col = f"{home_prefix}{base_name}"
        away_col = f"{away_prefix}{base_name}"
        # Меняем местами: для away игрока pl=away, opp=home
        away_rows[f"{player_name}_{base_name}"] = df[away_col]
        away_rows[f"{opponent_name}_{base_name}"] = df[home_col]

    # Объединяем
    long = pd.concat([home_rows, away_rows], ignore_index=True)

    # Сортируем по datetime и id для правильной последовательности
    if "datetime" in long.columns and "id" in long.columns:
        long = long.sort_values(
            by=["datetime", "id", "side"], ascending=[True, False, False]
        ).reset_index(drop=True)

    logger.info(
        f"Wide → Long: {len(df)} матчей → {len(long)} строк "
        f"({len(common_base)} атрибутов: {sorted(common_base)})"
    )

    return long


def long_to_wide(
    df: pd.DataFrame,
    player_prefix: str = "pl_",
    opponent_prefix: str = "opp_",
    home_prefix: str = "home_",
    away_prefix: str = "away_",
    aggregate_features: bool = True,
) -> pd.DataFrame:
    """
    Трансформация long → wide format.

    Сворачивает две строки (player vs opponent) в одну (home vs away).

    Args:
        df: Long format датафрейм
        player_prefix: Префикс колонок игрока (default: "pl_")
        opponent_prefix: Префикс колонок оппонента (default: "opp_")
        home_prefix: Префикс для хозяев в wide (default: "home_")
        away_prefix: Префикс для гостей в wide (default: "away_")
        aggregate_features: Агрегировать ли фичи (для home берем side='h',
                           для away берем side='a')

    Returns:
        Wide format датафрейм (в 2 раза меньше строк)

    Examples:
        >>> long = pd.DataFrame({
        ...     'id': [1, 1],
        ...     'datetime': ['2024-01-01', '2024-01-01'],
        ...     'pl_name': ['Team A', 'Team B'],
        ...     'opp_name': ['Team B', 'Team A'],
        ...     'pl_points': [10, 8],
        ...     'opp_points': [8, 10],
        ...     'side': ['h', 'a'],
        ...     'is_home': [1, 0]
        ... })
        >>> wide = long_to_wide(long)
        >>> len(wide)
        1
        >>> wide['home_name'].iloc[0]
        'Team A'
    """
    if "side" not in df.columns or "id" not in df.columns:
        raise ValueError("Long format должен содержать колонки 'side' и 'id'")

    # Разделяем на home и away строки
    home_df = df[df["side"] == "h"].copy()
    away_df = df[df["side"] == "a"].copy()

    if len(home_df) == 0 or len(away_df) == 0:
        raise ValueError("Long format должен содержать строки для side='h' и side='a'")

    # Мета-колонки (id, datetime, tournament, status, etc.)
    meta_cols = [
        col
        for col in df.columns
        if not col.startswith(player_prefix)
        and not col.startswith(opponent_prefix)
        and col not in ["side", "is_home"]
    ]

    # Начинаем с мета-колонок из home строк
    wide = home_df[meta_cols].copy()

    # Колонки с префиксами pl_ и opp_
    pl_cols = [col for col in df.columns if col.startswith(player_prefix)]
    opp_cols = [col for col in df.columns if col.startswith(opponent_prefix)]

    # Переименовываем pl_ → home_, opp_ → away_ для home строк
    for col in pl_cols:
        base_name = col[len(player_prefix) :]
        wide[f"{home_prefix}{base_name}"] = home_df[col].values

    for col in opp_cols:
        base_name = col[len(opponent_prefix) :]
        wide[f"{away_prefix}{base_name}"] = home_df[col].values

    # Если нужно агрегировать фичи (с префиксом f_), добавляем их из обеих строк
    if aggregate_features:
        feature_cols = [col for col in df.columns if col.startswith("f_")]

        for col in feature_cols:
            # Для home берем значение из home строки
            if col in home_df.columns:
                wide[f"{home_prefix}{col}"] = home_df[col].values

            # Для away берем значение из away строки
            if col in away_df.columns:
                # Убедимся что порядок id совпадает
                away_aligned = away_df.set_index("id").reindex(home_df["id"].values)
                wide[f"{away_prefix}{col}"] = away_aligned[col].values

    logger.info(f"Long → Wide: {len(df)} строк → {len(wide)} матчей")

    return wide


def create_player_metrics(
    df: pd.DataFrame, metrics: List[str], player_col: str = "pl"
) -> pd.DataFrame:
    """
    Создать метрики для long format (diff_ps, total_ps, etc.).

    Эти метрики используются как базовые для генерации фичей.

    Args:
        df: Long format датафрейм
        metrics: Список метрик для создания ('diff', 'total')
        player_col: Имя колонки игрока (default: "pl")

    Returns:
        Датафрейм с добавленными метриками

    Examples:
        >>> df = pd.DataFrame({
        ...     'pl_points': [10, 8],
        ...     'opp_points': [8, 10]
        ... })
        >>> df = create_player_metrics(df, metrics=['diff', 'total'])
        >>> df['diff_ps'].tolist()
        [2, -2]
        >>> df['total_ps'].tolist()
        [18, 18]
    """
    result = df.copy()

    if "diff" in metrics:
        # Разница очков (pl - opp)
        if "pl_points" in df.columns and "opp_points" in df.columns:
            result["diff_ps"] = df["pl_points"] - df["opp_points"]
            logger.debug("Создана метрика: diff_ps = pl_points - opp_points")

    if "total" in metrics:
        # Сумма очков
        if "pl_points" in df.columns and "opp_points" in df.columns:
            result["total_ps"] = df["pl_points"] + df["opp_points"]
            logger.debug("Создана метрика: total_ps = pl_points + opp_points")

    return result


def validate_long_format(df: pd.DataFrame) -> None:
    """
    Валидация long format датафрейма.

    Проверяет:
    - Наличие обязательных колонок (id, datetime, pl, opp, side, is_home)
    - Корректность значений side ('h' или 'a')
    - Корректность значений is_home (0 или 1)
    - Соответствие side и is_home

    Args:
        df: Long format датафрейм

    Raises:
        ValueError: Если формат некорректен

    Examples:
        >>> df = pd.DataFrame({
        ...     'id': [1, 1],
        ...     'datetime': ['2024-01-01', '2024-01-01'],
        ...     'pl_name': ['A', 'B'],
        ...     'opp_name': ['B', 'A'],
        ...     'side': ['h', 'a'],
        ...     'is_home': [1, 0]
        ... })
        >>> validate_long_format(df)  # OK
    """
    required_cols = ["id", "datetime", "side", "is_home"]
    missing = [col for col in required_cols if col not in df.columns]
    if missing:
        raise ValueError(f"Long format: отсутствуют обязательные колонки: {missing}")

    # Проверка side
    valid_sides = {"h", "a"}
    invalid_sides = set(df["side"].unique()) - valid_sides
    if invalid_sides:
        raise ValueError(
            f"Long format: некорректные значения side: {invalid_sides}. "
            f"Допустимы только: {valid_sides}"
        )

    # Проверка is_home
    valid_is_home = {0, 1}
    invalid_is_home = set(df["is_home"].unique()) - valid_is_home
    if invalid_is_home:
        raise ValueError(
            f"Long format: некорректные значения is_home: {invalid_is_home}. "
            f"Допустимы только: {valid_is_home}"
        )

    # Проверка соответствия side и is_home
    mismatches = df[(df["side"] == "h") & (df["is_home"] != 1)]
    if len(mismatches) > 0:
        raise ValueError(
            f"Long format: найдено {len(mismatches)} строк где side='h' но is_home!=1"
        )

    mismatches = df[(df["side"] == "a") & (df["is_home"] != 0)]
    if len(mismatches) > 0:
        raise ValueError(
            f"Long format: найдено {len(mismatches)} строк где side='a' но is_home!=0"
        )

    logger.debug(f"Long format валидация пройдена: {len(df)} строк")

