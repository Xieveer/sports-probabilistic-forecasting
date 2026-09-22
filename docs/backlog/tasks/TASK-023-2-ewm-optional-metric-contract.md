# TASK-023-2 — Согласование тестового контракта optional EWM-метрики

> **Статус:** done
> **Владелец:** implementer
> **Эпик:** [EPIC-023](../EPIC-023-nhl-schedule-agent-pilot.md)

## Результат и границы

Устаревший unit-тест соответствует принятому runtime-контракту: отсутствующая
optional-метрика пропускает только свой EWM-генератор и не отменяет доступные признаки.
Изменяется только тестовое ожидание и docstring существующего публичного метода.

Не изменяются runtime-логика, конфигурация, модели, API, Telegram-бот и production.

## Критерии приёмки

- [x] До изменения воспроизведён падающий тест с устаревшим ожиданием `ValueError`.
- [x] Новый тест подтверждает возврат исходного датафрейма без изменений.
- [x] Полный test suite проходит; результат внесён в отчёт TASK-023-1.
- [x] Независимый reviewer подтверждает отсутствие изменения runtime-поведения.

## Проверка

`uv run pytest tests/test_feature_generators.py::TestEWMFeatureGenerator::test_missing_metric_skips_generator -q`, затем полный `make test`.

## Handoff

Отчёт: [TASK-023-2 done](../../changes/done/TASK-023-2-ewm-optional-metric-contract.md).
TASK намеренно принимается отдельным Git-инкрементом: это независимая коррекция старого
тестового контракта и не часть Telegram-функции TASK-023-1.

## Принятие

Независимый reviewer принял runtime-neutral diff. Commit: `8a30825`
(`test(features): align optional EWM metric contract`); push не выполнялся.
