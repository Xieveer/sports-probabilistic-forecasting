# TASK-023-2 — отчёт о выполнении

> **Статус задачи:** done
> **Дата:** 2026-09-22
> **Задача:** [TASK-023-2](../../backlog/tasks/TASK-023-2-ewm-optional-metric-contract.md)

## Результат

Устаревший тест `test_missing_metric_raises` приведён к фактическому контракту
`EWMFeatureGenerator`: отсутствующая optional-метрика не прерывает pipeline и возвращает
данные без новых feature-колонок. Runtime-логика не изменилась; уточнён только её docstring.

## Проверки

- `uv run pytest tests/test_feature_generators.py::TestEWMFeatureGenerator::test_missing_metric_skips_generator -q` — 1 passed.
- `make test` — 1032 passed, 37 warnings.
- `make lint` — успешно.
- `uv run pre-commit run mypy --files sports_forecast/features/generators/ewm_generator.py tests/test_feature_generators.py` — успешно.
- `git diff --check` — успешно.

TASK выделена отдельно, поскольку корректирует самостоятельный старый тестовый контракт,
а не Telegram-функцию. Канонический mypy gate pre-commit для затронутых файлов зелёный.

## Review

Независимый reviewer подтвердил отсутствие изменения runtime. Commit: `8a30825`
(`test(features): align optional EWM metric contract`); push не выполнялся.
