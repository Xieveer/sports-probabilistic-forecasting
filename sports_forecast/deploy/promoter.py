"""
ModelPromoter — модуль для выбора лучшей модели из MLflow экспериментов.

Сценарии использования:
    1. Автоматический промоушн: после sweep (``--multirun``) выбрать
       лучший run по указанной метрике и скопировать артефакты
       в ``models/{tournament}/{spec}/best/``.
    2. Сравнение: вывести топ-N моделей по метрикам для ручного решения.
    3. Деплой-конфиг: сгенерировать ``deploy.yaml`` с выбранным run_id.

Запуск::

    uv run python -m sports_forecast.deploy.promoter \\
        --experiment "uel_kz_1__total__over_6.5" \\
        --metric test_logloss \\
        --direction minimize \\
        --top-n 5
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import mlflow
import yaml
from mlflow.entities import Run

from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)


@dataclass
class CandidateModel:
    """Кандидат на промоушн — один MLflow Run.

    Attributes:
        run_id: Уникальный ID run-а в MLflow.
        run_name: Имя run-а (алг__фичи__sXXX).
        algorithm: Название алгоритма.
        featureset: Название набора фичей.
        primary_metric: Значение основной метрики.
        metrics: Все метрики run-а.
        tags: Все теги run-а.
        artifact_uri: URI артефактов.
    """

    run_id: str
    run_name: str
    algorithm: str
    featureset: str
    primary_metric: float
    metrics: dict[str, float] = field(default_factory=dict)
    tags: dict[str, str] = field(default_factory=dict)
    artifact_uri: str = ""


class ModelPromoter:
    """Выбор лучшей модели для продакшена на основе метрик MLflow.

    ``ModelPromoter`` работает внутри одного MLflow-эксперимента
    (один tournament + market + spec) и выбирает лучший run
    по заданной метрике.

    Args:
        experiment_name: Имя MLflow эксперимента
            (e.g. ``"uel_kz_1__total__over_6.5"``).
        metric: Метрика для ранжирования (e.g. ``"test_logloss"``).
        direction: ``"minimize"`` или ``"maximize"``.
        min_bets: Минимальное количество ставок для допуска
            (``betting_num_bets``). По умолчанию 0 (без фильтра).
        required_tags: Дополнительные теги-фильтры
            (e.g. ``{"test_validated": "true"}``).

    Examples:
        >>> promoter = ModelPromoter(
        ...     experiment_name="uel_kz_1__total__over_6.5",
        ...     metric="test_logloss",
        ...     direction="minimize",
        ... )
        >>> best = promoter.get_best_candidate()
        >>> promoter.promote(best, Path("models/uel_kz_1/total_over/best"))
    """

    def __init__(
        self,
        experiment_name: str,
        metric: str = "test_logloss",
        direction: str = "minimize",
        min_bets: int = 0,
        required_tags: dict[str, str] | None = None,
    ) -> None:
        self.experiment_name = experiment_name
        self.metric = metric
        self.direction = direction
        self.min_bets = min_bets
        self.required_tags = (
            required_tags if required_tags is not None else {"test_validated": "true"}
        )

        logger.info("ModelPromoter инициализирован:")
        logger.info("  Experiment: %s", experiment_name)
        logger.info("  Metric: %s (%s)", metric, direction)
        if min_bets > 0:
            logger.info("  Min bets: %d", min_bets)

    # ─────────────────────────────────────────────────────────────────────────
    # PUBLIC API
    # ─────────────────────────────────────────────────────────────────────────

    def get_candidates(self, top_n: int = 10) -> list[CandidateModel]:
        """Получить топ-N кандидатов на промоушн.

        Args:
            top_n: Количество лучших моделей.

        Returns:
            Список ``CandidateModel``, отсортированный по метрике.

        Raises:
            ValueError: Если эксперимент не найден.
        """
        experiment = mlflow.get_experiment_by_name(self.experiment_name)
        if experiment is None:
            raise ValueError(
                f"MLflow experiment '{self.experiment_name}' не найден. Сначала запустите обучение."
            )

        runs = mlflow.search_runs(
            experiment_ids=[experiment.experiment_id],
            filter_string='attributes.status = "FINISHED"',
            output_format="list",
        )

        if not runs:
            logger.warning(
                "Нет завершённых runs в эксперименте '%s'",
                self.experiment_name,
            )
            return []

        candidates = self._filter_and_rank(runs, top_n)
        logger.info("Найдено %d кандидатов (из %d runs)", len(candidates), len(runs))
        return candidates

    def get_best_candidate(self) -> CandidateModel | None:
        """Получить лучшего кандидата.

        Returns:
            Лучший ``CandidateModel`` или None если нет подходящих.
        """
        candidates = self.get_candidates(top_n=1)
        if not candidates:
            logger.warning("Нет подходящих кандидатов для промоушна")
            return None
        return candidates[0]

    def promote(
        self,
        candidate: CandidateModel,
        target_dir: Path,
        generate_deploy_config: bool = True,
    ) -> Path:
        """Промотировать кандидата — скопировать артефакты в target_dir.

        Args:
            candidate: Выбранный кандидат.
            target_dir: Директория для деплоя.
            generate_deploy_config: Генерировать ``deploy.yaml``.

        Returns:
            Путь к директории с артефактами.
        """
        logger.info("=" * 60)
        logger.info("ПРОМОУШН МОДЕЛИ")
        logger.info("  Run ID: %s", candidate.run_id)
        logger.info("  Run Name: %s", candidate.run_name)
        logger.info("  %s: %.6f", self.metric, candidate.primary_metric)
        logger.info("  Target: %s", target_dir)
        logger.info("=" * 60)

        target_dir.mkdir(parents=True, exist_ok=True)

        # Копируем артефакты из MLflow
        self._copy_artifacts(candidate, target_dir)

        # Генерируем deploy.yaml
        if generate_deploy_config:
            deploy_config_path = self._generate_deploy_config(candidate, target_dir)
            logger.info("Deploy config: %s", deploy_config_path)

        logger.info("Промоушн завершён: %s", target_dir)
        return target_dir

    def compare(self, top_n: int = 5) -> str:
        """Сформировать сравнительную таблицу кандидатов.

        Args:
            top_n: Количество лучших кандидатов.

        Returns:
            Форматированная строка-таблица.
        """
        candidates = self.get_candidates(top_n=top_n)
        if not candidates:
            return "Нет подходящих кандидатов."

        # Заголовки
        header = (
            f"{'#':<3} {'Run Name':<25} {'Algorithm':<12} "
            f"{'Features':<12} {self.metric:<15} "
            f"{'AUC':<10} {'Brier':<10} {'ECE':<10}"
        )
        sep = "─" * len(header)

        lines = [sep, header, sep]

        for i, c in enumerate(candidates, 1):
            auc = c.metrics.get("test_auc", 0)
            brier = c.metrics.get("test_brier", 0)
            ece = c.metrics.get("test_ece", 0)

            line = (
                f"{i:<3} {c.run_name:<25} {c.algorithm:<12} "
                f"{c.featureset:<12} {c.primary_metric:<15.6f} "
                f"{auc:<10.4f} {brier:<10.4f} {ece:<10.4f}"
            )
            lines.append(line)

        lines.append(sep)

        # Бизнес-метрики (если есть)
        has_business = any(c.metrics.get("betting_roi") is not None for c in candidates)
        if has_business:
            lines.append("")
            biz_header = (
                f"{'#':<3} {'ROI%':<10} {'Profit':<12} {'Bets':<8} {'Sharpe':<10} {'MaxDD':<10}"
            )
            lines.extend([biz_header, "─" * len(biz_header)])

            for i, c in enumerate(candidates, 1):
                roi = c.metrics.get("betting_roi", 0)
                profit = c.metrics.get("betting_profit", 0)
                bets = int(c.metrics.get("betting_num_bets", 0))
                sharpe = c.metrics.get("betting_sharpe", 0)
                max_dd = c.metrics.get("betting_max_drawdown", 0)

                biz_line = (
                    f"{i:<3} {roi:<10.2f} {profit:<12.2f} {bets:<8} {sharpe:<10.4f} {max_dd:<10.4f}"
                )
                lines.append(biz_line)

            lines.append("─" * len(biz_header))

        return "\n".join(lines)

    # ─────────────────────────────────────────────────────────────────────────
    # PRIVATE METHODS
    # ─────────────────────────────────────────────────────────────────────────

    def _filter_and_rank(self, runs: list[Run], top_n: int) -> list[CandidateModel]:
        """Фильтровать и ранжировать runs.

        Args:
            runs: Список MLflow Run.
            top_n: Количество лучших.

        Returns:
            Отсортированный список ``CandidateModel``.
        """
        candidates: list[CandidateModel] = []

        for run in runs:
            # Проверяем required_tags
            tags = run.data.tags
            if not self._check_tags(tags):
                continue

            # Проверяем наличие метрики
            metrics = run.data.metrics
            if self.metric not in metrics:
                continue

            primary_value = metrics[self.metric]

            # Фильтр по min_bets
            if self.min_bets > 0:
                num_bets = metrics.get("betting_num_bets", 0)
                if num_bets < self.min_bets:
                    continue

            candidate = CandidateModel(
                run_id=run.info.run_id,
                run_name=tags.get("mlflow.runName", run.info.run_id[:8]),
                algorithm=tags.get("algorithm", "unknown"),
                featureset=tags.get("featureset", "unknown"),
                primary_metric=primary_value,
                metrics=dict(metrics),
                tags=dict(tags),
                artifact_uri=run.info.artifact_uri,
            )
            candidates.append(candidate)

        # Сортировка
        reverse = self.direction == "maximize"
        candidates.sort(key=lambda c: c.primary_metric, reverse=reverse)

        return candidates[:top_n]

    def _check_tags(self, tags: dict[str, str]) -> bool:
        """Проверить что run удовлетворяет required_tags.

        Args:
            tags: Теги run-а.

        Returns:
            True если все required_tags совпадают.
        """
        return all(tags.get(key) == value for key, value in self.required_tags.items())

    def _copy_artifacts(self, candidate: CandidateModel, target_dir: Path) -> None:
        """Скопировать артефакты модели из MLflow.

        Args:
            candidate: Выбранный кандидат.
            target_dir: Директория назначения.
        """
        try:
            artifact_dir = mlflow.artifacts.download_artifacts(
                run_id=candidate.run_id,
            )
            artifact_path = Path(artifact_dir)

            if artifact_path.is_dir():
                for item in artifact_path.iterdir():
                    dest = target_dir / item.name
                    if item.is_file():
                        shutil.copy2(item, dest)
                        logger.debug("Скопирован артефакт: %s", item.name)
                    elif item.is_dir():
                        if dest.exists():
                            shutil.rmtree(dest)
                        shutil.copytree(item, dest)
                        logger.debug("Скопирована директория: %s", item.name)

            logger.info("Артефакты скопированы из run '%s'", candidate.run_id)

        except Exception:
            logger.exception(
                "Ошибка при копировании артефактов из run '%s'",
                candidate.run_id,
            )

    def _generate_deploy_config(self, candidate: CandidateModel, target_dir: Path) -> Path:
        """Сгенерировать deploy.yaml с информацией о модели.

        Args:
            candidate: Выбранный кандидат.
            target_dir: Директория для сохранения.

        Returns:
            Путь к deploy.yaml.
        """
        deploy_config: dict[str, Any] = {
            "model": {
                "run_id": candidate.run_id,
                "run_name": candidate.run_name,
                "algorithm": candidate.algorithm,
                "featureset": candidate.featureset,
                "experiment": self.experiment_name,
            },
            "selection": {
                "metric": self.metric,
                "direction": self.direction,
                "value": float(candidate.primary_metric),
                "min_bets": self.min_bets,
            },
            "metrics": {
                "test_logloss": candidate.metrics.get("test_logloss"),
                "test_auc": candidate.metrics.get("test_auc"),
                "test_brier": candidate.metrics.get("test_brier"),
                "test_ece": candidate.metrics.get("test_ece"),
                "test_accuracy": candidate.metrics.get("test_accuracy"),
            },
            "business": {
                "betting_roi": candidate.metrics.get("betting_roi"),
                "betting_profit": candidate.metrics.get("betting_profit"),
                "betting_num_bets": (
                    int(candidate.metrics["betting_num_bets"])
                    if "betting_num_bets" in candidate.metrics
                    else None
                ),
                "betting_sharpe": candidate.metrics.get("betting_sharpe"),
            },
            "stability": {
                "level": candidate.tags.get("stability_level"),
                "prod_confidence": candidate.tags.get("prod_confidence"),
            },
        }

        deploy_path = target_dir / "deploy.yaml"
        with deploy_path.open("w") as f:
            yaml.dump(deploy_config, f, default_flow_style=False, allow_unicode=True)

        return deploy_path
