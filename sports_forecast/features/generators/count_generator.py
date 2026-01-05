"""
Генератор count фичей (количество встреч в контексте).

Подсчитывает сколько раз игрок встречался в определенном контексте:
- Глобально (все матчи игрока)
- В определенном состоянии формы (match_state)
- В определенном номере матча (tour_match_num)
- Head-to-head (против конкретного оппонента)
- И т.д.

Генерирует:
- pl_global_count: Общее количество матчей игрока
- pl_match_state_count: Количество матчей в текущем match_state
- h2h_count: Количество встреч pl vs opp
"""

from typing import Any, Dict, List

import pandas as pd

from sports_forecast.features.generators.base import BaseFeatureGenerator
from sports_forecast.utils.log_config import get_logger

logger = get_logger(__name__)


class CountFeatureGenerator(BaseFeatureGenerator):
    """
    Генератор count фичей.

    Пример конфига:
        type: "count"
        enabled: true
        shift: 1
        contexts:
          - name: "global"
            keys: ["pl"]
            players: ["pl", "opp"]

          - name: "match_state"
            keys: ["pl", "match_state"]
            players: ["pl", "opp"]

          - name: "h2h"
            keys: ["pl", "opp"]
            h2h: true

    Фичи:
        - pl_global_count: int (количество матчей игрока до текущего)
        - opp_global_count: int
        - pl_match_state_count: int
        - opp_match_state_count: int
        - h2h_count: int (количество встреч pl vs opp)
    """

    def validate_config(self) -> None:
        """Валидация конфигурации."""
        super().validate_config()

        if "contexts" not in self.config:
            raise ValueError(f"{self.name}: отсутствует обязательное поле 'contexts'")

        contexts = self.config["contexts"]
        if not isinstance(contexts, list) or len(contexts) == 0:
            raise ValueError(
                f"{self.name}: 'contexts' должен быть непустым списком"
            )

        # Проверка каждого контекста
        for i, ctx in enumerate(contexts):
            if "name" not in ctx:
                raise ValueError(
                    f"{self.name}: context[{i}] не содержит обязательное поле 'name'"
                )
            if "keys" not in ctx:
                raise ValueError(
                    f"{self.name}: context[{i}] не содержит обязательное поле 'keys'"
                )

    def generate(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Генерация count фичей.

        Args:
            df: Long format датафрейм

        Returns:
            Датафрейм с добавленными count фичами

        Raises:
            ValueError: Если отсутствуют обязательные колонки
        """
        long = df.copy()

        shift = self.config.get("shift", 1)
        contexts = self.config["contexts"]

        logger.debug(f"{self.name}: shift={shift}, contexts={len(contexts)}")

        # Генерация фичей для каждого контекста
        for ctx in contexts:
            self._generate_context_count(long, ctx, shift)

        return long

    def _generate_context_count(
        self, df: pd.DataFrame, ctx: Dict[str, Any], shift: int
    ) -> None:
        """
        Генерация count фичей для одного контекста (in-place).

        Args:
            df: Датафрейм (изменяется in-place)
            ctx: Конфигурация контекста
            shift: Сдвиг для исключения текущего матча
        """
        name = ctx["name"]
        keys = ctx["keys"]
        is_h2h = ctx.get("h2h", False)

        # Валидация наличия колонок
        missing = [col for col in keys if col not in df.columns]
        if missing:
            logger.warning(
                f"{self.name}: контекст '{name}' пропущен, "
                f"отсутствуют колонки: {missing}"
            )
            return

        if is_h2h:
            # H2H count (один признак на пару игроков)
            df[f"{name}_count"] = self._calculate_count(df, keys, shift)
            logger.debug(
                f"{self.name}: {name}_count создан (h2h, keys={keys})"
            )
        else:
            # Count для каждого игрока
            players = ctx.get("players", ["pl", "opp"])

            for player in players:
                # Заменяем "pl" в keys на текущего игрока
                player_keys = [player if k == "pl" else k for k in keys]

                # Проверка наличия колонок для этого игрока
                missing_player = [k for k in player_keys if k not in df.columns]
                if missing_player:
                    logger.warning(
                        f"{self.name}: {player}_{name}_count пропущен, "
                        f"отсутствуют колонки: {missing_player}"
                    )
                    continue

                df[f"{player}_{name}_count"] = self._calculate_count(
                    df, player_keys, shift
                )
                logger.debug(
                    f"{self.name}: {player}_{name}_count создан (keys={player_keys})"
                )

    def _calculate_count(
        self, df: pd.DataFrame, group_keys: List[str], shift: int
    ) -> pd.Series:
        """
        Вычисление count для группы.

        Args:
            df: Датафрейм
            group_keys: Ключи для группировки
            shift: Сдвиг (исключаем текущий матч из подсчета)

        Returns:
            Series с количеством встреч
        """
        return df.groupby(group_keys, dropna=False).cumcount() + 1 - shift

    def get_feature_names(self) -> List[str]:
        """
        Возвращает список имен фичей (без префикса f_).

        Returns:
            Список имен фичей
        """
        features = []
        contexts = self.config.get("contexts", [])

        for ctx in contexts:
            name = ctx["name"]
            is_h2h = ctx.get("h2h", False)

            if is_h2h:
                features.append(f"{name}_count")
            else:
                players = ctx.get("players", ["pl", "opp"])
                for player in players:
                    features.append(f"{player}_{name}_count")

        return features

