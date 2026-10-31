"""
Optuna оптимизатор для подбора гиперпараметров моделей.

Поддерживает:
- Построение пространства параметров из ``algorithm.optuna_space`` конфигов
- Оптимизацию на TSCV (усреднённый log loss по фолдам)
- Создание новых моделей через ``ModelFactory`` на каждый trial
- Логирование в MLflow (артефакт ``optuna_trials.json``: ``params``, ``value``, ``user_attrs`` с ``mean_*``/``std_*`` из TSCV)
- SQLite storage для персистентности

Примеры::

    optimizer = OptunaHyperOptimizer(cfg.algorithm, cfg.hyper, cfg.split)
    best_params = optimizer.optimize(train_features, train_target)
"""

from __future__ import annotations

import json
import time
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

import mlflow
from omegaconf import DictConfig, OmegaConf
from optuna.logging import INFO, WARNING, set_verbosity
from optuna.pruners import MedianPruner
from optuna.samplers import RandomSampler, TPESampler
from optuna.study import Study, StudyDirection, create_study, get_all_study_summaries, load_study
from optuna.trial import FrozenTrial, Trial, TrialState

from sports_forecast.training.optimization.tscv import TimeSeriesCrossValidator
from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)


def build_param_space_from_config(
    optuna_space: DictConfig,
    trial: Trial,
) -> dict[str, Any]:
    """Построить пространство параметров из конфига ``algorithm.optuna_space``.

    Поддерживаемые типы:
        - ``float``: ``trial.suggest_float(name, low, high, log=False)``
        - ``int``: ``trial.suggest_int(name, low, high, step=1)``
        - ``categorical``: ``trial.suggest_categorical(name, choices)``

    Args:
        optuna_space: Секция ``optuna_space`` из конфига алгоритма.
        trial: Optuna Trial.

    Returns:
        Словарь параметров для модели.

    Raises:
        ValueError: Если тип параметра не поддерживается.

    Examples:
        Конфиг::

            optuna_space:
              learning_rate:
                type: float
                low: 0.01
                high: 0.3
                log: true
              depth:
                type: int
                low: 4
                high: 12
    """
    params: dict[str, Any] = {}

    for param_name, param_cfg in optuna_space.items():
        param_type = param_cfg.get("type", "float")

        if param_type == "float":
            params[param_name] = trial.suggest_float(
                param_name,
                float(param_cfg.low),
                float(param_cfg.high),
                log=param_cfg.get("log", False),
            )
        elif param_type == "int":
            step = int(param_cfg.get("step", 1))
            params[param_name] = trial.suggest_int(
                param_name,
                int(param_cfg.low),
                int(param_cfg.high),
                step=step,
            )
        elif param_type == "categorical":
            choices = list(param_cfg.choices)
            params[param_name] = trial.suggest_categorical(param_name, choices)
        else:
            raise ValueError(
                f"Неподдерживаемый тип параметра '{param_type}' "
                f"для '{param_name}'. Допустимые: float, int, categorical"
            )

    return params


class OptunaHyperOptimizer:
    """Optuna оптимизатор, управляемый конфигами.

    Строит пространство параметров из ``algorithm.optuna_space``,
    создаёт новые экземпляры моделей через ``ModelFactory`` на каждый trial,
    оценивает качество через TSCV.

    Args:
        algorithm_cfg: Конфигурация алгоритма (с ``optuna_space``).
        hyper_cfg: Конфигурация гиперпараметрической оптимизации.
        split_cfg: Конфигурация split (для TSCV n_splits).

    Attributes:
        algorithm_cfg: Конфигурация алгоритма.
        hyper_cfg: Конфигурация оптимизации.
        n_splits: Количество фолдов TSCV.
        study_name: Уникальное название Optuna study.

    Examples:
        >>> optimizer = OptunaHyperOptimizer(cfg.algorithm, cfg.hyper, cfg.split)
        >>> best_params = optimizer.optimize(train_features, train_target)
        >>> # best_params можно передать при создании модели
    """

    def __init__(
        self,
        algorithm_cfg: DictConfig,
        hyper_cfg: DictConfig,
        split_cfg: DictConfig | None = None,
        study_name: str | None = None,
    ) -> None:
        """Инициализация OptunaHyperOptimizer.

        Args:
            algorithm_cfg: Конфигурация алгоритма.
            hyper_cfg: Конфигурация гиперпараметрической оптимизации.
            split_cfg: Конфигурация split (TSCV).
            study_name: Пользовательское имя study (опционально).
        """
        self.algorithm_cfg = algorithm_cfg
        self.hyper_cfg = hyper_cfg

        # TSCV настройки
        self.n_splits = split_cfg.get("tscv_n_splits", 4) if split_cfg else 4

        # Optuna study settings
        self.n_trials = hyper_cfg.get("n_trials", 50)
        self.timeout = hyper_cfg.get("timeout", None)
        self.direction = hyper_cfg.get("direction", "minimize")
        self.metric = hyper_cfg.get("metric", "logloss")

        # Study naming
        model_name = algorithm_cfg.name
        self.study_name = study_name or f"hyper_{model_name}"
        self.active_study_name = self.study_name

        # SQLite storage
        storage_dir = Path(str(hyper_cfg.get("storage_dir", "optuna")))
        storage_dir.mkdir(parents=True, exist_ok=True)
        self.storage_url = f"sqlite:///{storage_dir}/{self.study_name}.db"

        # TSCV
        self.tscv = TimeSeriesCrossValidator(n_splits=self.n_splits)

        # Sampler configuration (``sampler=null`` → дефолтный TPE; ключ отсутствует → тот же дефолт)
        if "sampler" in hyper_cfg and hyper_cfg.get("sampler") is None:
            sampler_cfg: dict[str, Any] = {}
        else:
            sampler_raw = hyper_cfg.get("sampler", {})
            if OmegaConf.is_config(sampler_raw):
                sampler_cfg = dict(OmegaConf.to_container(sampler_raw, resolve=True))  # type: ignore[arg-type]
            elif isinstance(sampler_raw, dict):
                sampler_cfg = sampler_raw
            else:
                sampler_cfg = {}
        sampler_type = sampler_cfg.get("type", "TPESampler")
        sampler_seed = sampler_cfg.get("seed", 42)

        if sampler_type == "TPESampler":
            self.sampler = TPESampler(
                n_startup_trials=sampler_cfg.get("n_startup_trials", 10),
                multivariate=sampler_cfg.get("multivariate", True),
                seed=sampler_seed,
            )
        elif sampler_type == "RandomSampler":
            self.sampler = RandomSampler(seed=sampler_seed)
        else:
            self.sampler = TPESampler(seed=sampler_seed)

        # Pruner: ``pruner=null`` → без обрезки; ключ отсутствует → MedianPruner из optuna.yaml / дефолт
        if "pruner" in hyper_cfg and hyper_cfg.get("pruner") is None:
            self.pruner = None
        else:
            pruner_raw = hyper_cfg.get("pruner", {})
            if OmegaConf.is_config(pruner_raw):
                pruner_cfg = dict(OmegaConf.to_container(pruner_raw, resolve=True))  # type: ignore[arg-type]
            elif isinstance(pruner_raw, dict):
                pruner_cfg = pruner_raw
            else:
                pruner_cfg = {}
            pruner_type = pruner_cfg.get("type", "MedianPruner")
            if pruner_type == "MedianPruner":
                self.pruner = MedianPruner(
                    n_startup_trials=pruner_cfg.get("n_startup_trials", 5),
                    n_warmup_steps=pruner_cfg.get("n_warmup_steps", 10),
                    interval_steps=pruner_cfg.get("interval_steps", 1),
                )
            else:
                self.pruner = MedianPruner()

        logger.info(
            "OptunaHyperOptimizer: study='%s', n_trials=%d, metric=%s, tscv_splits=%d",
            self.study_name,
            self.n_trials,
            self.metric,
            self.n_splits,
        )

    def _valid_trials(self, study: Study) -> list[FrozenTrial]:
        """Исключить старый штраф, если нет подтверждения метрики."""
        return [
            trial
            for trial in study.get_trials(states=(TrialState.COMPLETE,))
            if trial.value != 1e6
            or trial.user_attrs.get(f"mean_{self.metric}") == trial.value
            or trial.user_attrs.get("objective_succeeded") is True
        ]

    def _best_trial(self, study: Study) -> FrozenTrial:
        """Выбрать лучший подтверждённый результат по направлению study."""
        trials = self._valid_trials(study)
        if not trials:
            raise RuntimeError(f"Optuna study {self.study_name}: нет валидных trials")
        return (min if study.direction == StudyDirection.MINIMIZE else max)(
            trials, key=lambda trial: cast(float, trial.value)
        )

    def _study(self, *, create: bool = False) -> Study:
        """Изолировать старые штрафы от sampler, не изменяя исходное study."""
        if create:
            source = create_study(
                study_name=self.study_name,
                storage=self.storage_url,
                load_if_exists=True,
                direction=self.direction,
                sampler=self.sampler,
                pruner=self.pruner,
            )
        else:
            source = load_study(
                study_name=self.study_name,
                storage=self.storage_url,
                sampler=self.sampler,
                pruner=self.pruner,
            )

        valid_numbers = {trial.number for trial in self._valid_trials(source)}
        if not any(
            trial.number not in valid_numbers
            for trial in source.get_trials(states=(TrialState.COMPLETE,))
        ):
            return source

        base_name = f"{self.study_name}__without_legacy_penalties__{self.metric}"
        origin_key = "_legacy_penalty_migration_source"
        number_key = "_legacy_penalty_migration_trial"
        summaries = get_all_study_summaries(storage=self.storage_url)
        candidates = {
            summary.study_name: summary
            for summary in summaries
            if summary.study_name == base_name
            or (
                summary.study_name.startswith(f"{base_name}__")
                and summary.study_name[len(base_name) + 2 :].isdigit()
            )
        }
        owned = [
            name
            for name, summary in candidates.items()
            if summary.user_attrs.get(origin_key) == self.study_name
        ]
        if len(owned) > 1:
            raise RuntimeError(
                f"Найдено несколько изолированных studies для {self.study_name}: {owned}"
            )
        if owned:
            isolated = load_study(
                study_name=owned[0],
                storage=self.storage_url,
                sampler=self.sampler,
                pruner=self.pruner,
            )
        else:
            isolated_name = base_name
            suffix = 1
            while isolated_name in candidates:
                isolated_name = f"{base_name}__{suffix}"
                suffix += 1
            isolated = create_study(
                study_name=isolated_name,
                storage=self.storage_url,
                direction=source.direction.name.lower(),
                sampler=self.sampler,
                pruner=self.pruner,
            )
            isolated.set_user_attr(origin_key, self.study_name)

        copied = {
            trial.user_attrs[number_key]
            for trial in isolated.trials
            if number_key in trial.user_attrs
        }
        for trial in source.trials:
            if not trial.state.is_finished() or trial.number in copied:
                continue
            if trial.state == TrialState.COMPLETE and trial.number not in valid_numbers:
                continue
            migrated = deepcopy(trial)
            migrated.user_attrs[number_key] = trial.number
            isolated.add_trial(migrated)
        return isolated

    def optimize(
        self,
        train_features: Any,
        train_target: Any,
        groups: Any = None,
    ) -> dict[str, Any]:
        """Оптимизировать гиперпараметры модели.

        Для каждого trial:
            1. Строит параметры из ``algorithm.optuna_space``
            2. Создаёт модель через ``ModelFactory`` с этими параметрами
            3. Оценивает через TSCV
            4. Возвращает метрику для Optuna

        Args:
            train_features: Фичи для обучения.
            train_target: Таргет.

        Returns:
            Словарь с лучшими параметрами.

        Raises:
            ValueError: Если ``optuna_space`` не задан в конфиге алгоритма.
        """
        # Проверяем наличие optuna_space
        optuna_space = self.algorithm_cfg.get("optuna_space", None)
        if optuna_space is None or (
            isinstance(optuna_space, DictConfig) and len(optuna_space) == 0
        ):
            raise ValueError(
                f"optuna_space не задан в конфиге алгоритма "
                f"'{self.algorithm_cfg.name}'. "
                f"Оптимизация невозможна."
            )

        logger.info("=" * 60)
        logger.info("OPTUNA ОПТИМИЗАЦИЯ")
        logger.info("  Алгоритм: %s", self.algorithm_cfg.name)
        logger.info("  Trials: %d", self.n_trials)
        logger.info("  Метрика: %s", self.metric)
        logger.info("  TSCV: %d фолдов", self.n_splits)
        logger.info("  Параметры для оптимизации: %s", list(optuna_space.keys()))
        logger.info("=" * 60)

        # Базовые параметры модели (дефолтные значения)
        base_params = dict(self.algorithm_cfg.get("params", {}))

        # Lazy import to avoid circular dependency
        from sports_forecast.training.model_factory import ModelFactory

        def objective(trial: Trial) -> float:
            """Objective function для Optuna."""
            # 1. Строим param space из конфига
            trial_params = build_param_space_from_config(optuna_space, trial)

            # 2. Мержим с базовыми параметрами
            merged_params = {**base_params, **trial_params}

            # 3. Создаём модель с новыми параметрами через ModelFactory
            trial_cfg = OmegaConf.create(
                {
                    "name": self.algorithm_cfg.name,
                    "_target_": self.algorithm_cfg.get("_target_", ""),
                    "params": merged_params,
                }
            )
            model = ModelFactory.create_model(trial_cfg)

            # 4. Оценка через TSCV
            try:
                results = self.tscv.cross_validate(
                    model=model,
                    features=train_features,
                    target=train_target,
                    groups=groups,
                )
                objective_value = float(results[f"mean_{self.metric}"])
                # Сохраняем агрегаты TSCV на trial — для отчётов / MLflow / study.trials_dataframe()
                for key, raw in results.items():
                    if not (key.startswith("mean_") or key.startswith("std_")):
                        continue
                    if raw is None:
                        continue
                    try:
                        trial.set_user_attr(key, float(raw))
                    except (TypeError, ValueError):
                        trial.set_user_attr(key, raw)
                trial.set_user_attr("objective_succeeded", True)
                return objective_value

            except Exception as e:
                logger.exception("Trial %d failed: %s", trial.number, e)
                raise

        # Исходное study остаётся неизменным при изоляции старых штрафов.
        study = self._study(create=True)
        self.active_study_name = study.study_name

        # Запускаем оптимизацию
        verbose = self.hyper_cfg.get("verbose", True)
        set_verbosity(INFO if verbose else WARNING)

        completed = len(self._valid_trials(study))
        attempts = 0
        max_extra_attempts = max(5, self.n_trials // 5)
        max_attempts = max(0, self.n_trials - completed) + max_extra_attempts
        started_at = time.monotonic()
        while completed < self.n_trials:
            remaining_seconds = (
                None if self.timeout is None else self.timeout - (time.monotonic() - started_at)
            )
            if remaining_seconds is not None and remaining_seconds <= 0:
                break
            if attempts >= max_attempts:
                break
            study.optimize(
                objective,
                n_trials=1,
                timeout=remaining_seconds,
                catch=(Exception,),
                show_progress_bar=self.hyper_cfg.get("show_progress_bar", False),
            )
            attempts += 1
            completed = len(self._valid_trials(study))
        if completed < self.n_trials:
            raise RuntimeError(
                f"Optuna study {self.study_name}: завершено {completed}/{self.n_trials} "
                "валидных trials; проверьте ошибки и повторите запуск"
            )

        best_trial = self._best_trial(study)
        best_params = dict(best_trial.params)

        logger.info("=" * 60)
        logger.info("OPTUNA ЗАВЕРШЕНА")
        logger.info("  Best value (%s): %.6f", self.metric, best_trial.value)
        logger.info("  Best params: %s", best_params)
        logger.info("  Total trials: %d", len(study.trials))
        logger.info(
            "  Valid/Pruned/Failed: %d / %d / %d",
            completed,
            len([t for t in study.trials if t.state == TrialState.PRUNED]),
            len([t for t in study.trials if t.state == TrialState.FAIL]),
        )
        logger.info("=" * 60)

        # Мержим лучшие параметры с базовыми
        return {**base_params, **best_params}

    def log_to_mlflow(self, best_params: dict[str, Any]) -> None:
        """Залогировать результаты оптимизации в MLflow.

        Args:
            best_params: Лучшие параметры (полные, с базовыми).
        """
        study = self._study()

        # Параметры
        for key, value in best_params.items():
            mlflow.log_param(f"optuna_best__{key}", value)

        # Метрики оптимизации
        mlflow.log_metric("optuna_best_value", self._best_trial(study).value)
        mlflow.log_metric("optuna_n_trials", len(study.trials))
        mlflow.log_metric(
            "optuna_n_completed",
            len(self._valid_trials(study)),
        )

        # Теги
        mlflow.set_tag("hyper_strategy", "optuna")
        mlflow.set_tag("optuna_study", study.study_name)
        mlflow.set_tag("optuna_metric", self.metric)

        # Артефакт: валидные trials как JSON
        trials_data = []
        for trial in self._valid_trials(study):
            trials_data.append(
                {
                    "number": trial.number,
                    "value": trial.value,
                    "params": trial.params,
                    "user_attrs": dict(trial.user_attrs),
                }
            )

        mlflow.log_text(
            json.dumps(trials_data, indent=2, default=str),
            "optuna_trials.json",
        )

        logger.info("Optuna результаты залогированы в MLflow")

    def save_best_params(self, save_path: Path) -> None:
        """Сохранить лучшие параметры в JSON файл.

        Args:
            save_path: Путь для сохранения.
        """
        study = self._study()
        best_trial = self._best_trial(study)

        best_data = {
            "study_name": study.study_name,
            "algorithm": self.algorithm_cfg.name,
            "best_value": best_trial.value,
            "best_params": best_trial.params,
            "n_trials": len(study.trials),
            "metric": self.metric,
        }

        save_path.parent.mkdir(parents=True, exist_ok=True)
        with save_path.open("w", encoding="utf-8") as f:
            json.dump(best_data, f, indent=2, ensure_ascii=False)

        logger.info("Лучшие параметры сохранены: %s", save_path)
