"""
Target Computation Module для архитектуры v2.0.

Вычисление таргетов на основе MarketSpec вместо старых target_sources.

Поддерживаемые способы задания таргета:
    1. **target_source_key** (новая архитектура) — ссылка на
       ``tournament.target_sources.<key>`` с ``comparison`` и колонками.
    2. **formula** (декларативная формула) — строка вида
       ``"col_a > col_b"`` или ``"(col_a + col_b) > {line}"``.
       Обрабатывается безопасным парсером ``FormulaTargetBuilder``
       (без использования ``eval()``).
    3. **market_family** (старая архитектура) — switch по типу маркета
       (``winner``, ``total``, ``handicap``).
"""

from __future__ import annotations

import re
from typing import Any

import pandas as pd
from omegaconf import DictConfig

from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)


class TargetComputationError(Exception):
    """Ошибка при вычислении таргета."""

    pass


# ─────────────────────────────────────────────────────────────────────────────
# Formula-based Target Builder (safe, no eval())
# ─────────────────────────────────────────────────────────────────────────────

# Допустимые операторы сравнения
_COMPARISON_OPS: dict[str, str] = {
    ">": "gt",
    "<": "lt",
    ">=": "ge",
    "<=": "le",
    "==": "eq",
    "!=": "ne",
}

# Допустимые арифметические операторы
_ARITH_OPS = {"+", "-", "*", "/"}

# Regex для разбора формулы: left_expr COMP right_expr
_FORMULA_RE = re.compile(r"^(?P<left>.+?)\s*(?P<op>>=|<=|!=|==|>|<)\s*(?P<right>.+)$")


class FormulaTargetBuilder:
    """Безопасный вычислитель формул для таргетов.

    Парсит декларативную формулу и вычисляет бинарный таргет
    без использования ``eval()``.

    Поддерживаемые форматы формул::

        "col_a > col_b"
        "(col_a + col_b) > 6.5"
        "col_a - col_b >= {line}"
        "col_a > 0"

    Placeholder ``{line}`` подставляется из параметра ``line``.

    Args:
        formula: Строка формулы.
        line: Значение линии для подстановки ``{line}`` (опционально).

    Examples:
        >>> builder = FormulaTargetBuilder("pl_points > opp_points")
        >>> target = builder.compute(df)

        >>> builder = FormulaTargetBuilder("(pl_points + opp_points) > {line}", line=6.5)
        >>> target = builder.compute(df)
    """

    def __init__(self, formula: str, line: float | None = None) -> None:
        self.raw_formula = formula
        self.line = line

        # Подставляем {line} если есть
        resolved = formula
        if "{line}" in formula:
            if line is None:
                raise TargetComputationError(
                    f"Формула '{formula}' содержит {{line}}, но line не указан"
                )
            resolved = formula.replace("{line}", str(line))

        self.formula = resolved.strip()
        self._left_expr: str = ""
        self._right_expr: str = ""
        self._op: str = ""
        self._parse()

    def _parse(self) -> None:
        """Разобрать формулу на left, op, right."""
        match = _FORMULA_RE.match(self.formula)
        if not match:
            raise TargetComputationError(
                f"Невалидная формула: '{self.formula}'. "
                "Ожидается формат: 'expr OPERATOR expr' "
                f"(операторы: {list(_COMPARISON_OPS.keys())})"
            )
        self._left_expr = match.group("left").strip()
        self._op = match.group("op").strip()
        self._right_expr = match.group("right").strip()

    def compute(self, df: pd.DataFrame) -> pd.Series:
        """Вычислить бинарный таргет по формуле.

        Args:
            df: DataFrame с данными.

        Returns:
            Series с бинарным таргетом (0/1).

        Raises:
            TargetComputationError: Если вычисление невозможно.
        """
        left_val = self._eval_expr(df, self._left_expr)
        right_val = self._eval_expr(df, self._right_expr)

        op_name = _COMPARISON_OPS.get(self._op)
        if op_name is None:
            raise TargetComputationError(f"Неподдерживаемый оператор: '{self._op}'")

        # Применяем оператор сравнения
        comparison_fn = getattr(left_val, op_name, None)
        if comparison_fn is None:
            # Fallback для скаляров
            comparison_fn = getattr(pd.Series(left_val), op_name)

        result = comparison_fn(right_val)
        return pd.Series(result.astype(int))

    def _eval_expr(self, df: pd.DataFrame, expr: str) -> Any:
        """Вычислить арифметическое выражение (безопасно).

        Поддерживает:
            - Ссылки на колонки: ``col_name``
            - Числовые литералы: ``6.5``, ``-1``
            - Бинарные арифметические операции: ``col_a + col_b``

        Args:
            df: DataFrame.
            expr: Строковое выражение.

        Returns:
            pd.Series или float.
        """
        expr = expr.strip().strip("()")

        # 1. Попробуем как число
        try:
            return float(expr)
        except ValueError:
            pass

        # 2. Попробуем как бинарную арифметическую операцию
        for op_char in _ARITH_OPS:
            # Ищем оператор не внутри скобок
            parts = self._split_by_operator(expr, op_char)
            if parts is not None:
                left_val = self._eval_expr(df, parts[0])
                right_val = self._eval_expr(df, parts[1])
                if op_char == "+":
                    return left_val + right_val
                if op_char == "-":
                    return left_val - right_val
                if op_char == "*":
                    return left_val * right_val
                if op_char == "/":
                    return left_val / right_val

        # 3. Как имя колонки
        if expr in df.columns:
            return df[expr]

        raise TargetComputationError(
            f"Невозможно вычислить выражение: '{expr}'. "
            f"Это не число и не колонка DataFrame. "
            f"Доступные колонки: {list(df.columns)[:20]}..."
        )

    @staticmethod
    def _split_by_operator(expr: str, op: str) -> tuple[str, str] | None:
        """Разделить выражение по оператору (вне скобок).

        Args:
            expr: Выражение.
            op: Оператор для поиска.

        Returns:
            Кортеж (left, right) или None.
        """
        depth = 0
        for i, ch in enumerate(expr):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            elif ch == op and depth == 0 and i > 0:
                left = expr[:i].strip()
                right = expr[i + 1 :].strip()
                if left and right:
                    return (left, right)
        return None

    def get_referenced_columns(self, df: pd.DataFrame) -> list[str]:
        """Получить список колонок, на которые ссылается формула.

        Args:
            df: DataFrame для проверки наличия колонок.

        Returns:
            Список имён колонок.
        """
        # Извлекаем все слова из формулы и проверяем наличие в df
        tokens = re.findall(r"[a-zA-Z_]\w*", self.formula)
        return [t for t in tokens if t in df.columns]

    def __repr__(self) -> str:
        return f"FormulaTargetBuilder('{self.raw_formula}', line={self.line})"


def _compute_target_from_source(
    df: pd.DataFrame,
    market_spec: DictConfig,
    tournament_cfg: DictConfig,
    line: float | None = None,
) -> pd.Series:
    """
    Вычислить таргет используя target_sources из tournament config (НОВАЯ АРХИТЕКТУРА).

    Args:
        df: DataFrame с данными
        market_spec: cfg.market_spec конфигурация
        tournament_cfg: cfg.tournament конфигурация
        line: Линия для total/handicap markets

    Returns:
        Series с бинарным таргетом (0/1)

    Raises:
        TargetComputationError: Если вычисление невозможно
    """
    target_source_key = market_spec.target_source_key
    target_name = market_spec.get("target_name", "target")
    data_format = market_spec.data_format

    if not hasattr(tournament_cfg, "target_sources"):
        raise TargetComputationError(
            f"tournament '{tournament_cfg.name}' не содержит target_sources"
        )

    if target_source_key not in tournament_cfg.target_sources:
        available = list(tournament_cfg.target_sources.keys())
        raise TargetComputationError(
            f"target_source_key '{target_source_key}' не найден в tournament.target_sources. "
            f"Доступные: {available}"
        )

    target_spec = tournament_cfg.target_sources[target_source_key]
    comparison = target_spec.comparison

    # Получаем колонки в зависимости от формата
    if target_spec.format == "long":
        col_a = target_spec.player_column
        col_b = target_spec.opponent_column
    else:  # wide
        col_a = target_spec.home_column
        col_b = target_spec.away_column

    # Проверяем наличие колонок
    for col in [col_a, col_b]:
        if col not in df.columns:
            raise TargetComputationError(
                f"Колонка '{col}' не найдена в датафрейме. Доступные: {list(df.columns)[:20]}..."
            )

    # Вычисляем таргет
    if comparison == "greater":
        target = (df[col_a] > df[col_b]).astype(int)
        logger.info(
            "✓ Таргет '%s': %s > %s, format=%s, positive_rate=%.2f%%",
            target_name,
            col_a,
            col_b,
            data_format,
            target.mean() * 100,
        )
    elif comparison == "total_over":
        if line is None:
            line = market_spec.get("line")
        if line is None or line == "???":
            raise TargetComputationError("Line обязательна для total_over!")
        target = ((df[col_a] + df[col_b]) > line).astype(int)
        logger.info(
            "✓ Таргет '%s': (%s + %s) > %.1f, format=%s, positive_rate=%.2f%%",
            target_name,
            col_a,
            col_b,
            line,
            data_format,
            target.mean() * 100,
        )
    elif comparison == "total_under":
        if line is None:
            line = market_spec.get("line")
        if line is None:
            raise TargetComputationError("Line обязательна для total_under!")
        target = ((df[col_a] + df[col_b]) < line).astype(int)
        logger.info(
            "✓ Таргет '%s': (%s + %s) < %.1f, format=%s, positive_rate=%.2f%%",
            target_name,
            col_a,
            col_b,
            line,
            data_format,
            target.mean() * 100,
        )
    else:
        raise TargetComputationError(f"Неизвестный comparison: {comparison}")

    return target  # type: ignore[no-any-return]


def compute_target_from_market_spec(
    df: pd.DataFrame,
    market_spec: DictConfig,
    tournament_cfg: DictConfig | None = None,
    line: float | None = None,
) -> pd.Series:
    """
    Вычислить таргет на основе MarketSpec (архитектура v2.0).

    Args:
        df: DataFrame с данными
        market_spec: cfg.market_spec конфигурация
        tournament_cfg: cfg.tournament конфигурация (для target_sources)
        line: Линия для total/handicap markets (override market_spec.line)

    Returns:
        Series с бинарным таргетом (0/1)

    Raises:
        TargetComputationError: Если вычисление невозможно

    Examples:
        >>> # Winner (long format) - НОВАЯ АРХИТЕКТУРА
        >>> target = compute_target_from_market_spec(df, cfg.market_spec, cfg.tournament)

        >>> # Total over 6.5 - НОВАЯ АРХИТЕКТУРА
        >>> target = compute_target_from_market_spec(df, cfg.market_spec, cfg.tournament, line=6.5)
    """
    # НОВАЯ АРХИТЕКТУРА: Используем target_source_key
    if hasattr(market_spec, "target_source_key") and tournament_cfg:
        return _compute_target_from_source(df, market_spec, tournament_cfg, line)

    # СТАРАЯ АРХИТЕКТУРА (для обратной совместимости)
    # Получаем параметры
    market_family = market_spec.market_family
    side = market_spec.get("side")
    data_format = market_spec.data_format

    # Получаем source columns
    if not hasattr(market_spec, "target"):
        raise TargetComputationError(
            f"market_spec '{market_spec.name}' не содержит ни target_source_key, ни target секцию. "
            "Обновите конфиг на новую архитектуру!"
        )

    source_columns = market_spec.target.get("source_columns", [])
    formula = market_spec.target.get("formula")
    target_name = market_spec.target.get("name", "target")

    # ── Formula-based target (если указана формула) ──
    if formula:
        builder = FormulaTargetBuilder(formula, line=line)
        target = builder.compute(df)
        refs = builder.get_referenced_columns(df)
        logger.info(
            "✓ Таргет '%s' (formula): %s, positive_rate=%.2f%%, cols=%s",
            target_name,
            formula,
            target.mean() * 100,
            refs,
        )
        return target  # type: ignore[return-value]

    # Проверяем наличие колонок
    for col in source_columns:
        if col not in df.columns:
            raise TargetComputationError(
                f"Колонка '{col}' не найдена в датафрейме. Доступные: {list(df.columns)[:20]}..."
            )

    # Вычисляем таргет в зависимости от market family
    if market_family == "winner":
        target = _compute_winner_target(df, market_spec)

    elif market_family == "total":
        # Для total обязательна линия
        if line is None:
            line = market_spec.get("line")
        if line is None or line == "???":
            raise TargetComputationError(
                "Line обязательна для total markets! "
                "Укажите market_spec.line=6.5 или передайте параметр line"
            )

        target = _compute_total_target(df, market_spec, line)

    elif market_family == "handicap":
        # Для handicap обязательна линия
        if line is None:
            line = market_spec.get("line")
        if line is None:
            raise TargetComputationError("Line обязательна для handicap markets!")

        target = _compute_handicap_target(df, market_spec, line)

    else:
        raise TargetComputationError(
            f"Неизвестный market_family: {market_family}. Поддерживаются: winner, total, handicap"
        )

    # Логируем
    logger.info(
        "✓ Таргет '%s' вычислен: market=%s, side=%s, format=%s, positive_rate=%.2f%%",
        target_name,
        market_family,
        side,
        data_format,
        target.mean() * 100,
    )

    return target


def _compute_winner_target(df: pd.DataFrame, market_spec: DictConfig) -> pd.Series:
    """
    Вычислить таргет для winner market.

    Args:
        df: DataFrame с данными
        market_spec: MarketSpec конфигурация

    Returns:
        Бинарный таргет (1 = победа, 0 = проигрыш)
    """
    side = market_spec.side
    source_cols = market_spec.target.source_columns

    if side == "home":
        # Победа хозяев: home_points > away_points
        if len(source_cols) != 2:
            raise TargetComputationError(
                f"winner_home требует 2 колонки [home_points, away_points], получено: {source_cols}"
            )
        home_col, away_col = source_cols
        target = (df[home_col] > df[away_col]).astype(int)
        logger.debug("Winner home: %s > %s", home_col, away_col)

    elif side == "away":
        # Победа гостей: away_points > home_points
        if len(source_cols) != 2:
            raise TargetComputationError("winner_away требует 2 колонки [home_points, away_points]")
        home_col, away_col = source_cols
        target = (df[away_col] > df[home_col]).astype(int)
        logger.debug("Winner away: %s > %s", away_col, home_col)

    else:
        raise TargetComputationError(
            f"Неизвестный side для winner: {side}. Поддерживаются: home, away"
        )

    return target  # type: ignore[no-any-return]


def _compute_total_target(df: pd.DataFrame, market_spec: DictConfig, line: float) -> pd.Series:
    """
    Вычислить таргет для total market.

    Args:
        df: DataFrame с данными
        market_spec: MarketSpec конфигурация
        line: Линия тотала (например, 6.5)

    Returns:
        Бинарный таргет (1 = over/under, 0 = иначе)
    """
    side = market_spec.side
    source_cols = market_spec.target.source_columns

    if len(source_cols) != 2:
        raise TargetComputationError(
            f"total markets требуют 2 колонки [home_points, away_points], получено: {source_cols}"
        )

    home_col, away_col = source_cols

    # Вычисляем total
    total = df[home_col] + df[away_col]

    # Применяем comparison
    if side == "over":
        target = (total > line).astype(int)
        logger.debug("Total over %.1f: (%s + %s) > %.1f", line, home_col, away_col, line)

    elif side == "under":
        target = (total < line).astype(int)
        logger.debug("Total under %.1f: (%s + %s) < %.1f", line, home_col, away_col, line)

    else:
        raise TargetComputationError(
            f"Неизвестный side для total: {side}. Поддерживаются: over, under"
        )

    return target  # type: ignore[no-any-return]


def _compute_handicap_target(df: pd.DataFrame, market_spec: DictConfig, line: float) -> pd.Series:
    """
    Вычислить таргет для handicap market.

    Args:
        df: DataFrame с данными
        market_spec: MarketSpec конфигурация
        line: Линия форы (например, -1.5)

    Returns:
        Бинарный таргет
    """
    side = market_spec.side
    source_cols = market_spec.target.source_columns

    if len(source_cols) != 2:
        raise TargetComputationError(
            "handicap markets требуют 2 колонки [home_points, away_points]"
        )

    home_col, away_col = source_cols

    # Применяем фору
    if side == "home":
        # Фора на хозяев: (home + line) > away
        result = df[home_col] + line
        target = (result > df[away_col]).astype(int)
        logger.debug("Handicap home %.1f: (%s + %.1f) > %s", line, home_col, line, away_col)

    elif side == "away":
        # Фора на гостей: (away + line) > home
        result = df[away_col] + line
        target = (result > df[home_col]).astype(int)
        logger.debug("Handicap away %.1f: (%s + %.1f) > %s", line, away_col, line, home_col)

    else:
        raise TargetComputationError(
            f"Неизвестный side для handicap: {side}. Поддерживаются: home, away"
        )

    return target  # type: ignore[no-any-return]


def get_target_name(market_spec: DictConfig, line: float | None = None) -> str:
    """
    Получить имя таргета на основе MarketSpec.

    Args:
        market_spec: cfg.market_spec
        line: Линия (для total/handicap)

    Returns:
        Имя таргета (например, "target_total_over_6.5")

    Examples:
        >>> name = get_target_name(cfg.market_spec, line=6.5)
        >>> # "target_total_over_6.5"
    """
    # НОВАЯ АРХИТЕКТУРА: используем target_name
    if hasattr(market_spec, "target_name"):
        base_name = market_spec.target_name
    # СТАРАЯ АРХИТЕКТУРА: используем target.name
    elif hasattr(market_spec, "target"):
        base_name = market_spec.target.get("name", "target")
    else:
        base_name = "target"

    # Подставляем line если есть placeholder {line} или добавляем line для total/handicap
    market_family = market_spec.get("market_family", "")
    if market_family in ["total", "handicap", "total_withOT"]:
        if line is None:
            line = market_spec.get("line")
        if line is not None:
            # Добавляем линию к имени
            base_name = f"{base_name}_{str(line).replace('.', '_')}"

    return base_name  # type: ignore[no-any-return]
