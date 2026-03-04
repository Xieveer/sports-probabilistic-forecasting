"""
Генератор временных фичей (TimeFeatureGenerator).

Извлекает признаки из колонки ``datetime``:
- weekday (день недели 0-6)
- hour (час 0-23)
- is_weekend (выходной: 0/1)
- time_of_day (категория: night/morning/day/evening → 0-3)
- month (месяц 1-12)

Важно:
    TimeFeatureGenerator — «пре-генератор».  Он запускается на WIDE данных
    ДО преобразования wide → long, а сгенерированные колонки автоматически
    добавляются в ``long_format_context_columns`` для переноса в long формат.

Пример конфига (conf/features/generators/time/default.yaml):

    type: "time"
    enabled: true
    datetime_column: "datetime"
    features:
      - weekday
      - hour
      - is_weekend
      - time_of_day
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from sports_forecast.features.generators.base import BaseFeatureGenerator
from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)


# Маппинг час → время суток (0-night, 1-morning, 2-day, 3-evening)
_HOUR_TO_TIME_OF_DAY = {
    **dict.fromkeys(range(0, 6), 0),  # night   00-05
    **dict.fromkeys(range(6, 12), 1),  # morning 06-11
    **dict.fromkeys(range(12, 18), 2),  # day     12-17
    **dict.fromkeys(range(18, 24), 3),  # evening 18-23
}


class TimeFeatureGenerator(BaseFeatureGenerator):
    """Генератор временных признаков из datetime.

    Конфиг:
        type: "time"
        enabled: true
        datetime_column: "datetime"     # колонка-источник
        features:                       # какие фичи генерировать
          - weekday
          - hour
          - is_weekend
          - time_of_day
          - month

    Все указанные фичи создаются как int-колонки.

    Attributes:
        datetime_column: Имя колонки с datetime.
        requested_features: Список запрошенных фичей.
    """

    # Допустимые имена фичей
    SUPPORTED_FEATURES = frozenset({"weekday", "hour", "is_weekend", "time_of_day", "month"})

    def __init__(self, config: dict[str, Any]) -> None:
        self.datetime_column: str = config.get("datetime_column", "datetime")
        self.requested_features: list[str] = list(config.get("features", ["weekday", "hour"]))
        super().__init__(config)

    # ------------------------------------------------------------------
    # BaseFeatureGenerator interface
    # ------------------------------------------------------------------

    def validate_config(self) -> None:
        """Проверить корректность конфига."""
        super().validate_config()
        unknown = set(self.requested_features) - self.SUPPORTED_FEATURES
        if unknown:
            raise ValueError(
                f"{self.name}: неизвестные фичи {unknown}. "
                f"Доступные: {sorted(self.SUPPORTED_FEATURES)}"
            )

    def generate(self, df: pd.DataFrame) -> pd.DataFrame:
        """Сгенерировать временные колонки.

        Args:
            df: Датафрейм (wide или long), содержащий ``datetime_column``.

        Returns:
            Копия датафрейма с добавленными колонками.
        """
        df = df.copy()

        if self.datetime_column not in df.columns:
            logger.warning(
                "%s: колонка '%s' не найдена, пропускаю генерацию",
                self.name,
                self.datetime_column,
            )
            return df

        dt_series = pd.to_datetime(df[self.datetime_column], errors="coerce")

        for feat in self.requested_features:
            if feat == "weekday":
                df["weekday"] = dt_series.dt.dayofweek.astype("Int64")
            elif feat == "hour":
                df["hour"] = dt_series.dt.hour.astype("Int64")
            elif feat == "is_weekend":
                df["is_weekend"] = (dt_series.dt.dayofweek >= 5).astype("Int64")
            elif feat == "time_of_day":
                df["time_of_day"] = dt_series.dt.hour.map(_HOUR_TO_TIME_OF_DAY).astype("Int64")
            elif feat == "month":
                df["month"] = dt_series.dt.month.astype("Int64")

        logger.info(
            "%s: сгенерировано %d фичей из '%s': %s",
            self.name,
            len(self.requested_features),
            self.datetime_column,
            self.requested_features,
        )
        return df

    def get_feature_names(self) -> list[str]:
        """Имена фичей (без префикса f_).

        Returns:
            Список имён генерируемых колонок.
        """
        return list(self.requested_features)

    # ------------------------------------------------------------------
    # Дополнительный API для pipeline
    # ------------------------------------------------------------------

    def get_context_column_names(self) -> list[str]:
        """Колонки, которые нужно включить в long_format_context_columns.

        Те же колонки, что и feature_names, поскольку временные
        признаки используются как ключи группировки (EWM/Count).

        Returns:
            Список имён контекстных колонок.
        """
        return list(self.requested_features)
