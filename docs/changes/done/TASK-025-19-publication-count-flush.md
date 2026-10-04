# TASK-025-19 — Счётчики publication после flush

> **Статус:** код и независимое review завершены; CI/runtime gate открыт
> **Задача:** [TASK-025-19](../../backlog/tasks/TASK-025-19-publication-count-flush.md)

## Граница

Publication и её counters остаются одной DB-транзакцией; счётчики отражают
фактически записанные прогнозы уже внутри этой транзакции.

## Доказательство

Изолированный replay выявил 1 834 committed predictions и нулевые
in-transaction counters; post-commit readiness дал 187 ready из 187
eligible. Red→green SQL-тест с `autoflush=False` подтвердил flush перед
counts. Fault injection после `mark_stale` доказал rollback внешней
transaction и сохранение прежней витрины. Developer: 139 целевых тестов;
Reviewer: 67 целевых тестов, P0–P2 после correction не осталось. Полный unit
suite: 1227 passed, 13 deselected; `make lint`, `make production-check` и
`make docs` (155 warnings) прошли. PR CI и production gate открыты.

Проверенный content commit: `c8895fdb9fdb3ccba6c74a33373124fa2cefc4a0`.
Reviewer повторно выполнил `make pre-commit` и 67 целевых тестов перед
коммитом; оба gate прошли.
