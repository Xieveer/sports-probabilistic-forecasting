"""
Генератор EWM фичей (Exponentially Weighted Moving Average).

Создает экспоненциально взвешенные скользящие средние по различным контекстам:
- Глобальная форма игрока (global)
- Форма в зависимости от состояния (match_state)
- Форма в зависимости от времени суток (tour_num)
- Head-to-head форма (h2h_global, h2h_match_state, ...)
- И т.д.

Для каждого контекста генерируются фичи для разных размеров окна (spans).

Поддержка нескольких метрик:
    Каждый экземпляр генератора работает с ОДНОЙ метрикой (diff_ps или total_ps).
    Поле ``metric_label`` определяет суффикс в именах фичей:
    - ``metric_label: "diff"``  → pl_global_diff_ewm_10
    - ``metric_label: "total"`` → pl_global_total_ewm_10

    Для получения обоих типов фичей создаётся ДВА экземпляра генератора
    (``ewm_diff`` и ``ewm_total``) через конфиг.

NaN-стратегия:
    - ``ignore_na=True`` — EWM пропускает NaN-наблюдения (upcoming-матчи,
      cold-start), carry-forward последнего значения.
    - ``min_periods`` — EWM выдаёт NaN пока не увидит достаточно реальных
      данных. Это лучше чем fillna(0) или fillna(median), т.к. CatBoost/LGBM
      обрабатывают NaN нативно.
    - Опциональная ``warmup``-фича показывает модели уровень достоверности
      EWM-оценки: ``min(n_observed / threshold, 1.0)`` ∈ [0, 1].

Именование фичей (с metric_label="diff", span=10):
    pl/opp stats:
        - pl_global_diff_ewm_10
        - opp_global_diff_ewm_10
        - all_global_diff_ewm_10  (pl - opp, только при compute_diff=true)
    h2h stats:
        - h2h_global_diff_ewm_10
    warmup:
        - pl_ewm_warmup, opp_ewm_warmup  (один раз, не зависит от метрики)
"""

from typing import Any

import pandas as pd

from sports_forecast.features.generators.base import BaseFeatureGenerator
from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)


class EWMFeatureGenerator(BaseFeatureGenerator):
    """
    Генератор экспоненциально взвешенных скользящих средних.

    Пример конфига (multi-metric):

        # --- diff_ps ---
        ewm_diff:
          type: "ewm"
          metric: "diff_ps"
          metric_label: "diff"
          spans: [5, 25, 100]
          shift: 1
          min_periods: 3
          adjust: false

          contexts:
            - name: "global"
              keys: ["pl"]
              players: ["pl", "opp"]
              compute_diff: true           # all_global_diff_ewm_5 = pl - opp

            - name: "h2h_global"
              keys: ["pl", "opp"]
              h2h: true                    # h2h_global_diff_ewm_5

          warmup:
            enabled: true
            threshold: 10
            players: ["pl", "opp"]

        # --- total_ps ---
        ewm_total:
          type: "ewm"
          metric: "total_ps"
          metric_label: "total"
          spans: [5, 25, 100]
          shift: 1
          min_periods: 3
          adjust: false

          contexts:
            - name: "global"
              keys: ["pl"]
              players: ["pl", "opp"]
              compute_diff: false          # НЕТ all_*, только pl/opp

            - name: "h2h_global"
              keys: ["pl", "opp"]
              h2h: true                    # h2h_global_total_ewm_5

    Фичи (для spans=[5]):
        ewm_diff:
            - pl_global_diff_ewm_5, opp_global_diff_ewm_5, all_global_diff_ewm_5
            - h2h_global_diff_ewm_5
            - pl_ewm_warmup, opp_ewm_warmup
        ewm_total:
            - pl_global_total_ewm_5, opp_global_total_ewm_5
            - h2h_global_total_ewm_5
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
                - metric (например, diff_ps или total_ps)
                - pl, opp (имена игроков)
                - контекстные колонки (match_state, tour_num, weekday, etc.)

        Returns:
            Датафрейм с добавленными EWM фичами

        Raises:
            ValueError: Если отсутствуют обязательные колонки
        """
        long = df.copy()
        self._last_run_skipped_contexts = 0

        # Параметры из конфига
        metric_col = self.config["metric"]
        metric_label = self.config.get("metric_label", "")
        spans = self.config["spans"]
        shift = self.config.get("shift", 1)
        min_periods = self.config.get("min_periods", 3)
        adjust = self.config.get("adjust", False)
        contexts = self.config["contexts"]

        # Валидация наличия метрики
        if metric_col not in long.columns:
            raise ValueError(f"{self.name}: отсутствует колонка с метрикой: '{metric_col}'")

        logger.debug(
            f"{self.name}: metric={metric_col}, metric_label={metric_label!r}, "
            f"spans={spans}, shift={shift}, min_periods={min_periods}, adjust={adjust}"
        )
        logger.debug("%s: contexts=%d", self.name, len(contexts))

        # Генерация фичей для каждого span и контекста
        total_features = 0
        for span in spans:
            for ctx in contexts:
                count = self._generate_context_features(
                    long, ctx, metric_col, metric_label, span, shift, min_periods, adjust
                )
                total_features += count

        # Warmup-фича (опционально)
        warmup_cfg = self.config.get("warmup", {})
        if warmup_cfg.get("enabled", False):
            warmup_count = self._generate_warmup_features(long, metric_col, shift, warmup_cfg)
            total_features += warmup_count

        logger.info(
            f"{self.name}: сгенерировано {total_features} фичей "
            f"({len(spans)} spans × {len(contexts)} contexts, metric={metric_label!r})"
        )

        return long

    def _generate_context_features(
        self,
        df: pd.DataFrame,
        ctx: dict[str, Any],
        metric: str,
        metric_label: str,
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
            metric_label: Метка метрики для именования (e.g. "diff", "total")
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
            self._last_run_skipped_contexts = getattr(self, "_last_run_skipped_contexts", 0) + 1
            return 0

        if is_h2h:
            # H2H фичи (один признак на пару игроков)
            # Naming: {context}_{metric_label}_ewm_{span}
            # Example: h2h_global_diff_ewm_5
            feature_name = self._feature_name_h2h(name, metric_label, span)

            df[feature_name] = self._calculate_ewm(
                df, keys, metric, span, shift, min_periods, adjust
            )
            features_created = 1
            logger.debug("%s: %s создан (h2h, keys=%s)", self.name, feature_name, keys)
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
                        f"{self.name}: {player}_{name} пропущен, "
                        f"отсутствуют колонки: {missing_player}"
                    )
                    continue

                # Naming: {player}_{context}_{metric_label}_ewm_{span}
                # Example: pl_global_diff_ewm_5
                feature_name = self._feature_name_player(player, name, metric_label, span)
                df[feature_name] = self._calculate_ewm(
                    df, player_keys, metric, span, shift, min_periods, adjust
                )
                features_created += 1
                logger.debug("%s: %s создан (keys=%s)", self.name, feature_name, player_keys)

            # Разница между игроками
            if ctx.get("compute_diff", False) and "pl" in players and "opp" in players:
                pl_feat = self._feature_name_player("pl", name, metric_label, span)
                opp_feat = self._feature_name_player("opp", name, metric_label, span)

                if pl_feat in df.columns and opp_feat in df.columns:
                    diff_feat = self._feature_name_diff(name, metric_label, span)
                    df[diff_feat] = df[pl_feat] - df[opp_feat]
                    features_created += 1
                    logger.debug(
                        "%s: %s создан (diff: %s - %s)",
                        self.name,
                        diff_feat,
                        pl_feat,
                        opp_feat,
                    )

        return features_created

    def _generate_warmup_features(
        self,
        df: pd.DataFrame,
        metric: str,
        shift: int,
        warmup_cfg: dict[str, Any],
    ) -> int:
        """
        Генерация warmup-фичей — коэффициентов уверенности EWM.

        Формула: ``min(n_observed / threshold, 1.0)``

        Где ``n_observed`` — кумулятивное число не-NaN наблюдений метрики
        (со сдвигом ``shift``), ``threshold`` — порог «полной уверенности».

        Значение 0 → у игрока нет истории, EWM = NaN (модель не должна
        опираться на EWM-фичи). Значение 1 → достаточно матчей, EWM надёжен.

        Warmup НЕ зависит от metric_label: diff_ps и total_ps имеют одинаковый
        паттерн NaN (оба вычисляются из pl_points/opp_points). Достаточно
        одного warmup на игрока.

        Args:
            df: Датафрейм (изменяется in-place).
            metric: Колонка с метрикой.
            shift: Сдвиг (исключаем текущий матч).
            warmup_cfg: Конфигурация warmup (threshold, players).

        Returns:
            Количество созданных фичей.
        """
        threshold = warmup_cfg.get("threshold", 10)
        players = warmup_cfg.get("players", ["pl", "opp"])
        features_created = 0

        for player in players:
            feature_name = f"{player}_ewm_warmup"

            df[feature_name] = df.groupby(player, dropna=False, observed=False)[metric].transform(
                lambda x: x.shift(shift).expanding().count().div(threshold).clip(upper=1.0)
            )
            features_created += 1
            logger.debug(
                "%s: %s создан (threshold=%d)",
                self.name,
                feature_name,
                threshold,
            )

        logger.info(
            "%s: warmup фичей: %d (threshold=%d)",
            self.name,
            features_created,
            threshold,
        )
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

        NaN-стратегия (без ffill / fillna):
            - ``shift(shift)`` сдвигает метрику → первые строки каждой группы
              становятся NaN (cold-start).
            - ``ignore_na=True`` пропускает NaN-наблюдения: upcoming-матчи
              (метрика = NaN из-за отсутствия счёта) не обновляют EWM-весá,
              а последнее значение carry-forward.
            - ``min_periods`` гарантирует NaN на выходе пока реальных
              наблюдений меньше порога → модель видит «нет данных».

        Args:
            df: Датафрейм.
            group_keys: Ключи для группировки.
            metric: Колонка с метрикой.
            span: Размер окна EWM.
            shift: Сдвиг (исключаем текущий матч).
            min_periods: Минимальное количество не-NaN наблюдений.
            adjust: Параметр adjust для EWM.

        Returns:
            Series с EWM значениями.
        """
        return df.groupby(group_keys, dropna=False, observed=False)[metric].transform(
            lambda x: x.shift(shift)
            .ewm(span=span, min_periods=min_periods, adjust=adjust, ignore_na=True)
            .mean()
        )

    # ------------------------------------------------------------------
    # Naming helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _feature_name_player(player: str, context: str, metric_label: str, span: int) -> str:
        """Имя фичи для отдельного игрока.

        Pattern: ``{player}_{context}_{metric_label}_ewm_{span}``
        Example: ``pl_global_diff_ewm_5``

        Если metric_label пустой (backward compat):
            ``{player}_{context}_ewm_{span}``
        """
        if metric_label:
            return f"{player}_{context}_{metric_label}_ewm_{span}"
        return f"{player}_{context}_ewm_{span}"

    @staticmethod
    def _feature_name_diff(context: str, metric_label: str, span: int) -> str:
        """Имя diff-фичи (pl - opp).

        Pattern: ``all_{context}_{metric_label}_ewm_{span}``
        Example: ``all_global_diff_ewm_5``

        Если metric_label пустой:
            ``all_{context}_ewm_{span}_diff``  (legacy)
        """
        if metric_label:
            return f"all_{context}_{metric_label}_ewm_{span}"
        return f"all_{context}_ewm_{span}_diff"

    @staticmethod
    def _feature_name_h2h(context: str, metric_label: str, span: int) -> str:
        """Имя H2H фичи.

        Pattern: ``{context}_{metric_label}_ewm_{span}``
        Example: ``h2h_global_diff_ewm_5``

        Если metric_label пустой:
            ``{context}_ewm_{span}``
        """
        if metric_label:
            return f"{context}_{metric_label}_ewm_{span}"
        return f"{context}_ewm_{span}"

    # ------------------------------------------------------------------
    # Feature names
    # ------------------------------------------------------------------

    def get_feature_names(self) -> list[str]:
        """
        Возвращает список имен фичей (без префикса f_), которые генератор
        может создать по конфигу (ожидаемый список, без учёта наличия колонок).

        Returns:
            Список имен фичей
        """
        return self.get_expected_feature_names()

    def get_expected_feature_names(self) -> list[str]:
        """
        Возвращает полный список имён фичей по конфигу (все контексты и spans).

        Returns:
            Список имен фичей без префикса f_
        """
        features = []
        spans = self.config.get("spans", [])
        contexts = self.config.get("contexts", [])
        metric_label = self.config.get("metric_label", "")

        for span in spans:
            for ctx in contexts:
                name = ctx["name"]
                is_h2h = ctx.get("h2h", False)

                if is_h2h:
                    features.append(self._feature_name_h2h(name, metric_label, span))
                else:
                    players = ctx.get("players", ["pl", "opp"])
                    for player in players:
                        features.append(self._feature_name_player(player, name, metric_label, span))

                    # Diff фича
                    if ctx.get("compute_diff", False) and "pl" in players and "opp" in players:
                        features.append(self._feature_name_diff(name, metric_label, span))

        # Warmup-фичи
        warmup_cfg = self.config.get("warmup", {})
        if warmup_cfg.get("enabled", False):
            warmup_players = warmup_cfg.get("players", ["pl", "opp"])
            for player in warmup_players:
                features.append(f"{player}_ewm_warmup")

        return features

    def get_actual_feature_names(self, df: pd.DataFrame) -> list[str]:
        """
        Возвращает список имён фичей, которые будут реально сгенерированы для df.

        Пропущенные контексты (из-за отсутствующих колонок) не включаются.

        Args:
            df: Датафрейм с колонками метрик и контекстов (до или после generate).

        Returns:
            Список имён фичей без префикса f_
        """
        features: list[str] = []
        spans = self.config.get("spans", [])
        contexts = self.config.get("contexts", [])
        metric_label = self.config.get("metric_label", "")

        for span in spans:
            for ctx in contexts:
                name = ctx["name"]
                keys = ctx["keys"]
                is_h2h = ctx.get("h2h", False)

                missing = [col for col in keys if col not in df.columns]
                if missing:
                    continue

                if is_h2h:
                    features.append(self._feature_name_h2h(name, metric_label, span))
                else:
                    players = ctx.get("players", ["pl", "opp"])
                    added_players: list[str] = []
                    for player in players:
                        player_keys = [player if k == "pl" else k for k in keys]
                        missing_player = [k for k in player_keys if k not in df.columns]
                        if missing_player:
                            continue
                        features.append(self._feature_name_player(player, name, metric_label, span))
                        added_players.append(player)

                    if (
                        ctx.get("compute_diff", False)
                        and "pl" in added_players
                        and "opp" in added_players
                    ):
                        features.append(self._feature_name_diff(name, metric_label, span))

        # Warmup не зависит от контекстных колонок, создаётся всегда если включён
        warmup_cfg = self.config.get("warmup", {})
        if warmup_cfg.get("enabled", False):
            warmup_players = warmup_cfg.get("players", ["pl", "opp"])
            for player in warmup_players:
                features.append(f"{player}_ewm_warmup")

        return features
