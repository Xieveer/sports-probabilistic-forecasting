"""
Генератор EWM фичей (Exponentially Weighted Moving Average).

Создает экспоненциально взвешенные скользящие средние по различным контекстам:
- Глобальная форма игрока (global)
- Форма в зависимости от состояния (match_state)
- Форма в зависимости от времени суток (weekday)
- Head-to-head форма (h2h)
- И т.д.

Для каждого контекста генерируются фичи для разных размеров окна (spans).

Генерирует:
- pl_global_ewm_10, pl_global_ewm_20, ...: EWM для игрока
- opp_global_ewm_10, opp_global_ewm_20, ...: EWM для оппонента
- all_global_ewm_10_diff, ...: Разница EWM между игроками
- h2h_ewm_10_diff, ...: Head-to-head EWM
"""

from typing import Any

import pandas as pd

from sports_forecast.features.generators.base import BaseFeatureGenerator
from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)


class EWMFeatureGenerator(BaseFeatureGenerator):
    """
    Генератор экспоненциально взвешенных скользящих средних.

    Пример конфига:
        type: "ewm"
        enabled: true
        metric: "diff_ps"  # Колонка с метрикой (pl_points - opp_points)
        spans: [5, 10, 20, 50, 100, 150, 200]
        shift: 1
        min_periods: 3
        adjust: false

        contexts:
          # Глобальная форма игрока
          - name: "global"
            keys: ["pl"]
            players: ["pl", "opp"]
            compute_diff: true

          # Форма в зависимости от match_state
          - name: "match_state"
            keys: ["pl", "match_state"]
            players: ["pl", "opp"]
            compute_diff: true

          # Head-to-head
          - name: "h2h"
            keys: ["pl", "opp"]
            h2h: true
            output_suffix: "_diff"

    Фичи (для spans=[10, 20]):
        - pl_global_ewm_10, pl_global_ewm_20
        - opp_global_ewm_10, opp_global_ewm_20
        - all_global_ewm_10_diff, all_global_ewm_20_diff
        - pl_match_state_ewm_10, pl_match_state_ewm_20
        - ...
        - h2h_ewm_10_diff, h2h_ewm_20_diff
    """

    def validate_config(self) -> None:
        """Валидация конфигурации."""
        super().validate_config()

        required = ["metric", "spans", "contexts"]
        missing = [field for field in required if field not in self.config]
        if missing:
            raise ValueError(f"{self.name}: отсутствуют обязательные поля: {missing}")

        spans = self.config["spans"]
        if not isinstance(spans, list) or len(spans) == 0:
            raise ValueError(f"{self.name}: 'spans' должен быть непустым списком")

        contexts = self.config["contexts"]
        if not isinstance(contexts, list) or len(contexts) == 0:
            raise ValueError(f"{self.name}: 'contexts' должен быть непустым списком")

    def generate(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Генерация EWM фичей.

        Args:
            df: Long format датафрейм с колонками:
                - metric (например, diff_ps = pl_points - opp_points)
                - pl, opp (имена игроков)
                - контекстные колонки (match_state, tour_num, weekday, etc.)

        Returns:
            Датафрейм с добавленными EWM фичами

        Raises:
            ValueError: Если отсутствуют обязательные колонки
        """
        long = df.copy()

        # Параметры из конфига
        metric_col = self.config["metric"]
        spans = self.config["spans"]
        shift = self.config.get("shift", 1)
        min_periods = self.config.get("min_periods", 3)
        adjust = self.config.get("adjust", False)
        contexts = self.config["contexts"]

        # Валидация наличия метрики
        if metric_col not in long.columns:
            raise ValueError(f"{self.name}: отсутствует колонка с метрикой: '{metric_col}'")

        logger.debug(
            f"{self.name}: metric={metric_col}, spans={spans}, "
            f"shift={shift}, min_periods={min_periods}, adjust={adjust}"
        )
        logger.debug(f"{self.name}: contexts={len(contexts)}")

        # Генерация фичей для каждого span и контекста
        total_features = 0
        for span in spans:
            for ctx in contexts:
                count = self._generate_context_features(
                    long, ctx, metric_col, span, shift, min_periods, adjust
                )
                total_features += count

        logger.info(
            f"{self.name}: сгенерировано {total_features} фичей "
            f"({len(spans)} spans × {len(contexts)} contexts)"
        )

        return long

    def _generate_context_features(
        self,
        df: pd.DataFrame,
        ctx: dict[str, Any],
        metric: str,
        span: int,
        shift: int,
        min_periods: int,
        adjust: bool,
    ) -> int:
        """
        Генерация EWM фичей для одного контекста и одного span (in-place).

        Args:
            df: Датафрейм (изменяется in-place)
            ctx: Конфигурация контекста
            metric: Имя колонки с метрикой
            span: Размер окна EWM
            shift: Сдвиг
            min_periods: Минимальное количество наблюдений
            adjust: Параметр adjust для EWM

        Returns:
            Количество созданных фичей
        """
        name = ctx["name"]
        keys = ctx["keys"]
        is_h2h = ctx.get("h2h", False)
        features_created = 0

        # Валидация наличия колонок
        missing = [col for col in keys if col not in df.columns]
        if missing:
            logger.warning(
                f"{self.name}: контекст '{name}' (span={span}) пропущен, "
                f"отсутствуют колонки: {missing}"
            )
            return 0

        if is_h2h:
            # H2H фичи (один признак на пару игроков)
            output_suffix = ctx.get("output_suffix", "_diff")
            feature_name = f"{name}_ewm_{span}{output_suffix}"

            df[feature_name] = self._calculate_ewm(
                df, keys, metric, span, shift, min_periods, adjust
            )
            features_created = 1
            logger.debug(f"{self.name}: {feature_name} создан (h2h, keys={keys})")
        else:
            # Фичи для каждого игрока
            players = ctx.get("players", ["pl", "opp"])

            for player in players:
                # Заменяем "pl" в keys на текущего игрока
                player_keys = [player if k == "pl" else k for k in keys]

                # Проверка наличия колонок для этого игрока
                missing_player = [k for k in player_keys if k not in df.columns]
                if missing_player:
                    logger.warning(
                        f"{self.name}: {player}_{name}_ewm_{span} пропущен, "
                        f"отсутствуют колонки: {missing_player}"
                    )
                    continue

                feature_name = f"{player}_{name}_ewm_{span}"
                df[feature_name] = self._calculate_ewm(
                    df, player_keys, metric, span, shift, min_periods, adjust
                )
                features_created += 1
                logger.debug(f"{self.name}: {feature_name} создан (keys={player_keys})")

            # Разница между игроками
            if ctx.get("compute_diff", False) and "pl" in players and "opp" in players:
                pl_feat = f"pl_{name}_ewm_{span}"
                opp_feat = f"opp_{name}_ewm_{span}"

                if pl_feat in df.columns and opp_feat in df.columns:
                    diff_feat = f"all_{name}_ewm_{span}_diff"
                    df[diff_feat] = df[pl_feat] - df[opp_feat]
                    features_created += 1
                    logger.debug(f"{self.name}: {diff_feat} создан (diff: {pl_feat} - {opp_feat})")

        return features_created

    def _calculate_ewm(
        self,
        df: pd.DataFrame,
        group_keys: list[str],
        metric: str,
        span: int,
        shift: int,
        min_periods: int,
        adjust: bool,
    ) -> pd.Series:
        """
        Вычисление EWM для группы.

        Args:
            df: Датафрейм
            group_keys: Ключи для группировки
            metric: Колонка с метрикой
            span: Размер окна
            shift: Сдвиг
            min_periods: Минимальное количество наблюдений
            adjust: Параметр adjust для EWM

        Returns:
            Series с EWM значениями
        """
        return df.groupby(group_keys, dropna=False)[metric].transform(
            lambda x: x.shift(shift)
            .ffill()
            .fillna(0.0)
            .ewm(span=span, min_periods=min_periods, adjust=adjust, ignore_na=True)
            .mean()
        )

    def get_feature_names(self) -> list[str]:
        """
        Возвращает список имен фичей (без префикса f_).

        Returns:
            Список имен фичей
        """
        features = []
        spans = self.config.get("spans", [])
        contexts = self.config.get("contexts", [])

        for span in spans:
            for ctx in contexts:
                name = ctx["name"]
                is_h2h = ctx.get("h2h", False)

                if is_h2h:
                    output_suffix = ctx.get("output_suffix", "_diff")
                    features.append(f"{name}_ewm_{span}{output_suffix}")
                else:
                    players = ctx.get("players", ["pl", "opp"])
                    for player in players:
                        features.append(f"{player}_{name}_ewm_{span}")

                    # Diff фича
                    if ctx.get("compute_diff", False) and "pl" in players and "opp" in players:
                        features.append(f"all_{name}_ewm_{span}_diff")

        return features
