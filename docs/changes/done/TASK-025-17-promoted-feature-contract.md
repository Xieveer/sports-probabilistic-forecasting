# TASK-025-17 — Признаки promoted-модели в Data Cycle

> **Статус:** код и независимое review завершены; runtime gate открыт
> **Задача:** [TASK-025-17](../../backlog/tasks/TASK-025-17-promoted-feature-contract.md)

## Граница

Feature processing полного NHL Data Cycle использует проверенный contract
promoted bundle, а не независимый runtime override. Диагностика остаётся
безопасной и не раскрывает данные модели, credentials или полный inference
dataset.

## Доказательство

Изолированный production-like replay v1.2.4 подтвердил mismatch 139 против
489 признаков и `CatBoostError`. Red-тест показал передачу `basic` из CLI
при verified bundle `advanced`; green-тест подтверждает `advanced` у
feature builder. Несовместимый algorithm и неизвестный featureset
отклоняются до сборки. 72 целевых и 1207 unit тестов прошли,
`make lint`, `make production-check` и `make docs` (155 warnings) прошли.
Независимый Reviewer не нашёл P0–P2. Runtime release gate открыт.
