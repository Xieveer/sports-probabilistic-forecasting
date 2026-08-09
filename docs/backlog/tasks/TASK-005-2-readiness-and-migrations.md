# TASK-005-2 — Readiness API и versioned migrations

> **Статус:** done
> **Владелец:** implementer
> **Эпик:** [EPIC-005](../EPIC-005-production-serving-readiness.md)
> **Требование:** [REQ-005](../../product/requirements/REQ-005-production-serving-release.md)
> **ADR:** [ADR-005](../../architecture/adr/ADR-005-production-serving-boundary.md)

## Результат и границы

Ввести `/ready` и отдельную versioned migration command. `/health` сохраняет
liveness процесса; API и Worker перестают изменять schema при startup. Не
менять public prediction contract.

## Критерии приёмки

- [x] `/health` возвращает 2xx без PostgreSQL, `/ready` возвращает non-2xx при
  её недоступности и 2xx только после проверки обязательной DB.
- [x] Migration имеет exact command, additive revision, порядок backup →
  migrate → ready → Worker, idempotency и recovery procedure.
- [x] Частично применённая migration детектируется и завершается понятным
  recovery/forward-fix; automatic destructive downgrade отсутствует.

## План реализации

1. Написать падающие API и PostgreSQL migration tests.
2. Выбрать/внедрить versioned migration mechanism и убрать `init_db()` из
   runtime startup paths; добавить readiness route.
3. Описать backup/recovery/runbook и проверить dry-run на disposable DB.

## Проверка

- Targeted pytest, PostgreSQL integration tests, migration dry-run, `make lint`.

## Handoff и отчёт

- Отчёт выполнения: [TASK-005-2](../../changes/done/TASK-005-2-readiness-and-migrations.md).
