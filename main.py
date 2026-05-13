"""
Sports Probabilistic Forecasting — Unified CLI Entry Point.

Этот модуль предоставляет единую точку входа для всех операций проекта.
Каждая операция имеет свой подкомандный модуль, который вызывается через CLI.

Usage::

    # Обучение модели
    python main.py train tournament=uel_kz_1 market=total ...

    # Инференс
    python main.py predict tournament=uel_kz_1 ...

    # Выбор лучшей модели
    python main.py promote compare -e uel_kz_1__total__over_6.5
    python main.py promote deploy --run-id <mlflow_run_id> -t models/nhl/winner_withOT/best

    # Справка
    python main.py --help
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import cast


PROJECT_ROOT = Path(__file__).resolve().parent


def _run_module(module: str, extra_args: list[str]) -> int:
    """Запустить Python-модуль с аргументами.

    Args:
        module: Имя модуля (e.g. ``sports_forecast.train``).
        extra_args: Дополнительные аргументы CLI.

    Returns:
        Exit code.
    """
    cmd = [sys.executable, "-m", module, *extra_args]
    result = subprocess.run(cmd, cwd=str(PROJECT_ROOT), check=False)
    return result.returncode


def cmd_train(args: argparse.Namespace) -> int:
    """Запустить обучение модели.

    Args:
        args: Аргументы CLI.

    Returns:
        Exit code.
    """
    return _run_module("sports_forecast.train", args.hydra_args)


def cmd_predict(args: argparse.Namespace) -> int:
    """Запустить инференс модели.

    Args:
        args: Аргументы CLI.

    Returns:
        Exit code.
    """
    return _run_module("sports_forecast.predict", args.hydra_args)


def cmd_promote(args: argparse.Namespace) -> int:
    """Запустить выбор лучшей модели.

    Args:
        args: Аргументы CLI.

    Returns:
        Exit code.
    """
    from mlflow.exceptions import MlflowException

    from sports_forecast.deploy.promoter import ModelPromoter, promoter_and_candidate_from_run_id

    run_id = getattr(args, "run_id", None)
    if run_id and args.experiment:
        print(
            "Укажите либо --run-id, либо --experiment, но не оба одновременно.",
            file=sys.stderr,
        )
        return 1

    if run_id:
        try:
            promoter, fixed_candidate = promoter_and_candidate_from_run_id(
                run_id,
                metric=args.metric,
                direction=args.direction,
            )
        except (ValueError, MlflowException) as exc:
            print(f"Ошибка MLflow run {run_id!r}: {exc}", file=sys.stderr)
            return 1
    else:
        if not args.experiment:
            print(
                "Нужен --experiment или --run-id (см. main.py promote --help).",
                file=sys.stderr,
            )
            return 1
        promoter = ModelPromoter(
            experiment_name=args.experiment,
            metric=args.metric,
            direction=args.direction,
            min_bets=args.min_bets,
        )
        fixed_candidate = None

    if args.action == "compare":
        if run_id:
            assert fixed_candidate is not None
            print(promoter.render_compare_table([fixed_candidate]))
        else:
            print(promoter.compare(top_n=args.top_n))
        return 0

    if args.action == "best":
        best = fixed_candidate if run_id else promoter.get_best_candidate()
        if best is None:
            print("Нет подходящих кандидатов для промоушна.")
            return 1
        print(f"Лучший кандидат: {best.run_name}")
        print(f"  Run ID:    {best.run_id}")
        print(f"  Algorithm: {best.algorithm}")
        print(f"  Features:  {best.featureset}")
        print(f"  {args.metric}: {best.primary_metric:.6f}")
        return 0

    if args.action == "deploy":
        best = fixed_candidate if run_id else promoter.get_best_candidate()
        if best is None:
            print("Нет подходящих кандидатов для деплоя.")
            return 1
        if args.target_dir:
            target = Path(args.target_dir)
        elif run_id:
            print(
                "Для deploy по --run-id укажите цель явно: --target-dir "
                "(например models/nhl/winner_withOT/best).",
                file=sys.stderr,
            )
            return 1
        else:
            target = PROJECT_ROOT / "models" / "deployed" / args.experiment
        promoter.promote(best, target)
        print(f"Модель задеплоена в: {target}")
        return 0

    return 1


def main() -> int:
    """Главная функция CLI.

    Returns:
        Exit code.
    """
    parser = argparse.ArgumentParser(
        prog="sports-forecast",
        description="Sports Probabilistic Forecasting — ML Pipeline CLI",
    )
    subparsers = parser.add_subparsers(dest="command", help="Доступные команды")

    # ── train ────────────────────────────────────────────────────────────────
    train_parser = subparsers.add_parser(
        "train",
        help="Обучение модели (Hydra CLI)",
    )
    train_parser.add_argument(
        "hydra_args",
        nargs="*",
        help="Аргументы Hydra (e.g. tournament=uel_kz_1 algorithm=catboost)",
    )
    train_parser.set_defaults(func=cmd_train)

    # ── predict ──────────────────────────────────────────────────────────────
    predict_parser = subparsers.add_parser(
        "predict",
        help="Инференс модели (Hydra CLI)",
    )
    predict_parser.add_argument(
        "hydra_args",
        nargs="*",
        help="Аргументы Hydra",
    )
    predict_parser.set_defaults(func=cmd_predict)

    # ── promote ──────────────────────────────────────────────────────────────
    promote_parser = subparsers.add_parser(
        "promote",
        help="Выбор лучшей модели для продакшена",
    )
    promote_parser.add_argument(
        "action",
        choices=["compare", "best", "deploy"],
        help="Действие: compare (таблица), best (лучший), deploy (промоушн)",
    )
    promote_parser.add_argument(
        "--experiment",
        "-e",
        default=None,
        help="Имя MLflow эксперимента (не нужен, если задан --run-id)",
    )
    promote_parser.add_argument(
        "--run-id",
        default=None,
        metavar="RUN_ID",
        help="Зафиксированный MLflow run_id (compare/best/deploy без поиска в эксперименте)",
    )
    promote_parser.add_argument(
        "--metric",
        "-m",
        default="test_logloss",
        help="Метрика для ранжирования (default: test_logloss)",
    )
    promote_parser.add_argument(
        "--direction",
        "-d",
        default="minimize",
        choices=["minimize", "maximize"],
        help="Направление оптимизации (default: minimize)",
    )
    promote_parser.add_argument(
        "--top-n",
        "-n",
        type=int,
        default=5,
        help="Количество лучших кандидатов (default: 5)",
    )
    promote_parser.add_argument(
        "--min-bets",
        type=int,
        default=0,
        help="Минимальное количество ставок для фильтра (default: 0)",
    )
    promote_parser.add_argument(
        "--target-dir",
        "-t",
        default=None,
        help="Директория для деплоя (default: models/deployed/{experiment})",
    )
    promote_parser.set_defaults(func=cmd_promote)

    # ── Parse ────────────────────────────────────────────────────────────────
    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return 0

    func = cast(Callable[[argparse.Namespace], int], args.func)
    return func(args)


if __name__ == "__main__":
    sys.exit(main())
