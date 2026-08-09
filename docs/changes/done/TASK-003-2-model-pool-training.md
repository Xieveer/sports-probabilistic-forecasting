# TASK-003-2 — отчёт о выполнении

> **Статус задачи:** done
> **Дата:** 2026-08-09
> **Задача:** [TASK-003-2](../../backlog/tasks/TASK-003-2-model-pool-training.md)

## Подтверждённый результат

Добавлен типизированный контракт model pool в
`sports_forecast.training.model_pool`. `build_pool_dataset()` принимает только
минимум два турнира, состоящих в одном пуле и market/spec, проверяет sport и
полное совпадение колонок, затем сохраняет tournament provenance каждой строки.
Нарушение контракта завершается до создания identity или файлового артефакта.

Для valid pool формируется стабильный `model_identity`. `SingleExperimentRunner`
при явном `model_pool` добавляет identity в MLflow-теги, пишет артефакты в
изолированный каталог пула и запускает обучение с уже проверенным dataframe,
не подгружая данные отдельного турнира. Legacy NHL-путь не изменён.

`CandidateReport` требует ML-метрики (`logloss`, `auc`, `brier`), betting
метрики (`roi`, `coverage`, `n_bets`) и разброс симуляций (`roi_std`), после
чего атомарно сохраняется как `candidate-report.json`. Promotion, production
pointer, total, трёхклассовый winner и реальный футбольный источник не
реализованы — это вне scope задачи.

Описание контракта и полей отчёта: [model-pool-training.md](../../development/model-pool-training.md).

## Доказательства

- `uv run pytest tests/test_model_pool.py tests/test_portfolio_catalog.py tests/test_trainer_integration.py -q` — 25 passed.
- `uv run ruff check sports_forecast/training/model_pool.py sports_forecast/training/trainer.py tests/test_model_pool.py tests/test_trainer_integration.py` — успешно.
- `uv run ruff format --check sports_forecast/training/model_pool.py sports_forecast/training/trainer.py tests/test_model_pool.py tests/test_trainer_integration.py` — успешно.
- `uv run pre-commit run mypy --files sports_forecast/training/model_pool.py sports_forecast/training/trainer.py tests/test_model_pool.py tests/test_trainer_integration.py` — успешно.
- `make lint` — успешно.
- `make test-unit` — 811 passed, 8 deselected.

## Остаточные риски и handoff

Тесты используют синтетические football fixtures: совместимый внешний источник
и данные в production не подтверждены. TASK-003-3 должен использовать
`model_identity` для immutable model version и ручного promotion; его входные
артефакты — [TASK-003-2](../../backlog/tasks/TASK-003-2-model-pool-training.md)
и этот отчёт.
