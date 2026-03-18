"""
Генератор фичей формы игрока (Player Form Features).

Создает фичи на основе времени между матчами игрока:
- First Game (FG): игрок давно не играл (>= fg_trigger)
- Double Play (DP): игрок играет второй матч подряд (<= dp_trigger)
- In Form: игрок в нормальной форме (между FG и DP)

Генерирует:
- pl_mins_prev_match, opp_mins_prev_match: время с предыдущего матча (минуты)
- pl_is_dp, pl_is_fg, pl_is_form: бинарные индикаторы состояния
- opp_is_dp, opp_is_fg, opp_is_form: аналогично для оппонента
- match_state: комбинированное состояние матча (pl_state|opp_state)
- diff_mins_prev_match: разница во времени между игроками
"""

import numpy as np
import pandas as pd

from sports_forecast.features.generators.base import BaseFeatureGenerator
from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)


class FormFeatureGenerator(BaseFeatureGenerator):
    """
    Генератор фичей формы игрока.

    Пример конфига:
        type: "form"
        enabled: true
        fg_trigger_minutes: 480   # 8 часов
        dp_trigger_minutes: 30
        players: ["pl", "opp"]

    Фичи:
        - pl_mins_prev_match: Минуты с предыдущего матча (float)
        - pl_is_dp: First Game индикатор (int8: 0 или 1)
        - pl_is_fg: Double Play индикатор (int8: 0 или 1)
        - pl_is_form: In Form индикатор (int8: 0 или 1)
        - opp_mins_prev_match: аналогично для оппонента
        - opp_is_dp, opp_is_fg, opp_is_form: аналогично
        - match_state: Комбинированное состояние (str: "fg|dp", "form|form", etc.)
        - diff_mins_prev_match: Разница времени (float: pl_mins - opp_mins)
    """

    def validate_config(self) -> None:
        """Валидация конфигурации."""
        super().validate_config()

        # Проверка обязательных параметров
        if "fg_trigger_minutes" not in self.config:
            logger.warning(
                "%s: fg_trigger_minutes не указан, используется 480 (8 часов)", self.name
            )

        if "dp_trigger_minutes" not in self.config:
            logger.warning("%s: dp_trigger_minutes не указан, используется 30 минут", self.name)

    def generate(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Генерация фичей формы игрока.

        Args:
            df: Long format датафрейм с колонками:
                - datetime: datetime64
                - pl: str (имя игрока)
                - opp: str (имя оппонента)

        Returns:
            Датафрейм с добавленными фичами формы

        Raises:
            ValueError: Если отсутствуют обязательные колонки
        """
        # Валидация входных данных
        required_cols = ["datetime", "pl", "opp"]
        missing = [col for col in required_cols if col not in df.columns]
        if missing:
            raise ValueError(f"{self.name}: отсутствуют обязательные колонки: {missing}")

        long = df.copy()

        # Параметры из конфига
        fg_trigger = self.config.get("fg_trigger_minutes", 480)  # 8 часов по умолчанию
        dp_trigger = self.config.get("dp_trigger_minutes", 30)  # 30 минут
        players = self.config.get("players", ["pl", "opp"])

        logger.debug(
            f"{self.name}: fg_trigger={fg_trigger}м, dp_trigger={dp_trigger}м, players={players}"
        )

        # Генерация фичей для каждого игрока
        for player in players:
            self._generate_player_form(long, player, fg_trigger, dp_trigger)

        # Комбинированное состояние матча
        if "pl" in players and "opp" in players:
            pl_state_str = long["pl_state"].astype(str)
            opp_state_str = long["opp_state"].astype(str)
            long["match_state"] = pl_state_str.str.cat(opp_state_str, sep="|")

            # Разница во времени между игроками
            long["diff_mins_prev_match"] = long["pl_mins_prev_match"] - long["opp_mins_prev_match"]

            logger.debug("%s: создано match_state и diff_mins_prev_match", self.name)

        return long

    def _generate_player_form(
        self,
        df: pd.DataFrame,
        player: str,
        fg_trigger: float,
        dp_trigger: float,
    ) -> None:
        """
        Генерация фичей формы для одного игрока (in-place).

        Args:
            df: Датафрейм (изменяется in-place)
            player: Имя колонки игрока ('pl' или 'opp')
            fg_trigger: Порог First Game (минуты)
            dp_trigger: Порог Double Play (минуты)
        """
        # Время с предыдущего матча (в минутах)
        df[f"{player}_mins_prev_match"] = (
            df.groupby(player)["datetime"].diff().dt.total_seconds().div(60.0)
        )

        # Определение состояния
        m = df[f"{player}_mins_prev_match"].clip(lower=0)
        is_dp = m.notna() & (m <= dp_trigger)
        is_fg = m.isna() | (m >= fg_trigger)

        # Категориальное состояние (для внутреннего использования)
        state_values = np.select([is_dp, is_fg], ["dp", "fg"], default="form")
        df[f"{player}_state"] = pd.Series(state_values, index=df.index, dtype=str).astype(
            "category"
        )

        # Бинарные индикаторы (для обучения)
        df[f"{player}_is_dp"] = is_dp.astype("int8")
        df[f"{player}_is_fg"] = is_fg.astype("int8")
        df[f"{player}_is_form"] = (~(is_dp | is_fg)).astype("int8")

        logger.debug(
            f"{self.name}: {player} форма: "
            f"DP={is_dp.sum()}, FG={is_fg.sum()}, Form={(~(is_dp | is_fg)).sum()}"
        )

    def get_feature_names(self) -> list[str]:
        """
        Возвращает список имен фичей (без префикса f_).

        Note:
            ``match_state``, ``pl_state``, ``opp_state`` — это КОНТЕКСТНЫЕ
            колонки для группировки в EWM/Count. Они НЕ включаются в feature
            names, чтобы не получить ``f_`` префикс и остаться доступными
            для downstream генераторов как ключи группировки.

        Returns:
            Список имен фичей
        """
        players = self.config.get("players", ["pl", "opp"])
        features = []

        for player in players:
            features.extend(
                [
                    f"{player}_mins_prev_match",
                    f"{player}_is_dp",
                    f"{player}_is_fg",
                    f"{player}_is_form",
                ]
            )

        # diff_mins_prev_match — это реальная фича
        # match_state — это контекстная колонка для группировки (НЕ фича)
        if "pl" in players and "opp" in players:
            features.append("diff_mins_prev_match")

        return features
